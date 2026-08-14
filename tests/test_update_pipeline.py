import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from connectors import RawFeedback
from contracts import Language, SourceType
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import (
    EvidencePeriod,
    Sentiment,
    UpdateDecision,
    UpdateEvidencePack,
    UpdateType,
)
from update_review.fixtures import load_dragunov_brief, load_update_feedback_fixture
from update_review.orchestrator import UpdateReviewOrchestrator, _input_snapshot_hash
from update_review.redteam import UpdateRedteamAgent


EXPECTED_AGENTS = [
    "collection",
    "evidence_rag_personas",
    "event_redteam",
    "audit_strategy",
]


class FakeClaudeMessages:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=payload)])


class FakeClaude:
    def __init__(self, payloads):
        self.messages = FakeClaudeMessages(payloads)


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


def test_decision_affecting_relevance_changes_snapshot_hash():
    brief = load_dragunov_brief("hash-relevance")
    bundle = load_update_feedback_fixture(brief)
    changed = bundle.model_copy(
        update={
            "evidence": [
                item.model_copy(update={"relevance": 0.1})
                if item.evidence_id == bundle.evidence[0].evidence_id
                else item
                for item in bundle.evidence
            ]
        }
    )
    assert _input_snapshot_hash(brief, bundle) != _input_snapshot_hash(brief, changed)


def test_reversed_evidence_has_identical_result_and_hash():
    brief = load_dragunov_brief("reversed-evidence")
    bundle = load_update_feedback_fixture(brief)

    class ReversedCollector:
        def run(self, brief, options, on_event=None):
            return load_update_feedback_fixture(brief).model_copy(
                update={"evidence": list(reversed(bundle.evidence))}
            )

    first = UpdateReviewOrchestrator().run(brief)
    second = UpdateReviewOrchestrator(collector=ReversedCollector()).run(brief)
    assert first.brief == second.brief
    assert first.brief.input_snapshot_hash == second.brief.input_snapshot_hash


def test_mixed_and_negative_signals_share_one_risk_and_metric():
    brief = load_dragunov_brief("coalesced-risk")
    bundle = load_update_feedback_fixture(brief)
    negative = next(item for item in bundle.evidence if item.sentiment is Sentiment.NEGATIVE)
    mixed = next(item for item in bundle.evidence if item.sentiment is Sentiment.MIXED)
    pack = UpdateEvidencePack(
        run_id=brief.run_id,
        status=bundle.status,
        producer="evidence_rag",
        input_refs=[bundle.ref],
        errors=[],
        positive_signals=[],
        negative_signals=[
            {
                "signal_id": "negative-balance_regression",
                "title": "실제 성능 역전 가능성",
                "summary": "부정 반응",
                "sentiment": "negative",
                "evidence_ids": [negative.evidence_id],
                "confidence": 0.8,
            }
        ],
        split_conditions=[
            {
                "signal_id": "mixed-balance_regression",
                "title": "실제 성능 역전 가능성",
                "summary": "혼합 반응",
                "sentiment": "mixed",
                "evidence_ids": [mixed.evidence_id],
                "confidence": 0.6,
            }
        ],
        persona_impacts=[],
        language_insights=[],
        evidence=[negative, mixed],
    )
    result = UpdateRedteamAgent().run_deterministic(brief, pack)
    assert [risk.risk_id for risk in result.risks] == ["risk-balance_regression"]
    assert [metric.metric_id for metric in result.validation_metrics] == [
        "metric-balance_regression"
    ]
    assert result.risks[0].evidence_ids == sorted(
        [negative.evidence_id, mixed.evidence_id]
    )


def test_claude_changes_only_korean_narrative_not_core_decision():
    baseline = UpdateReviewOrchestrator().run(load_dragunov_brief("claude-run"))
    risk = baseline.impact.risks[0]
    metric = baseline.impact.validation_metrics[0]
    positive = baseline.evidence.positive_signals[0]
    fake = FakeClaude(
        [
            {
                "signals": [
                    {
                        "signal_id": positive.signal_id,
                        "title": "예측 가능성 개선 예상",
                        "summary": "고정 피해로 결과 예측 가능성이 높아질 가능성이 있음.",
                        "evidence_ids": positive.evidence_ids,
                    }
                ]
            },
            {
                "risks": [
                    {
                        "risk_id": risk.risk_id,
                        "title": "전투 성능 재확인 필요",
                        "failure_path": "실제 특성 조합에서 메타가 쏠릴 가능성이 있음.",
                        "revision_question": "테스트 서버 지표를 확인할 수 있는가?",
                        "evidence_ids": risk.evidence_ids,
                        "validation_metric_ids": [metric.metric_id],
                    }
                ]
            },
            {
                "executive_summary": "결과 예측 가능성은 개선될 수 있으나 전투 지표는 테스트로 확인 필요.",
                "recommendations": [
                    {
                        "risk_id": risk.risk_id,
                        "title": "테스트 서버 확인",
                        "action": "사용률·승률·평균 피해를 확인한다.",
                        "validation_metric_ids": [metric.metric_id],
                    }
                ],
            },
        ]
    )
    result = UpdateReviewOrchestrator(use_llm=True, llm_client=fake).run(
        load_dragunov_brief("claude-run")
    )
    assert result.brief.decision == baseline.brief.decision == UpdateDecision.TEST
    assert [item.risk_id for item in result.brief.top_risks] == [
        item.risk_id for item in baseline.brief.top_risks
    ]
    assert [item.evidence_ids for item in result.brief.top_risks] == [
        item.evidence_ids for item in baseline.brief.top_risks
    ]
    assert result.llm_provider == "claude"
    assert result.llm_requested is True
    assert result.fallback_used is False
    assert [call["model"] for call in fake.messages.calls] == [
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-haiku-4-5",
    ]


def test_invalid_claude_reference_retries_then_uses_fixture_safe_path():
    invalid = {
        "signals": [
            {
                "signal_id": "unknown",
                "title": "한국어 제목",
                "summary": "한국어 설명을 제공함.",
                "evidence_ids": ["missing"],
            }
        ]
    }
    fake = FakeClaude([invalid, invalid])
    result = UpdateReviewOrchestrator(use_llm=True, llm_client=fake).run(
        load_dragunov_brief("fallback-run")
    )
    assert result.brief.decision is UpdateDecision.TEST
    assert result.fallback_used is True
    assert result.analysis_incomplete is False
    assert len(fake.messages.calls) == 2
    assert any(item.state.value == "retrying" for item in result.events)


def test_claude_request_cap_falls_back_without_an_extra_call():
    invalid = {
        "signals": [
            {
                "signal_id": "unknown",
                "title": "한국어 제목",
                "summary": "한국어 설명을 제공함.",
                "evidence_ids": ["missing"],
            }
        ]
    }
    fake = FakeClaude([invalid])
    orchestrator = UpdateReviewOrchestrator(use_llm=True, llm_client=fake)
    assert orchestrator.budget is not None
    orchestrator.budget.max_requests = 1
    result = orchestrator.run(load_dragunov_brief("budget-fallback-run"))
    assert result.fallback_used is True
    assert len(fake.messages.calls) == 1


def test_fixture_without_claude_key_uses_deterministic_path(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = UpdateReviewOrchestrator(use_llm=True).run(
        load_dragunov_brief("no-key-run")
    )
    assert result.brief.decision is UpdateDecision.TEST
    assert result.fallback_used is True
    assert result.analysis_incomplete is False


def test_live_classifier_returns_only_sanitized_structured_evidence():
    raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="anonymous-source-001",
        language=Language.KOREAN,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text="원문에는 사용자가 작성한 상세 반응이 있다.",
    )
    fake = FakeClaude(
        [
            {
                "items": [
                    {
                        "source_id": raw.source_id,
                        "sentiment": "negative",
                        "summary": "고정 피해의 실제 성능은 테스트로 확인 필요.",
                        "mechanism_tags": ["balance_regression"],
                        "relevance": 0.9,
                    }
                ]
            }
        ]
    )
    output = UpdateCollectorAgent(use_llm=True, client=fake).classify_raw(
        [raw], load_dragunov_brief("live-classify")
    )
    assert output[0].source_id == raw.source_id
    assert output[0].summary != raw.text
    assert "text" not in output[0].model_dump()
    assert raw.text not in json.dumps(output[0].model_dump(mode="json"), ensure_ascii=False)
