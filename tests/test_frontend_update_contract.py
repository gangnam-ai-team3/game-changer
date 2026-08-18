import json
import os
from pathlib import Path
import subprocess


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


def test_both_result_modes_expose_complete_decision_brief():
    event_source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    update_source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    for source in (event_source, update_source):
        assert "decision-logic" in source
        assert "이용자 유형별 예상 반응" in source
        assert "언어권별 예상" in source
        assert "판단을 좌우한 위험" in source
        assert "지금 해야 할 일" in source


def test_event_live_source_can_select_steam_x_or_both():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert "checked={useSteam}" in source
    assert "checked={useX}" in source
    assert 'use_x: sourceMode === "live" ? useX : false' in source
    assert 'sourceMode === "live" && useSteam ? Number(steamAppId) : null' in source
    assert "Steam만, X만, 또는 두 자료를 함께 선택할 수 있습니다" in source


def test_user_facing_frontend_copy_does_not_use_middle_dots():
    for path in (
        ROOT / "page.tsx",
        ROOT / "components" / "UpdateReview.tsx",
        ROOT / "components" / "AgentPipeline.tsx",
    ):
        assert "·" not in path.read_text(encoding="utf-8")


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


def _live_period_payload_in_timezone(timezone: str) -> dict[str, str | None]:
    script = """
import { utcWallClockToIso } from "./frontend/app/components/utcWallClock.ts";

process.stdout.write(JSON.stringify({
  period_start: utcWallClockToIso("2026-08-06T00:00"),
  period_end: utcWallClockToIso("2026-08-13T00:00"),
  invalid_period: utcWallClockToIso("2026-02-30T00:00"),
}));
"""
    completed = subprocess.run(
        [
            "node",
            "--no-warnings",
            "--experimental-strip-types",
            "--input-type=module",
            "--eval",
            script,
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        env={**os.environ, "TZ": timezone},
        text=True,
    )
    return json.loads(completed.stdout)


def test_live_datetime_payload_keeps_utc_wall_clock_in_non_utc_timezones():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "period_start: livePeriodStart" in source
    assert "period_end: livePeriodEnd" in source
    assert "new Date(periodStart).toISOString()" not in source
    assert "new Date(periodEnd).toISOString()" not in source

    expected = {
        "period_start": "2026-08-06T00:00:00Z",
        "period_end": "2026-08-13T00:00:00Z",
        "invalid_period": None,
    }
    assert _live_period_payload_in_timezone("America/New_York") == expected
    assert _live_period_payload_in_timezone("Asia/Seoul") == expected
