from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from contracts import Artifact, ArtifactStatus, Producer
from execution import EventCallback, ExecutionEvent, ExecutionState
from orchestrator import ContractViolation, PipelineStopped
from update_review.audit import UpdateAuditAgent
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import (
    UpdateBrief,
    UpdateDecisionBrief,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateImpactAssessment,
    UpdateValidatedDecision,
)
from update_review.evidence import UpdateEvidenceAgent
from update_review.redteam import UpdateRedteamAgent


@dataclass(slots=True)
class UpdatePipelineResult:
    feedback: UpdateFeedbackBundle
    evidence: UpdateEvidencePack
    impact: UpdateImpactAssessment
    validated: UpdateValidatedDecision
    brief: UpdateDecisionBrief
    events: list[ExecutionEvent]
    fallback_used: bool = False
    analysis_incomplete: bool = False
    llm_provider: str = "deterministic"
    llm_requested: bool = False


class UpdateReviewOrchestrator:
    def __init__(
        self,
        *,
        collector=None,
        evidence=None,
        redteam=None,
        audit=None,
        use_llm: bool = False,
        llm_client=None,
    ) -> None:
        self.collector = collector or UpdateCollectorAgent()
        self.evidence_agent = evidence or UpdateEvidenceAgent()
        self.redteam = redteam or UpdateRedteamAgent()
        self.audit = audit or UpdateAuditAgent()
        self.use_llm = use_llm
        self.llm_client = llm_client

    def run(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions | None = None,
        *,
        on_event: EventCallback | None = None,
        log_path: Path | None = None,
    ) -> UpdatePipelineResult:
        if brief.producer != Producer.USER:
            raise PipelineStopped("UpdateBrief producer must be user")
        options = options or UpdateCollectionOptions()
        events: list[ExecutionEvent] = []

        def emit(agent, node, state, message, metrics=None):
            item = ExecutionEvent(
                sequence=len(events),
                agent=agent,
                node=node,
                state=state,
                message=message,
                metrics=metrics or {},
            )
            events.append(item)
            if on_event:
                on_event(item)
            self._write(item, log_path)

        def nodes(agent):
            return lambda node, message, metrics: emit(
                agent, node, ExecutionState.RUNNING, message, metrics
            )

        def stage(agent, call, output_type, producer, refs):
            emit(agent, "agent", ExecutionState.RUNNING, "업데이트 점검 단계를 시작했습니다.")
            result = self._check(call(), output_type, producer, brief.run_id, refs)
            if result.status == ArtifactStatus.FAILED:
                raise PipelineStopped(f"{agent} returned failed status")
            emit(agent, "agent", ExecutionState.COMPLETE, "업데이트 점검 단계를 완료했습니다.")
            self._write(result, log_path)
            return result

        feedback = stage(
            "collection",
            lambda: self.collector.run(brief, options, nodes("collection")),
            UpdateFeedbackBundle,
            Producer.COLLECTOR,
            {brief.ref},
        )
        metadata = {"input_snapshot_hash": _input_snapshot_hash(brief, feedback)}
        feedback = feedback.model_copy(update=metadata)
        evidence = stage(
            "evidence_rag_personas",
            lambda: self.evidence_agent.run_deterministic(
                feedback, nodes("evidence_rag_personas")
            ).model_copy(update=metadata),
            UpdateEvidencePack,
            Producer.EVIDENCE_RAG,
            {feedback.ref},
        )
        impact = stage(
            "event_redteam",
            lambda: self.redteam.run_deterministic(
                brief, evidence, nodes("event_redteam")
            ).model_copy(update=metadata),
            UpdateImpactAssessment,
            Producer.EVENT_REDTEAM,
            {brief.ref, evidence.ref},
        )
        validated = stage(
            "audit_strategy",
            lambda: self.audit.run_deterministic(
                feedback,
                evidence,
                impact,
                on_event=nodes("audit_strategy"),
            ).model_copy(update=metadata),
            UpdateValidatedDecision,
            Producer.AUDIT_STRATEGY,
            {feedback.ref, evidence.ref, impact.ref},
        )
        final = self.audit.to_brief(brief, evidence, impact, validated).model_copy(
            update=metadata
        )
        final = self._check(
            final,
            UpdateDecisionBrief,
            Producer.ORCHESTRATOR,
            brief.run_id,
            {brief.ref, evidence.ref, impact.ref, validated.ref},
        )
        self._write(final, log_path)
        return UpdatePipelineResult(feedback, evidence, impact, validated, final, events)

    @staticmethod
    def _check(result: Artifact, output_type, producer: Producer, run_id: str, refs: set[str]):
        checked = output_type.model_validate(result.model_dump(mode="python"))
        if checked.run_id != run_id:
            raise ContractViolation("run_id changed between stages")
        if checked.producer != producer:
            raise ContractViolation(
                f"expected producer {producer.value}, got {checked.producer.value}"
            )
        if not refs <= set(checked.input_refs):
            raise ContractViolation("required input_refs are missing")
        return checked

    @staticmethod
    def _write(value: Artifact | ExecutionEvent, log_path: Path | None) -> None:
        if log_path is None:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _input_snapshot_hash(brief: UpdateBrief, feedback: UpdateFeedbackBundle) -> str:
    payload = {
        "brief": brief.model_dump(
            mode="json",
            exclude={
                "run_id",
                "producer",
                "input_refs",
                "status",
                "errors",
                "input_snapshot_hash",
            },
        ),
        "input_mode": feedback.input_mode.value,
        "samples": sorted(
            (item.language.value, item.general_count, item.mechanism_count)
            for item in feedback.samples
        ),
        "evidence": sorted(
            [item.model_dump(mode="json") for item in feedback.evidence],
            key=lambda item: (item["source"], item["source_id"], item["evidence_id"]),
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
