from time import monotonic

import pytest

from agents.collector import CollectionOptions, CollectorAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import ClaudeBudget, StructuredModelError
from connectors import ConnectorError
from contracts import (
    ArtifactStatus,
    Decision,
    ErrorCode,
    InputMode,
    PipelineError,
    Producer,
)
from evaluation.backtest import evaluate_black_market
from evaluation.fixtures import load_demo_event
from execution import AGENT_ORDER, ExecutionState
from orchestrator import EventPreflightOrchestrator, PipelineStopped


def core_outcome(result):
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


def test_fixed_data_end_to_end_passes_in_under_five_minutes(event):
    started = monotonic()
    result = EventPreflightOrchestrator().run(event, CollectionOptions())
    elapsed = monotonic() - started
    score = evaluate_black_market(result.brief)

    assert elapsed < 300
    assert score.passed
    assert score.detected_count >= 3
    assert score.evidence_link_rate == 1
    assert score.sampled_claim_support_rate >= 0.9
    assert all(item.observed_at < event.cutoff_at for item in result.brief.evidence)


def test_claude_provider_runs_all_three_narrative_agents(monkeypatch, event):
    import agents.audit_strategy.agent as audit_module
    import agents.event_redteam.agent as redteam_module
    import agents.evidence_rag.agent as evidence_module

    calls = []

    def fake_claude(**kwargs):
        calls.append(kwargs["output_type"].__name__)
        output_type = kwargs["output_type"]
        if output_type is evidence_module.EvidenceNarrative:
            return output_type(issues=[], personas=[], exploratory_insights=[])
        if output_type is redteam_module.RedteamNarrative:
            return output_type(risks=[])
        return output_type(decision_narrative="Claude 설명", revisions=[])

    monkeypatch.setattr(evidence_module, "parse_claude_structured", fake_claude)
    monkeypatch.setattr(redteam_module, "parse_claude_structured", fake_claude)
    monkeypatch.setattr(audit_module, "parse_claude_structured", fake_claude)

    result = EventPreflightOrchestrator(
        use_llm=True, llm_provider="claude", llm_client=object()
    ).run(event, CollectionOptions())

    assert calls == ["EvidenceNarrative", "RedteamNarrative", "AuditNarrative"]
    assert result.llm_provider == "claude"
    assert result.llm_requested is True
    assert result.fallback_used is False
    assert result.brief.decision == Decision.REVISE


def test_fixture_llm_refusal_retries_once_then_uses_deterministic_fallback(event):
    class RefusingRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, _bundle, on_event=None):
            self.calls += 1
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

    rag = RefusingRag()
    result = EventPreflightOrchestrator(evidence_rag=rag).run(event, CollectionOptions())
    assert rag.calls == 2
    assert result.brief.decision == Decision.REVISE
    assert result.fallback_used is True
    states = [item.state for item in result.events if item.agent == "evidence_rag_personas"]
    assert ExecutionState.RETRYING in states
    assert ExecutionState.FAILED in states
    assert ExecutionState.COMPLETE in states


def test_complete_corpus_budget_exhaustion_uses_non_hold_deterministic_result(
    event, feedback
):
    complete_corpus = feedback.model_copy(
        update={
            "input_refs": [event.ref],
            "input_mode": InputMode.CORPUS,
            "status": ArtifactStatus.COMPLETE,
            "errors": [],
        }
    )

    class CompleteCorpusCollector:
        def run(self, _event, _options, on_event=None):
            return complete_corpus

    result = EventPreflightOrchestrator(
        collector=CompleteCorpusCollector(),
        use_llm=True,
        llm_provider="claude",
        llm_client=object(),
        budget=ClaudeBudget(max_requests=0, max_usd=0),
    ).run(event, CollectionOptions())

    assert result.fallback_used is True
    assert result.analysis_incomplete is False
    assert result.brief.decision is Decision.REVISE


def test_contract_violation_stops_without_retry_or_fallback(event):
    class BrokenRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, bundle, on_event=None):
            self.calls += 1
            return self.run_deterministic(bundle).model_copy(update={"producer": Producer.COLLECTOR})

    broken = BrokenRag()
    events = []
    with pytest.raises(PipelineStopped, match="SCHEMA_INVALID"):
        EventPreflightOrchestrator(evidence_rag=broken).run(
            event,
            CollectionOptions(),
            on_event=events.append,
        )
    assert broken.calls == 1
    assert any(
        item.agent == "evidence_rag_personas" and item.state == ExecutionState.FAILED
        for item in events
    )


def test_live_llm_failure_returns_hold_without_loading_fixture(event):
    class RefusingRag(EvidenceRagAgent):
        def run(self, _bundle, on_event=None):
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

    class FakeSteam:
        def fetch_reviews(self, _app_id, language, cutoff_at, limit=100):
            return []

    result = EventPreflightOrchestrator(
        collector=CollectorAgent(steam=FakeSteam()),
        evidence_rag=RefusingRag(),
    ).run(event, CollectionOptions(use_fixture=False, steam_app_id=578080))
    assert result.feedback.input_mode == InputMode.LIVE
    assert result.brief.decision == Decision.HOLD
    assert result.analysis_incomplete is True
    assert result.brief.evidence == []


def test_partial_corpus_runs_end_to_end_as_incomplete_hold(event, feedback):
    partial = feedback.model_copy(
        update={
            "status": ArtifactStatus.PARTIAL,
            "input_mode": InputMode.CORPUS,
            "errors": [
                PipelineError(
                    code=ErrorCode.INSUFFICIENT_EVIDENCE,
                    message="한국어 관련 근거를 더 확보해야 합니다.",
                )
            ],
        }
    )

    class PartialCorpusCollector:
        def run(self, _event, _options, on_event=None):
            return partial

    result = EventPreflightOrchestrator(collector=PartialCorpusCollector()).run(
        event, CollectionOptions()
    )

    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.analysis_incomplete is True
    assert result.brief.decision is Decision.HOLD


def test_fixture_run_still_succeeds_after_live_collection_failure(event):
    class FailingSteam:
        def fetch_reviews(self, *_args, **_kwargs):
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "network down")

    orchestrator = EventPreflightOrchestrator(collector=CollectorAgent(steam=FailingSteam()))
    with pytest.raises(PipelineStopped):
        orchestrator.run(
            event,
            CollectionOptions(use_fixture=False, steam_app_id=578080),
        )
    recovered = orchestrator.run(event, CollectionOptions(use_fixture=True))
    assert recovered.brief.decision == Decision.REVISE
    assert all(item.synthetic for item in recovered.feedback.evidence)


def test_same_fixture_produces_same_core_outcome_across_run_ids():
    first_event = load_demo_event("first-run")
    second_event = load_demo_event("second-run")
    first = EventPreflightOrchestrator().run(first_event, CollectionOptions())
    second = EventPreflightOrchestrator().run(second_event, CollectionOptions())
    assert core_outcome(first) == core_outcome(second)


def test_input_snapshot_hash_changes_when_normalized_input_changes(event):
    first = EventPreflightOrchestrator().run(event, CollectionOptions())
    changed = event.model_copy(update={"goal": f"{event.goal} 변경"})
    second = EventPreflightOrchestrator().run(changed, CollectionOptions())
    assert first.brief.input_snapshot_hash != second.brief.input_snapshot_hash


def test_sample_counts_change_snapshot_hash_and_can_change_decision(event):
    baseline = EventPreflightOrchestrator().run(event, CollectionOptions())
    changed_samples = [
        sample.model_copy(update={"general_count": 0, "mechanism_count": 0})
        if index < 3
        else sample
        for index, sample in enumerate(baseline.feedback.samples)
    ]

    class ChangedSampleCollector:
        def run(self, _event, _options, on_event=None):
            return baseline.feedback.model_copy(update={"samples": changed_samples})

    changed = EventPreflightOrchestrator(collector=ChangedSampleCollector()).run(
        event, CollectionOptions()
    )

    assert changed.feedback.evidence == baseline.feedback.evidence
    assert changed.brief.input_snapshot_hash != baseline.brief.input_snapshot_hash
    assert baseline.brief.decision == Decision.REVISE
    assert changed.brief.decision == Decision.HOLD


def test_success_events_include_internal_nodes_in_pipeline_order(event):
    result = EventPreflightOrchestrator().run(event, CollectionOptions())
    assert [item.agent for item in result.events[:4]] == list(AGENT_ORDER)
    assert all(item.state == ExecutionState.WAITING for item in result.events[:4])
    completed = [item.agent for item in result.events if item.state == ExecutionState.COMPLETE]
    assert completed[:4] == list(AGENT_ORDER)
    required_nodes = {
        "collection": ["source_selected", "cutoff_checked", "anonymized", "samples_counted", "bundle_ready"],
        "evidence_rag_personas": ["deduplicated", "issues_grouped", "language_gate_checked", "personas_built", "pack_ready"],
        "event_redteam": ["event_reviewed", "failure_paths_built", "impact_linked", "risks_graded", "assessment_ready"],
        "audit_strategy": ["evidence_checked", "risks_validated", "sample_gate_applied", "decision_fixed", "revisions_built"],
    }
    for agent, nodes in required_nodes.items():
        observed = [item.node for item in result.events if item.agent == agent]
        positions = [observed.index(node) for node in nodes]
        assert positions == sorted(positions)


def test_failure_event_never_starts_downstream_agents(event):
    class BrokenRag(EvidenceRagAgent):
        def run(self, bundle, on_event=None):
            result = self.run_deterministic(bundle)
            return result.model_copy(update={"producer": Producer.COLLECTOR})

    events = []
    with pytest.raises(PipelineStopped):
        EventPreflightOrchestrator(evidence_rag=BrokenRag()).run(
            event,
            CollectionOptions(),
            on_event=events.append,
        )
    assert not any(
        item.agent in {"event_redteam", "audit_strategy"} and item.state == ExecutionState.RUNNING
        for item in events
    )


def test_unexpected_stage_exception_records_safe_failure_and_stops_downstream(event):
    class BrokenRag(EvidenceRagAgent):
        def run(self, _bundle, on_event=None):
            raise TypeError("username alice must not escape")

    events = []
    with pytest.raises(PipelineStopped) as error:
        EventPreflightOrchestrator(evidence_rag=BrokenRag()).run(
            event,
            CollectionOptions(),
            on_event=events.append,
        )

    assert isinstance(error.value.__cause__, TypeError)
    failed = next(
        item
        for item in events
        if item.agent == "evidence_rag_personas" and item.state == ExecutionState.FAILED
    )
    assert failed.metrics == {"error_type": "TypeError"}
    assert "alice" not in failed.message
    assert not any(
        item.agent in {"event_redteam", "audit_strategy"}
        and item.state == ExecutionState.RUNNING
        for item in events
    )


def test_unexpected_deterministic_exception_records_safe_failure_and_stops_downstream(event):
    class BrokenFallbackRag(EvidenceRagAgent):
        def run(self, _bundle, on_event=None):
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

        def run_deterministic(self, _bundle, on_event=None):
            raise RuntimeError("raw internal detail must not escape")

    events = []
    with pytest.raises(PipelineStopped) as error:
        EventPreflightOrchestrator(evidence_rag=BrokenFallbackRag()).run(
            event,
            CollectionOptions(),
            on_event=events.append,
        )

    assert isinstance(error.value.__cause__, RuntimeError)
    failed = [
        item
        for item in events
        if item.agent == "evidence_rag_personas" and item.state == ExecutionState.FAILED
    ][-1]
    assert failed.metrics == {"error_type": "RuntimeError"}
    assert "raw internal detail" not in failed.message
    assert not any(
        item.agent in {"event_redteam", "audit_strategy"}
        and item.state == ExecutionState.RUNNING
        for item in events
    )
