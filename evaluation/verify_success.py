from __future__ import annotations

from time import monotonic

from pydantic import BaseModel, ConfigDict, ValidationError

from agents.audit_strategy import AuditStrategyAgent
from agents.collector import CollectionOptions
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from contracts import Decision, FeedbackBundle, LanguageSample
from evaluation.backtest import BacktestResult, evaluate_black_market
from evaluation.fixtures import load_demo_event, load_feedback_fixture
from orchestrator import EventPreflightOrchestrator, PipelineResult


class SuccessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    revision_count: int
    runtime_seconds: float
    backtest: BacktestResult
    insufficient_languages_hidden: int
    insufficient_languages_decision: Decision
    cutoff_leak_blocked: bool
    event_goal_aligned: bool
    reproducible_core: bool
    semantic_links_valid: bool
    input_snapshot_hash: str
    passed: bool


def core_outcome(result: PipelineResult) -> tuple:
    return (
        result.brief.decision,
        tuple(
            (risk.category, risk.severity, tuple(sorted(risk.evidence_ids)))
            for risk in result.brief.top_risks
        ),
        tuple(risk.risk_id for risk in result.validated.validated_risks),
        tuple(risk.risk_id for risk in result.validated.rejected_risks),
        tuple(
            (tuple(action.addresses_risk_ids), action.priority)
            for action in result.brief.revision_plan
        ),
        result.brief.schema_version,
        result.brief.policy_version,
        result.brief.input_snapshot_hash,
    )


def verify() -> SuccessReport:
    event = load_demo_event("success-gate")
    started = monotonic()
    result = EventPreflightOrchestrator().run(event, CollectionOptions())
    runtime_seconds = monotonic() - started
    backtest = evaluate_black_market(result.brief)
    repeat = EventPreflightOrchestrator().run(
        load_demo_event("success-gate-repeat"), CollectionOptions()
    )
    reproducible_core = core_outcome(result) == core_outcome(repeat)
    semantic_links_valid = (
        backtest.evidence_link_rate == 1 and backtest.sampled_claim_support_rate >= 0.9
    )

    feedback = load_feedback_fixture(event).model_copy(update={"input_refs": [event.ref]})
    insufficient_samples = [
        LanguageSample(
            language=sample.language,
            general_count=0 if index < 3 else sample.general_count,
            mechanism_count=0 if index < 3 else sample.mechanism_count,
        )
        for index, sample in enumerate(feedback.samples)
    ]
    insufficient_feedback = feedback.model_copy(update={"samples": insufficient_samples})
    insufficient_pack = EvidenceRagAgent().run(insufficient_feedback)
    insufficient_risks = EventRedteamAgent().run(event, insufficient_pack)
    insufficient_decision = AuditStrategyAgent().run(
        insufficient_feedback, insufficient_pack, insufficient_risks
    )
    hidden_count = sum(insight.conclusion is None for insight in insufficient_pack.language_insights)

    leaked_payload = feedback.model_dump()
    leaked_payload["evidence"][0]["observed_at"] = feedback.cutoff_at
    try:
        FeedbackBundle.model_validate(leaked_payload)
        cutoff_leak_blocked = False
    except ValidationError:
        cutoff_leak_blocked = True

    goal_terms = ("Progressive", "수집", "유료 전환", "비용", "진행 경로", "명확")
    event_goal_aligned = all(term in event.goal for term in goal_terms)
    passed = all(
        (
            result.brief.decision == Decision.REVISE,
            bool(result.brief.revision_plan),
            runtime_seconds < 300,
            backtest.passed,
            reproducible_core,
            semantic_links_valid,
            hidden_count >= 3,
            insufficient_decision.decision == Decision.HOLD,
            cutoff_leak_blocked,
            event_goal_aligned,
        )
    )
    return SuccessReport(
        decision=result.brief.decision,
        revision_count=len(result.brief.revision_plan),
        runtime_seconds=runtime_seconds,
        backtest=backtest,
        insufficient_languages_hidden=hidden_count,
        insufficient_languages_decision=insufficient_decision.decision,
        cutoff_leak_blocked=cutoff_leak_blocked,
        event_goal_aligned=event_goal_aligned,
        reproducible_core=reproducible_core,
        semantic_links_valid=semantic_links_valid,
        input_snapshot_hash=result.brief.input_snapshot_hash,
        passed=passed,
    )


if __name__ == "__main__":
    print(verify().model_dump_json(indent=2))
