from time import monotonic

import pytest

from agents.collector import CollectionOptions, CollectorAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import StructuredModelError
from contracts import Decision, ErrorCode, InputMode, Producer
from evaluation.backtest import evaluate_black_market
from orchestrator import EventPreflightOrchestrator, PipelineStopped


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


def test_fixture_llm_refusal_retries_once_then_uses_deterministic_fallback(event):
    class RefusingRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, _bundle):
            self.calls += 1
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

    rag = RefusingRag()
    result = EventPreflightOrchestrator(evidence_rag=rag).run(event, CollectionOptions())
    assert rag.calls == 2
    assert result.brief.decision == Decision.REVISE
    assert result.fallback_used is True


def test_contract_violation_stops_without_retry_or_fallback(event):
    class BrokenRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, bundle):
            self.calls += 1
            return self.run_deterministic(bundle).model_copy(update={"producer": Producer.COLLECTOR})

    broken = BrokenRag()
    with pytest.raises(PipelineStopped, match="SCHEMA_INVALID"):
        EventPreflightOrchestrator(evidence_rag=broken).run(event, CollectionOptions())
    assert broken.calls == 1


def test_live_llm_failure_returns_hold_without_loading_fixture(event):
    class RefusingRag(EvidenceRagAgent):
        def run(self, _bundle):
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
