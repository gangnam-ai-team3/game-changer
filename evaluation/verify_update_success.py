from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict

from agents.structured import ClaudeBudget
from connectors import ConnectorError, RawFeedback
from contracts import ArtifactStatus, ErrorCode, InputMode, Language, SourceType
from execution import AGENT_ORDER, ExecutionState
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import EvidencePeriod, UpdateDecision
from update_review.fixtures import load_dragunov_brief
from update_review.orchestrator import UpdatePipelineResult, UpdateReviewOrchestrator


class UpdateSuccessReport(BaseModel):
    """Deterministic acceptance result for the Dragunov pre-launch fixture."""

    model_config = ConfigDict(extra="forbid")

    decision: UpdateDecision
    evidence_count: int
    synthetic_only: bool
    comparable_reference_only: bool
    actual_after_count: int
    no_after_leakage: bool
    reproducible_core: bool
    semantic_links_valid: bool
    event_sequence_valid: bool
    partial_hold_safe: bool
    llm_fallback_budget_safe: bool
    source_metadata_safe: bool
    input_snapshot_hash: str
    runtime_seconds: float
    passed: bool


def core_outcome(result: UpdatePipelineResult) -> tuple:
    """Compare policy-owned outcome only; run IDs and prose may vary."""

    return (
        result.brief.decision,
        tuple(
            (
                item.risk_id,
                item.category,
                item.severity,
                tuple(sorted(item.evidence_ids)),
            )
            for item in result.brief.top_risks
        ),
        tuple(
            (item.metric_id, tuple(sorted(item.addresses_risk_ids)))
            for item in result.brief.validation_metrics
        ),
        tuple(sorted(item.evidence_id for item in result.brief.evidence)),
        result.brief.policy_version,
        result.brief.input_snapshot_hash,
    )


def _semantic_links_valid(result: UpdatePipelineResult) -> bool:
    evidence_ids = {item.evidence_id for item in result.brief.evidence}
    risk_ids = {item.risk_id for item in result.brief.top_risks}
    metric_ids = {item.metric_id for item in result.brief.validation_metrics}
    evidence_references = [
        *result.evidence.positive_signals,
        *result.evidence.negative_signals,
        *result.evidence.split_conditions,
        *result.evidence.persona_impacts,
        *result.impact.expected_positive,
        *result.impact.expected_negative,
        *result.brief.expected_positive,
        *result.brief.expected_negative,
        *result.brief.split_conditions,
        *result.brief.persona_impacts,
        *result.brief.top_risks,
    ]
    return (
        all(set(item.evidence_ids) <= evidence_ids for item in evidence_references)
        and all(
            set(item.addresses_risk_ids) <= risk_ids
            for item in result.brief.validation_metrics
        )
        and all(
            set(item.addresses_risk_ids) <= risk_ids
            and set(item.validation_metric_ids) <= metric_ids
            for item in result.brief.recommendations
        )
    )


def _period_is(item, expected: EvidencePeriod) -> bool:
    """Fail closed even if an adversarial model_copy injected a raw string."""

    period = getattr(item, "period", None)
    return getattr(period, "value", period) == expected.value


class _ToolMessages:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=payload)]
        )


class _RefusalMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="refusal")])


class _SingleLanguageSteam:
    def __init__(self, row: RawFeedback) -> None:
        self.row = row

    def fetch_reviews(self, _app_id, language, _cutoff_at, *, start_at=None):
        del start_at
        return [self.row] if language is self.row.language else []


class _UnavailableSteam:
    def fetch_reviews(self, *_args, **_kwargs):
        raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "fixture outage")


def _live_source_id(source: SourceType, source_id: str) -> str:
    digest = hashlib.sha256(f"{source.value}:{source_id}".encode("utf-8")).hexdigest()[:20]
    return f"{source.value}-{digest}"


def _partial_failure_holds() -> bool:
    """A live connector failure must remain partial and never use the fixture."""

    brief = load_dragunov_brief("update-success-live-failure")
    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(steam=_UnavailableSteam())
    ).run(
        brief,
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            period_start=brief.cutoff_at - timedelta(days=7),
            period_end=brief.cutoff_at,
        ),
    )
    return (
        result.feedback.input_mode is InputMode.LIVE
        and result.feedback.status is ArtifactStatus.PARTIAL
        and result.brief.decision is UpdateDecision.HOLD
        and result.analysis_incomplete
        and not result.fallback_used
        and not result.feedback.evidence
        and any(item.code is ErrorCode.SOURCE_UNAVAILABLE for item in result.feedback.errors)
        and not any(item.synthetic for item in result.brief.evidence)
    )


def _source_metadata_safe() -> bool:
    """Exercise live metadata normalization with fakes, never an external key."""

    brief = load_dragunov_brief("update-success-live-safety")
    raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="private-live-id-7f80",
        language=Language.KOREAN,
        observed_at=brief.cutoff_at - timedelta(days=1),
        text="PRIVATE-LIVE-TEXT-7f80은 결과물이나 로그에 남으면 안 됩니다.",
    )
    messages = _ToolMessages(
        [
            {
                "items": [
                    {
                        "source_id": _live_source_id(raw.source, raw.source_id),
                        "sentiment": "negative",
                        "mechanism_tags": ["balance_regression"],
                        "relevance": 0.9,
                    }
                ]
            }
        ]
    )
    collector = UpdateCollectorAgent(
        steam=_SingleLanguageSteam(raw),
        use_llm=True,
        client=SimpleNamespace(messages=messages),
        budget=ClaudeBudget(max_requests=1),
    )
    options = UpdateCollectionOptions(
        use_fixture=False,
        steam_app_id=578080,
        period_start=brief.cutoff_at - timedelta(days=7),
        period_end=brief.cutoff_at,
    )
    with TemporaryDirectory() as directory:
        log_path = Path(directory) / "live-safety.jsonl"
        result = UpdateReviewOrchestrator(collector=collector).run(
            brief, options, log_path=log_path
        )
        serialized = json.dumps(
            {
                "feedback": result.feedback.model_dump(mode="json"),
                "evidence": result.evidence.model_dump(mode="json"),
                "impact": result.impact.model_dump(mode="json"),
                "validated": result.validated.model_dump(mode="json"),
                "brief": result.brief.model_dump(mode="json"),
                "events": [item.model_dump(mode="json") for item in result.events],
            },
            ensure_ascii=False,
        ) + log_path.read_text(encoding="utf-8")

    persisted = result.feedback.evidence
    return bool(
        len(persisted) == 1
        and persisted[0].source_url == "https://steamcommunity.com"
        and persisted[0].source_id == _live_source_id(raw.source, raw.source_id)
        and all(
            value not in serialized
            for value in (raw.source_url, raw.source_id, raw.text)
        )
    )


def _llm_fallback_budget_safe() -> bool:
    """A structured-output refusal must stay inside the shared safe budget."""

    messages = _RefusalMessages()
    orchestrator = UpdateReviewOrchestrator(
        use_llm=True,
        llm_client=SimpleNamespace(messages=messages),
    )
    result = orchestrator.run(load_dragunov_brief("update-success-llm-fallback"))
    budget = orchestrator.budget
    return bool(
        budget
        and result.fallback_used
        and not result.analysis_incomplete
        and result.brief.decision is UpdateDecision.TEST
        and result.llm_requested
        and result.llm_provider == "claude"
        and budget.max_requests <= 3
        and budget.max_usd <= 5
        and 1 <= budget.requests <= budget.max_requests
        and len(messages.calls) == budget.requests
        and any(item.state is ExecutionState.RETRYING for item in result.events)
    )


def verify() -> UpdateSuccessReport:
    """Run the deterministic fixture plus bounded safety backtests."""

    started = monotonic()
    result = UpdateReviewOrchestrator().run(
        load_dragunov_brief("update-success-gate")
    )
    repeat = UpdateReviewOrchestrator().run(
        load_dragunov_brief("update-success-gate-repeat")
    )
    runtime_seconds = monotonic() - started

    fixture_evidence = [
        *result.feedback.evidence,
        *result.evidence.evidence,
        *result.brief.evidence,
    ]
    evidence_ids = {item.evidence_id for item in result.brief.evidence}
    complete_order = [
        item.agent
        for item in result.events
        if item.node == "agent" and item.state is ExecutionState.COMPLETE
    ]
    actual_after_count = sum(
        _period_is(item, EvidencePeriod.AFTER) for item in result.brief.evidence
    )
    synthetic_only = bool(fixture_evidence) and all(
        item.synthetic for item in fixture_evidence
    )
    comparable_reference_only = bool(fixture_evidence) and all(
        _period_is(item, EvidencePeriod.COMPARABLE_REFERENCE)
        for item in fixture_evidence
    )
    no_after_leakage = not any(
        _period_is(item, EvidencePeriod.AFTER) for item in fixture_evidence
    )
    reproducible_core = core_outcome(result) == core_outcome(repeat)
    semantic_links_valid = _semantic_links_valid(result)
    event_sequence_valid = complete_order[:4] == list(AGENT_ORDER)
    partial_hold_safe = _partial_failure_holds()
    source_metadata_safe = _source_metadata_safe()
    llm_fallback_budget_safe = _llm_fallback_budget_safe()
    passed = all(
        (
            result.brief.decision is UpdateDecision.TEST,
            len(result.brief.evidence) == 75,
            len(evidence_ids) == 75,
            synthetic_only,
            comparable_reference_only,
            actual_after_count == 0,
            no_after_leakage,
            reproducible_core,
            semantic_links_valid,
            event_sequence_valid,
            partial_hold_safe,
            llm_fallback_budget_safe,
            source_metadata_safe,
            len(result.brief.input_snapshot_hash) == 64,
            runtime_seconds < 300,
        )
    )
    return UpdateSuccessReport(
        decision=result.brief.decision,
        evidence_count=len(result.brief.evidence),
        synthetic_only=synthetic_only,
        comparable_reference_only=comparable_reference_only,
        actual_after_count=actual_after_count,
        no_after_leakage=no_after_leakage,
        reproducible_core=reproducible_core,
        semantic_links_valid=semantic_links_valid,
        event_sequence_valid=event_sequence_valid,
        partial_hold_safe=partial_hold_safe,
        llm_fallback_budget_safe=llm_fallback_budget_safe,
        source_metadata_safe=source_metadata_safe,
        input_snapshot_hash=result.brief.input_snapshot_hash,
        runtime_seconds=runtime_seconds,
        passed=passed,
    )


if __name__ == "__main__":
    print(verify().model_dump_json(indent=2))
