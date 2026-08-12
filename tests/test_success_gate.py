from evaluation.verify_success import verify


def test_explicit_success_gate_passes():
    report = verify()
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
