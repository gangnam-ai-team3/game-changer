from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from agents.audit_strategy import AuditStrategyAgent
from agents.collector import CollectionOptions, CollectorAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import StructuredModelError
from contracts import (
    Artifact,
    ArtifactStatus,
    DecisionBrief,
    ErrorCode,
    EventBrief,
    EvidencePack,
    FeedbackBundle,
    InputMode,
    Producer,
    RiskAssessment,
    ValidatedDecision,
)
from policy import POLICY_VERSION

T = TypeVar("T", bound=Artifact)
StageCallback = Callable[[str, str, str], None]


class PipelineStopped(RuntimeError):
    pass


@dataclass(slots=True)
class PipelineResult:
    feedback: FeedbackBundle
    evidence: EvidencePack
    risks: RiskAssessment
    validated: ValidatedDecision
    brief: DecisionBrief
    fallback_used: bool = False
    analysis_incomplete: bool = False


class EventPreflightOrchestrator:
    def __init__(
        self,
        *,
        use_llm: bool = False,
        collector: CollectorAgent | None = None,
        evidence_rag: EvidenceRagAgent | None = None,
        redteam: EventRedteamAgent | None = None,
        audit: AuditStrategyAgent | None = None,
    ) -> None:
        self.collector = collector or CollectorAgent()
        self.evidence_rag = evidence_rag or EvidenceRagAgent(use_llm=use_llm)
        self.redteam = redteam or EventRedteamAgent(use_llm=use_llm)
        self.audit = audit or AuditStrategyAgent(use_llm=use_llm)

    def run(
        self,
        event: EventBrief,
        options: CollectionOptions | None = None,
        *,
        on_stage: StageCallback | None = None,
        log_path: Path | None = None,
    ) -> PipelineResult:
        if event.producer != Producer.USER:
            raise PipelineStopped("EventBrief producer must be user")
        options = options or CollectionOptions()
        notify = on_stage or (lambda _stage, _status, _message: None)
        fallback_used = False
        analysis_incomplete = False

        feedback = self._stage(
            "collection",
            lambda: self.collector.run(event, options),
            FeedbackBundle,
            Producer.COLLECTOR,
            event.run_id,
            {event.ref},
            notify,
        )
        reproducibility_metadata = {
            "policy_version": POLICY_VERSION,
            "input_snapshot_hash": _input_snapshot_hash(event, feedback),
        }
        feedback = self._check(
            feedback.model_copy(update=reproducibility_metadata),
            FeedbackBundle,
            Producer.COLLECTOR,
            event.run_id,
            {event.ref},
        )
        self._write(feedback, log_path)
        try:
            evidence = self._stage(
                "evidence_rag_personas",
                lambda: self.evidence_rag.run(feedback),
                EvidencePack,
                Producer.EVIDENCE_RAG,
                event.run_id,
                {feedback.ref},
                notify,
                reproducibility_metadata,
            )
        except StructuredModelError:
            fallback_used = True
            analysis_incomplete = feedback.input_mode != InputMode.FIXTURE
            evidence = self._deterministic_stage(
                "evidence_rag_personas",
                feedback,
                output_type=EvidencePack,
                producer=Producer.EVIDENCE_RAG,
                run_id=event.run_id,
                required_refs={feedback.ref},
                notify=notify,
                reproducibility_metadata=reproducibility_metadata,
            )
        self._write(evidence, log_path)
        if analysis_incomplete:
            risks = self._deterministic_stage(
                "event_redteam",
                event,
                evidence,
                output_type=RiskAssessment,
                producer=Producer.EVENT_REDTEAM,
                run_id=event.run_id,
                required_refs={event.ref, evidence.ref},
                notify=notify,
                reproducibility_metadata=reproducibility_metadata,
            )
        else:
            try:
                risks = self._stage(
                    "event_redteam",
                    lambda: self.redteam.run(event, evidence),
                    RiskAssessment,
                    Producer.EVENT_REDTEAM,
                    event.run_id,
                    {event.ref, evidence.ref},
                    notify,
                    reproducibility_metadata,
                )
            except StructuredModelError:
                fallback_used = True
                analysis_incomplete = feedback.input_mode != InputMode.FIXTURE
                risks = self._deterministic_stage(
                    "event_redteam",
                    event,
                    evidence,
                    output_type=RiskAssessment,
                    producer=Producer.EVENT_REDTEAM,
                    run_id=event.run_id,
                    required_refs={event.ref, evidence.ref},
                    notify=notify,
                    reproducibility_metadata=reproducibility_metadata,
                )
        self._write(risks, log_path)
        if analysis_incomplete:
            validated = self._deterministic_stage(
                "audit_strategy",
                feedback,
                evidence,
                risks,
                output_type=ValidatedDecision,
                producer=Producer.AUDIT_STRATEGY,
                run_id=event.run_id,
                required_refs={feedback.ref, evidence.ref, risks.ref},
                notify=notify,
                analysis_incomplete=True,
                reproducibility_metadata=reproducibility_metadata,
            )
        else:
            try:
                validated = self._stage(
                    "audit_strategy",
                    lambda: self.audit.run(feedback, evidence, risks),
                    ValidatedDecision,
                    Producer.AUDIT_STRATEGY,
                    event.run_id,
                    {feedback.ref, evidence.ref, risks.ref},
                    notify,
                    reproducibility_metadata,
                )
            except StructuredModelError:
                fallback_used = True
                analysis_incomplete = feedback.input_mode != InputMode.FIXTURE
                validated = self._deterministic_stage(
                    "audit_strategy",
                    feedback,
                    evidence,
                    risks,
                    output_type=ValidatedDecision,
                    producer=Producer.AUDIT_STRATEGY,
                    run_id=event.run_id,
                    required_refs={feedback.ref, evidence.ref, risks.ref},
                    notify=notify,
                    analysis_incomplete=analysis_incomplete,
                    reproducibility_metadata=reproducibility_metadata,
                )
        self._write(validated, log_path)
        brief = self.audit.to_brief(event, evidence, validated).model_copy(
            update=reproducibility_metadata
        )
        self._check(brief, DecisionBrief, Producer.ORCHESTRATOR, event.run_id, {event.ref, evidence.ref, validated.ref})
        self._write(brief, log_path)
        notify("decision_brief", "complete", brief.decision.value)
        return PipelineResult(
            feedback,
            evidence,
            risks,
            validated,
            brief,
            fallback_used=fallback_used,
            analysis_incomplete=analysis_incomplete,
        )

    def _stage(
        self,
        name: str,
        call: Callable[[], T],
        output_type: type[T],
        producer: Producer,
        run_id: str,
        required_refs: set[str],
        notify: StageCallback,
        reproducibility_metadata: dict[str, str] | None = None,
    ) -> T:
        notify(name, "running", "started")
        for attempt in range(2):
            try:
                result = call()
                if reproducibility_metadata:
                    result = result.model_copy(update=reproducibility_metadata)
                checked = self._check(result, output_type, producer, run_id, required_refs)
                if checked.status == ArtifactStatus.FAILED:
                    raise PipelineStopped(f"{name} returned failed status")
                notify(name, "complete", f"attempt {attempt + 1}")
                return checked
            except StructuredModelError as exc:
                if exc.code in {ErrorCode.SCHEMA_INVALID, ErrorCode.LLM_REFUSAL}:
                    if attempt == 0:
                        notify(name, "retrying", "schema/refusal validation failed")
                        continue
                    notify(name, "failed", f"{exc.code.value}: {exc}")
                    raise
                notify(name, "failed", f"{exc.code.value}: {exc}")
                raise PipelineStopped(f"{name}: {exc.code.value}: {exc}") from exc
            except (ValidationError, ContractViolation) as exc:
                notify(name, "failed", str(exc))
                raise PipelineStopped(f"{name}: SCHEMA_INVALID: {exc}") from exc
        raise AssertionError("unreachable")

    def _deterministic_stage(
        self,
        name: str,
        *args,
        output_type: type[T],
        producer: Producer,
        run_id: str,
        required_refs: set[str],
        notify: StageCallback,
        analysis_incomplete: bool = False,
        reproducibility_metadata: dict[str, str] | None = None,
    ) -> T:
        try:
            if name == "evidence_rag_personas":
                result = self.evidence_rag.run_deterministic(*args)
            elif name == "event_redteam":
                result = self.redteam.run_deterministic(*args)
            elif name == "audit_strategy":
                result = self.audit.run_deterministic(
                    *args,
                    analysis_incomplete=analysis_incomplete,
                )
            else:
                raise ValueError(f"unknown deterministic stage: {name}")
            if reproducibility_metadata:
                result = result.model_copy(update=reproducibility_metadata)
            checked = self._check(result, output_type, producer, run_id, required_refs)
            if checked.status == ArtifactStatus.FAILED:
                raise PipelineStopped(f"{name} returned failed status")
        except (ValidationError, ContractViolation) as exc:
            notify(name, "failed", str(exc))
            raise PipelineStopped(f"{name}: SCHEMA_INVALID: {exc}") from exc
        notify(name, "complete", "deterministic fallback")
        return checked

    @staticmethod
    def _check(
        result: Artifact,
        output_type: type[T],
        producer: Producer,
        run_id: str,
        required_refs: set[str],
    ) -> T:
        checked = output_type.model_validate(result.model_dump(mode="python"))
        if checked.run_id != run_id:
            raise ContractViolation("run_id changed between stages")
        if checked.producer != producer:
            raise ContractViolation(f"expected producer {producer.value}, got {checked.producer.value}")
        if not required_refs.issubset(set(checked.input_refs)):
            raise ContractViolation("required input_refs are missing")
        return checked

    @staticmethod
    def _write(artifact: Artifact, log_path: Path | None) -> None:
        if log_path is None:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False) + "\n")


class ContractViolation(ValueError):
    pass


def _input_snapshot_hash(event: EventBrief, feedback: FeedbackBundle) -> str:
    event_body = event.model_dump(
        mode="json",
        exclude={"run_id", "producer", "input_refs", "status", "errors", "input_snapshot_hash"},
    )
    evidence = [
        {
            "evidence_id": item.evidence_id,
            "source": item.source.value,
            "source_id": item.source_id,
            "language": item.language.value,
            "observed_at": item.observed_at.isoformat(),
            "summary": item.summary,
            "mechanism_tags": sorted(item.mechanism_tags),
            "relevance": item.relevance,
        }
        for item in sorted(feedback.evidence, key=lambda item: item.evidence_id)
    ]
    payload = {"event": event_body, "input_mode": feedback.input_mode.value, "evidence": evidence}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
