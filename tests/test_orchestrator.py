from time import monotonic

import pytest

from agents.collector import CollectionOptions
from agents.evidence_rag import EvidenceRagAgent
from contracts import Producer
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


def test_schema_violation_retries_once(event):
    class FlakyRag:
        def __init__(self):
            self.calls = 0
            self.real = EvidenceRagAgent()

        def run(self, bundle):
            self.calls += 1
            result = self.real.run(bundle)
            return result.model_copy(update={"producer": Producer.COLLECTOR}) if self.calls == 1 else result

    flaky = FlakyRag()
    EventPreflightOrchestrator(evidence_rag=flaky).run(event, CollectionOptions())
    assert flaky.calls == 2


def test_second_schema_violation_stops_pipeline(event):
    class BrokenRag:
        def __init__(self):
            self.calls = 0

        def run(self, bundle):
            self.calls += 1
            return EvidenceRagAgent().run(bundle).model_copy(update={"producer": Producer.COLLECTOR})

    broken = BrokenRag()
    with pytest.raises(PipelineStopped, match="SCHEMA_INVALID"):
        EventPreflightOrchestrator(evidence_rag=broken).run(event, CollectionOptions())
    assert broken.calls == 2
