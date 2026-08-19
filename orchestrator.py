from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from agents.audit_strategy import AuditStrategyAgent
from agents.collector import CollectionOptions, CollectorAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import ClaudeBudget, StructuredModelError
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
from execution import AGENT_ORDER, EventCallback, ExecutionEvent, ExecutionState
from policy import POLICY_VERSION

T = TypeVar("T", bound=Artifact)


class PipelineStopped(RuntimeError):
    pass


@dataclass(slots=True)
class PipelineResult:
    feedback: FeedbackBundle
    evidence: EvidencePack
    risks: RiskAssessment
    validated: ValidatedDecision
    brief: DecisionBrief
    events: list[ExecutionEvent]
    fallback_used: bool = False
    analysis_incomplete: bool = False
    llm_provider: str = "deterministic"
    llm_requested: bool = False


class EventPreflightOrchestrator:
    def __init__(
        self,
        *,
        use_llm: bool = False,
        llm_provider: str | None = None,
        llm_client=None,
        collector: CollectorAgent | None = None,
        evidence_rag: EvidenceRagAgent | None = None,
        redteam: EventRedteamAgent | None = None,
        audit: AuditStrategyAgent | None = None,
    ) -> None:
        provider = llm_provider or os.getenv("LLM_PROVIDER", "claude")
        budget = ClaudeBudget() if use_llm and provider == "claude" else None
        self.collector = collector or CollectorAgent()
        self.evidence_rag = evidence_rag or EvidenceRagAgent(
            use_llm=use_llm, client=llm_client, provider=provider, budget=budget
        )
        self.redteam = redteam or EventRedteamAgent(
            use_llm=use_llm, client=llm_client, provider=provider, budget=budget
        )
        self.audit = audit or AuditStrategyAgent(
            use_llm=use_llm, client=llm_client, provider=provider, budget=budget
        )
        self.llm_provider = provider if use_llm else "deterministic"
        self.llm_requested = use_llm

    def run(
        self,
        event: EventBrief,
        options: CollectionOptions | None = None,
        *,
        on_event: EventCallback | None = None,
        log_path: Path | None = None,
    ) -> PipelineResult:
        if event.producer != Producer.USER:
            raise PipelineStopped("EventBrief producer must be user")
        options = options or CollectionOptions()
        events: list[ExecutionEvent] = []

        def emit(
            agent: str,
            node: str,
            state: ExecutionState,
            message: str,
            metrics: dict[str, int | float | str | bool] | None = None,
        ) -> None:
            item = ExecutionEvent(
                sequence=len(events),
                agent=agent,
                node=node,
                state=state,
                message=message,
                metrics=metrics or {},
            )
            events.append(item)
            if on_event is not None:
                on_event(item)
            self._write(item, log_path)

        def agent_events(agent: str) -> Callable[[str, str, dict], None]:
            return lambda node, message, metrics: emit(
                agent, node, ExecutionState.RUNNING, message, metrics
            )

        for agent in AGENT_ORDER:
            emit(agent, "queued", ExecutionState.WAITING, "실행 대기 중입니다.")
        fallback_used = False
        analysis_incomplete = False

        feedback = self._stage(
            "collection",
            lambda: self.collector.run(event, options, on_event=agent_events("collection")),
            FeedbackBundle,
            Producer.COLLECTOR,
            event.run_id,
            {event.ref},
            emit,
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
        analysis_incomplete = (
            feedback.input_mode == InputMode.CORPUS
            and feedback.status == ArtifactStatus.PARTIAL
        )
        self._write(feedback, log_path)
        try:
            evidence = self._stage(
                "evidence_rag_personas",
                lambda: self.evidence_rag.run(
                    feedback, on_event=agent_events("evidence_rag_personas")
                ),
                EvidencePack,
                Producer.EVIDENCE_RAG,
                event.run_id,
                {feedback.ref},
                emit,
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
                emit=emit,
                on_event=agent_events("evidence_rag_personas"),
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
                emit=emit,
                on_event=agent_events("event_redteam"),
                reproducibility_metadata=reproducibility_metadata,
            )
        else:
            try:
                risks = self._stage(
                    "event_redteam",
                    lambda: self.redteam.run(
                        event, evidence, on_event=agent_events("event_redteam")
                    ),
                    RiskAssessment,
                    Producer.EVENT_REDTEAM,
                    event.run_id,
                    {event.ref, evidence.ref},
                    emit,
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
                    emit=emit,
                    on_event=agent_events("event_redteam"),
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
                emit=emit,
                on_event=agent_events("audit_strategy"),
                analysis_incomplete=True,
                reproducibility_metadata=reproducibility_metadata,
            )
        else:
            try:
                validated = self._stage(
                    "audit_strategy",
                    lambda: self.audit.run(
                        feedback, evidence, risks, on_event=agent_events("audit_strategy")
                    ),
                    ValidatedDecision,
                    Producer.AUDIT_STRATEGY,
                    event.run_id,
                    {feedback.ref, evidence.ref, risks.ref},
                    emit,
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
                    emit=emit,
                    on_event=agent_events("audit_strategy"),
                    analysis_incomplete=analysis_incomplete,
                    reproducibility_metadata=reproducibility_metadata,
                )
        self._write(validated, log_path)
        brief = self.audit.to_brief(event, evidence, validated).model_copy(
            update=reproducibility_metadata
        )
        self._check(brief, DecisionBrief, Producer.ORCHESTRATOR, event.run_id, {event.ref, evidence.ref, validated.ref})
        self._write(brief, log_path)
        return PipelineResult(
            feedback,
            evidence,
            risks,
            validated,
            brief,
            events,
            fallback_used=fallback_used,
            analysis_incomplete=analysis_incomplete,
            llm_provider=self.llm_provider,
            llm_requested=self.llm_requested,
        )

    def _stage(
        self,
        name: str,
        call: Callable[[], T],
        output_type: type[T],
        producer: Producer,
        run_id: str,
        required_refs: set[str],
        emit: Callable[
            [str, str, ExecutionState, str, dict[str, int | float | str | bool] | None], None
        ],
        reproducibility_metadata: dict[str, str] | None = None,
    ) -> T:
        emit(name, "agent", ExecutionState.RUNNING, "실행을 시작했습니다.")
        for attempt in range(2):
            try:
                result = call()
                if reproducibility_metadata:
                    result = result.model_copy(update=reproducibility_metadata)
                checked = self._check(result, output_type, producer, run_id, required_refs)
                if checked.status == ArtifactStatus.FAILED:
                    raise PipelineStopped(f"{name} returned failed status")
                emit(name, "agent", ExecutionState.COMPLETE, f"시도 {attempt + 1}회로 완료했습니다.")
                return checked
            except PipelineStopped as exc:
                emit(name, "agent", ExecutionState.FAILED, str(exc))
                raise
            except StructuredModelError as exc:
                if exc.code in {ErrorCode.SCHEMA_INVALID, ErrorCode.LLM_REFUSAL}:
                    if attempt == 0:
                        emit(
                            name,
                            "agent",
                            ExecutionState.RETRYING,
                            "구조화 출력 검증을 다시 시도합니다.",
                        )
                        continue
                    emit(name, "agent", ExecutionState.FAILED, f"{exc.code.value}: {exc}")
                    raise
                emit(name, "agent", ExecutionState.FAILED, f"{exc.code.value}: 안전 경로로 전환합니다.")
                raise
            except (ValidationError, ContractViolation) as exc:
                emit(name, "agent", ExecutionState.FAILED, str(exc))
                raise PipelineStopped(f"{name}: SCHEMA_INVALID: {exc}") from exc
            except Exception as exc:
                error_type = type(exc).__name__
                emit(
                    name,
                    "agent",
                    ExecutionState.FAILED,
                    f"예상하지 못한 {error_type} 오류로 실행을 중단했습니다.",
                    {"error_type": error_type},
                )
                raise PipelineStopped(f"{name}: unexpected {error_type}") from exc
        raise AssertionError("unreachable")

    def _deterministic_stage(
        self,
        name: str,
        *args,
        output_type: type[T],
        producer: Producer,
        run_id: str,
        required_refs: set[str],
        emit: Callable[
            [str, str, ExecutionState, str, dict[str, int | float | str | bool] | None], None
        ],
        on_event: Callable[[str, str, dict], None],
        analysis_incomplete: bool = False,
        reproducibility_metadata: dict[str, str] | None = None,
    ) -> T:
        emit(name, "agent", ExecutionState.RUNNING, "결정론적 안전 경로를 시작했습니다.")
        try:
            if name == "evidence_rag_personas":
                result = self.evidence_rag.run_deterministic(*args, on_event=on_event)
            elif name == "event_redteam":
                result = self.redteam.run_deterministic(*args, on_event=on_event)
            elif name == "audit_strategy":
                result = self.audit.run_deterministic(
                    *args,
                    analysis_incomplete=analysis_incomplete,
                    on_event=on_event,
                )
            else:
                raise ValueError(f"unknown deterministic stage: {name}")
            if reproducibility_metadata:
                result = result.model_copy(update=reproducibility_metadata)
            checked = self._check(result, output_type, producer, run_id, required_refs)
            if checked.status == ArtifactStatus.FAILED:
                raise PipelineStopped(f"{name} returned failed status")
        except PipelineStopped as exc:
            emit(name, "agent", ExecutionState.FAILED, str(exc))
            raise
        except (ValidationError, ContractViolation) as exc:
            emit(name, "agent", ExecutionState.FAILED, str(exc))
            raise PipelineStopped(f"{name}: SCHEMA_INVALID: {exc}") from exc
        except Exception as exc:
            error_type = type(exc).__name__
            emit(
                name,
                "agent",
                ExecutionState.FAILED,
                f"예상하지 못한 {error_type} 오류로 실행을 중단했습니다.",
                {"error_type": error_type},
            )
            raise PipelineStopped(f"{name}: unexpected {error_type}") from exc
        emit(name, "agent", ExecutionState.COMPLETE, "결정론적 안전 경로를 완료했습니다.")
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
    def _write(artifact: Artifact | ExecutionEvent, log_path: Path | None) -> None:
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
    samples = [
        {
            "language": sample.language.value,
            "general_count": sample.general_count,
            "mechanism_count": sample.mechanism_count,
        }
        for sample in sorted(feedback.samples, key=lambda sample: sample.language.value)
    ]
    payload = {
        "event": event_body,
        "input_mode": feedback.input_mode.value,
        "samples": samples,
        "evidence": evidence,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
