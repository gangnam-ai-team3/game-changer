import evaluation.verify_success as success_gate
from orchestrator import EventPreflightOrchestrator


def test_explicit_success_gate_passes():
    report = success_gate.verify()
    assert report.passed
    assert report.backtest.detected_count >= 3
    assert report.backtest.evidence_link_rate == 1
    assert report.backtest.sampled_claim_count == 20
    assert report.backtest.sampled_claim_support_rate >= 0.9
    assert report.backtest.persona_coverage_ok
    assert report.runtime_seconds < 300
    assert report.insufficient_languages_hidden >= 3
    assert report.insufficient_languages_decision.value == "Hold"
    assert report.cutoff_leak_blocked
    assert report.event_goal_aligned
    assert report.reproducible_core
    assert report.semantic_links_valid
    assert report.event_sequence_valid
    assert len(report.input_snapshot_hash) == 64


def test_success_gate_rejects_pending_input_snapshot_hash(monkeypatch):
    class PendingHashOrchestrator(EventPreflightOrchestrator):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            result.brief = result.brief.model_copy(update={"input_snapshot_hash": "pending"})
            return result

    monkeypatch.setattr(success_gate, "EventPreflightOrchestrator", PendingHashOrchestrator)

    report = success_gate.verify()

    assert report.input_snapshot_hash == "pending"
    assert report.reproducible_core
    assert not report.passed
