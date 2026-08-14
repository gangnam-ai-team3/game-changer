import pytest

from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import EvidencePeriod, Sentiment, UpdateDecision, UpdateType
from update_review.fixtures import load_dragunov_brief, load_update_feedback_fixture
from update_review.orchestrator import UpdateReviewOrchestrator


EXPECTED_AGENTS = [
    "collection",
    "evidence_rag_personas",
    "event_redteam",
    "audit_strategy",
]


def test_dragunov_fixture_is_synthetic_comparable_reference():
    brief = load_dragunov_brief("dragunov-fixture")
    bundle = load_update_feedback_fixture(brief)
    assert brief.update_type is UpdateType.WEAPON_BALANCE
    assert brief.details.damage == "기본 58·최대 73 확률 → 60 고정"
    assert "공식 변경 맥락" in brief.official_context
    assert brief.official_context_url == "https://pubg.com/en/news/6616"
    assert len(bundle.evidence) == 75
    assert len(bundle.samples) == 5
    assert all(item.synthetic for item in bundle.evidence)
    assert {item.period for item in bundle.evidence} == {
        EvidencePeriod.COMPARABLE_REFERENCE
    }
    assert {item.sentiment for item in bundle.evidence} == set(Sentiment)
    assert all(item.source_url.startswith("https://") for item in bundle.evidence)
    assert all(item.observed_at < brief.cutoff_at for item in bundle.evidence)


def test_fixture_collector_emits_five_named_nodes():
    brief = load_dragunov_brief("dragunov-nodes")
    nodes = []
    bundle = UpdateCollectorAgent().run(
        brief,
        UpdateCollectionOptions(),
        on_event=lambda node, message, metrics: nodes.append((node, message, metrics)),
    )
    assert bundle.input_refs == [brief.ref]
    assert [node for node, _, _ in nodes] == [
        "source_selected",
        "period_checked",
        "anonymized",
        "samples_counted",
        "bundle_ready",
    ]
    assert all(message for _, message, _ in nodes)


def test_dragunov_pipeline_is_reproducible_and_requires_test():
    first = UpdateReviewOrchestrator().run(load_dragunov_brief("stable-run"))
    second = UpdateReviewOrchestrator().run(load_dragunov_brief("stable-run"))
    assert first.brief == second.brief
    assert first.brief.decision is UpdateDecision.TEST
    assert first.feedback.ref in first.evidence.input_refs
    assert first.evidence.ref in first.impact.input_refs
    assert first.impact.ref in first.validated.input_refs
    assert {item.sentiment.value for item in first.evidence.positive_signals} == {"positive"}
    assert {item.sentiment.value for item in first.evidence.negative_signals} == {"negative"}
    assert all(metric.addresses_risk_ids for metric in first.brief.validation_metrics)
    assert not any(item.period.value == "after" for item in first.brief.evidence)


def test_pipeline_exposes_all_agents_and_internal_node_results():
    result = UpdateReviewOrchestrator().run(load_dragunov_brief("event-run"))
    completed_agents = [
        item.agent
        for item in result.events
        if item.node == "agent" and item.state.value == "complete"
    ]
    assert completed_agents == EXPECTED_AGENTS
    nodes = {item.node for item in result.events}
    assert {
        "source_selected",
        "signals_grouped",
        "personas_linked",
        "change_reviewed",
        "failure_paths_built",
        "metrics_linked",
        "risks_validated",
        "decision_fixed",
        "recommendations_built",
    } <= nodes
    assert all(item.message for item in result.events)


def test_update_contract_violation_stops_the_pipeline():
    class WrongCollector:
        def run(self, brief, options, on_event=None):
            return load_update_feedback_fixture(brief).model_copy(
                update={"run_id": "changed"}
            )

    with pytest.raises(Exception, match="run_id changed"):
        UpdateReviewOrchestrator(collector=WrongCollector()).run(
            load_dragunov_brief("expected")
        )
