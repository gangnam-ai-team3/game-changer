from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from agents.structured import ClaudeBudget, StructuredModelError
from contracts import Artifact, ArtifactStatus, ErrorCode, InputMode, Producer
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
        budget: ClaudeBudget | None = None,
    ) -> None:
        budget = budget if budget is not None else (ClaudeBudget() if use_llm else None)
        self.collector = collector or UpdateCollectorAgent(
            use_llm=use_llm, client=llm_client, budget=budget
        )
        self.evidence_agent = evidence or UpdateEvidenceAgent(
            use_llm=use_llm, client=llm_client, budget=budget
        )
        self.redteam = redteam or UpdateRedteamAgent(
            use_llm=use_llm, client=llm_client, budget=budget
        )
        self.audit = audit or UpdateAuditAgent(
            use_llm=use_llm, client=llm_client, budget=budget
        )
        self.budget = budget
        self.use_llm = use_llm
        self.llm_provider = "claude" if use_llm else "deterministic"
        self.llm_requested = use_llm

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
        fallback_used = False
        force_deterministic = False
        analysis_incomplete = False

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

        def stage(
            agent,
            llm_call,
            deterministic_call,
            output_type,
            producer,
            refs,
            *,
            allow_llm: bool,
        ):
            nonlocal fallback_used
            emit(agent, "agent", ExecutionState.RUNNING, "업데이트 점검 단계를 시작했습니다.")
            if not allow_llm or force_deterministic:
                result = deterministic_call()
            else:
                try:
                    result = llm_call()
                except StructuredModelError as exc:
                    can_retry = (
                        exc.code in {ErrorCode.SCHEMA_INVALID, ErrorCode.LLM_REFUSAL}
                        and self._has_retry_budget()
                    )
                    if can_retry:
                        fallback_used = True
                        emit(
                            agent,
                            "agent",
                            ExecutionState.RETRYING,
                            "Claude 자연어 결과를 계약 범위 안에서 다시 요청합니다.",
                        )
                        try:
                            result = llm_call()
                        except StructuredModelError as retry_error:
                            emit(
                                agent,
                                "fallback",
                                ExecutionState.RUNNING,
                                "Claude 설명을 제외하고 결정론적 안전 경로를 사용합니다.",
                                {"reason": retry_error.code.value},
                            )
                            result = deterministic_call()
                    else:
                        fallback_used = True
                        emit(
                            agent,
                            "fallback",
                            ExecutionState.RUNNING,
                            "Claude 설명을 제외하고 결정론적 안전 경로를 사용합니다.",
                            {"reason": exc.code.value},
                        )
                        result = deterministic_call()
            result = self._check(result, output_type, producer, brief.run_id, refs)
            if result.status == ArtifactStatus.FAILED:
                raise PipelineStopped(f"{agent} returned failed status")
            emit(agent, "agent", ExecutionState.COMPLETE, "업데이트 점검 단계를 완료했습니다.")
            self._write(result, log_path)
            return result

        feedback = stage(
            "collection",
            lambda: self.collector.run(brief, options, nodes("collection")),
            lambda: self.collector.run(brief, options, nodes("collection")),
            UpdateFeedbackBundle,
            Producer.COLLECTOR,
            {brief.ref},
            allow_llm=False,
        )
        metadata = {"input_snapshot_hash": _input_snapshot_hash(brief, feedback)}
        feedback = feedback.model_copy(update=metadata)
        # An external source that failed, produced no normalized evidence, or
        # missed the five-language sample gate is not comparable to the
        # deterministic fixture.  Keep its partial artifacts for auditability,
        # but make every downstream decision path deterministic and force the
        # policy-owned Hold outcome.
        analysis_incomplete = feedback.input_mode != InputMode.FIXTURE and (
            bool(feedback.errors)
            or not feedback.evidence
            or any(not sample.sufficient for sample in feedback.samples)
        )
        if analysis_incomplete:
            force_deterministic = True
        evidence_event_start = len(events)
        evidence = stage(
            "evidence_rag_personas",
            lambda: self.evidence_agent.run(
                feedback, nodes("evidence_rag_personas")
            ).model_copy(update=metadata),
            lambda: self.evidence_agent.run_deterministic(
                feedback, nodes("evidence_rag_personas")
            ).model_copy(update=metadata),
            UpdateEvidencePack,
            Producer.EVIDENCE_RAG,
            {feedback.ref},
            allow_llm=self.use_llm,
        )
        fallback_used = fallback_used or any(
            event.node == "persona_copy_fallback"
            for event in events[evidence_event_start:]
        )
        impact = stage(
            "event_redteam",
            lambda: self.redteam.run(
                brief, evidence, nodes("event_redteam")
            ).model_copy(update=metadata),
            lambda: self.redteam.run_deterministic(
                brief, evidence, nodes("event_redteam")
            ).model_copy(update=metadata),
            UpdateImpactAssessment,
            Producer.EVENT_REDTEAM,
            {brief.ref, evidence.ref},
            allow_llm=self.use_llm,
        )
        validated = stage(
            "audit_strategy",
            lambda: self.audit.run(
                feedback,
                evidence,
                impact,
                analysis_incomplete=analysis_incomplete,
                on_event=nodes("audit_strategy"),
            ).model_copy(update=metadata),
            lambda: self.audit.run_deterministic(
                feedback,
                evidence,
                impact,
                analysis_incomplete=analysis_incomplete,
                on_event=nodes("audit_strategy"),
            ).model_copy(update=metadata),
            UpdateValidatedDecision,
            Producer.AUDIT_STRATEGY,
            {feedback.ref, evidence.ref, impact.ref},
            allow_llm=self.use_llm and feedback.input_mode != InputMode.LIVE,
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
        return UpdatePipelineResult(
            feedback,
            evidence,
            impact,
            validated,
            final,
            events,
            fallback_used=fallback_used,
            analysis_incomplete=analysis_incomplete,
            llm_provider=self.llm_provider,
            llm_requested=self.llm_requested,
        )

    def _has_retry_budget(self) -> bool:
        return self.budget is not None and self.budget.requests < self.budget.max_requests

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
        # Error codes (not potentially sensitive provider messages) affect the
        # external-source Hold gate and therefore belong in reproducibility
        # input.  Their code-owned text is intentionally excluded.
        "errors": sorted(
            (item.code.value, item.retryable) for item in feedback.errors
        ),
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
