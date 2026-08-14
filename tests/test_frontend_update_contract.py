from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "frontend" / "app"


def test_home_exposes_accessible_review_mode_switch():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert 'aria-pressed={reviewMode === "event"}' in source
    assert 'aria-pressed={reviewMode === "update"}' in source
    assert "이벤트 점검" in source
    assert "업데이트 점검" in source


def test_existing_event_stream_and_pipeline_mode_are_preserved():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert 'fetch(`${API_URL}/api/runs/stream`' in source
    assert 'mode="event"' in source
    assert "file.name" not in source


def test_update_screen_has_prelaunch_copy_and_four_decision_labels():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "출시 전 예상이며 실제 이용자 반응이 아닙니다" in source
    assert 'Go: "출시 가능"' in source
    assert 'Revise: "일부 수정 후 출시"' in source
    assert 'Test: "테스트 후 출시"' in source
    assert 'Hold: "판정 보류"' in source
    assert 'fetch(`${API_URL}/api/update-runs/stream`' in source


def test_actual_after_section_is_conditionally_rendered():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert 'item.period === "after"' in source
    assert "업데이트 후 실제 반응" in source
    assert "출시 후 검증할 지표" in source


def test_language_ratios_are_hidden_when_sample_conclusion_is_hidden():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "language.conclusion ?" in source
    assert "language.hidden_reason" in source
    assert "language.sentiment_counts" in source


def test_official_context_is_visually_separate_from_synthetic_evidence():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "공식으로 확인된 변경 맥락" in source
    assert "official_context" in source
    assert "synthetic" in source


def test_shared_pipeline_has_update_contract_names_and_owners():
    source = (ROOT / "components" / "AgentPipeline.tsx").read_text(encoding="utf-8")

    for contract in (
        "UpdateFeedbackBundle",
        "UpdateEvidencePack",
        "UpdateImpactAssessment",
        "UpdateValidatedDecision",
    ):
        assert contract in source
    for owner in ("정현예", "유주심", "정아현", "승진배"):
        assert owner in source


def test_update_client_never_accepts_or_serializes_provider_credentials():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "ANTHROPIC_API_KEY" not in source
    assert "api_key" not in source
    assert "authorization" not in source.lower()
    assert "file.name" not in source
