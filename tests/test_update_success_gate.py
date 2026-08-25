from pathlib import Path
from types import SimpleNamespace

import evaluation.verify_update_success as update_gate

from update_review.contracts import EvidencePeriod, UpdateDecision


def test_update_success_gate_passes():
    report = update_gate.verify()

    assert report.passed
    assert report.decision is UpdateDecision.TEST
    assert report.evidence_count == 75
    assert report.synthetic_only
    assert report.comparable_reference_only
    assert report.actual_after_count == 0
    assert report.no_after_leakage
    assert report.reproducible_core
    assert report.semantic_links_valid
    assert report.event_sequence_valid
    assert report.partial_hold_safe
    assert report.llm_fallback_budget_safe
    assert report.source_metadata_safe
    assert len(report.input_snapshot_hash) == 64
    assert report.runtime_seconds < 300


def test_update_success_gate_rejects_actual_after_in_fixture(monkeypatch):
    original = update_gate.UpdateReviewOrchestrator

    class LeakingOrchestrator(original):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            if not result.brief.evidence:
                return result
            changed = result.brief.evidence[0].model_copy(
                update={"period": EvidencePeriod.AFTER}
            )
            result.brief = result.brief.model_copy(
                update={"evidence": [changed, *result.brief.evidence[1:]]}
            )
            return result

    monkeypatch.setattr(update_gate, "UpdateReviewOrchestrator", LeakingOrchestrator)

    report = update_gate.verify()

    assert report.actual_after_count == 1
    assert not report.no_after_leakage
    assert not report.comparable_reference_only
    assert not report.passed


def test_update_success_gate_treats_unvalidated_after_value_as_leakage():
    assert update_gate._period_is(
        SimpleNamespace(period="after"), EvidencePeriod.AFTER
    )


def test_update_readme_documents_safe_modes_and_local_runtime():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "### 출시 전 업데이트 점검",
        "`fixture`",
        "`live`",
        "`import`",
        "PARTIAL",
        "판정 보류(Hold)",
        "evaluation.verify_update_success",
        "backend.app.main:app",
        "npm run dev",
        "npm run build",
    ):
        assert required in readme
    assert "ANTHROPIC_API_KEY=" not in readme
    assert "X_BEARER_TOKEN=" not in readme
