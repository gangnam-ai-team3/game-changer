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


def test_event_result_uses_shared_decision_report():
    event_source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert "DecisionReport" in event_source
    assert "decision-logic" not in event_source
    assert "decisionHeading" not in event_source


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


def test_both_modes_offer_safe_corpus_and_team_agent_choice():
    event_source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    update_source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    for source in (event_source, update_source):
        assert 'type SourceMode = "fixture" | "corpus" | "live" | "import"' in source
        assert 'aria-pressed={sourceMode === "corpus"}' in source
        assert '사전 구축 Steam 코퍼스' in source
        assert '한국어와 영어 리뷰에서 파생한 비식별 요약' in source
        assert '리뷰 원문은 포함하지 않습니다' in source
        assert '코퍼스 데모 날짜 적용' in source
        assert 'onClick={applyCorpusDemoDates}' in source
        assert 'cutoff_on: dates.cutoffOn' in source
        assert 'isFutureUtcDate(form.cutoff_on)' in source
        assert '자료 기준일을 오늘(UTC)보다 뒤로' in source
        assert '2026년 8월 19일' not in source
        assert '{sourceMode === "live" && (' in source
        assert '{sourceMode === "import" && (' in source
        assert '정아현(Jelly) 위험 점검과 승진배 근거 검증 에이전트' in source
        assert '저장된 코퍼스와 코드 정책만 사용' in source

    assert 'starts_on: dates.startsOn' in event_source
    assert 'ends_on: dates.endsOn' in event_source
    assert 'planned_on: dates.startsOn' in update_source


def test_pipeline_names_corpus_and_team_agent_nodes():
    source = (ROOT / "components" / "AgentPipeline.tsx").read_text(encoding="utf-8")

    for node in (
        "corpus_selected",
        "corpus_retrieved",
        "jelly_sidecar_started",
        "jelly_output_checked",
        "jinbae_probe_started",
        "jinbae_probe_checked",
    ):
        assert f"{node}:" in source


def test_clients_validate_manual_review_dates():
    event_source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    update_source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert "form.cutoff_on > form.starts_on" in event_source
    assert "form.starts_on >= form.ends_on" in event_source
    assert "자료 기준일은 이벤트 시작일과 같거나 앞선 날짜" in event_source
    assert "이벤트 종료일은 시작일 이후" in event_source
    assert "form.cutoff_on > form.planned_on" in update_source
    assert "자료 기준일은 출시 예정일과 같거나 앞선 날짜" in update_source


def test_event_evidence_is_presented_as_derived_summary_not_quote():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "globals.css").read_text(encoding="utf-8")

    assert "이용자의 직접 인용이 아닙니다" in source
    assert "연결된 파생 요약 보기" in source
    assert "<blockquote" not in source
    assert 'className="derived-evidence"' in source
    assert ".risk-card .derived-evidence" in styles


def test_pipeline_translates_closed_team_metrics_and_focus_is_opaque():
    pipeline = (ROOT / "components" / "AgentPipeline.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "globals.css").read_text(encoding="utf-8")

    for label in (
        'corpus_version: "코퍼스 버전"',
        'neutral: "중립 신호"',
        'risk: "위험 신호"',
        'claims: "검증 주장"',
        'chunks: "검토 근거"',
        'calls: "호출 횟수"',
        'verdict: "근거 판정"',
        'grounded: "근거 확인"',
        'partially_grounded: "일부 근거 확인"',
        'not_grounded: "근거 부족"',
        'input_mode: "자료 입력 방식"',
        'remaining: "기준일 통과 근거"',
        'insufficient: "표본 부족 언어권"',
        'linked_risks: "연결된 위험"',
        'analysis_incomplete: "분석 미완료"',
        'revisions: "수정안"',
        'update_type: "업데이트 유형"',
        'accepted: "사용 근거"',
        'errors: "오류"',
        'comparable_reference: "비교 참고 근거"',
        'metrics_complete: "검증 지표 충족"',
        'corpus: "사전 구축 코퍼스"',
        'weapon_balance: "무기 밸런스"',
    ):
        assert label in pipeline
    assert ".corpus-date-action:focus-visible" in styles
    assert "outline:3px solid var(--accent)" in styles
    assert "outline:3px solid #5e6ad233" not in styles


def test_corpus_demo_dates_follow_browser_utc_day():
    script = """
import { corpusDemoDates, isFutureUtcDate } from "./frontend/app/components/corpusDemoDates.ts";

const now = new Date("2026-08-19T23:59:59Z");
process.stdout.write(JSON.stringify({
  dates: corpusDemoDates(now),
  todayAllowed: isFutureUtcDate("2026-08-19", now),
  tomorrowAllowed: isFutureUtcDate("2026-08-20", now),
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
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "dates": {
            "cutoffOn": "2026-08-20",
            "startsOn": "2026-08-21",
            "endsOn": "2026-08-28",
        },
        "todayAllowed": False,
        "tomorrowAllowed": True,
    }


def test_shared_decision_report_has_accessible_one_page_structure():
    source = (ROOT / "components" / "DecisionReport.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "globals.css").read_text(encoding="utf-8")

    for name in (
        "DecisionReportData",
        "subject",
        "decisionLabel",
        "conclusion",
        "fullReasoning",
        "sourceScope",
        "analysisIncomplete",
        "expectedCard",
        "riskCard",
        "actionCard",
        "riskRows",
        "reactionDetails",
        "evidenceDetails",
        "agentDetails",
    ):
        assert name in source
    assert "useEffect" in source
    assert "headingRef.current?.focus()" in source
    assert "knownDecisions.includes(decision)" in source
    assert 'tabIndex={-1}' in source
    assert 'role="alert"' in source
    assert "analysisIncomplete &&" in source
    assert "판정 논리 전체 보기" in source
    assert "실제 이용자 인용이 아닙니다" in source
    assert "예상 반응과 이용자 유형" in source
    assert "언어권과 판단 근거" in source
    assert "에이전트 실행 과정과 산출물" in source
    assert "<table" in source
    assert 'data-label="위험"' in source
    assert 'data-label="출시 전 확인"' in source
    assert ".decision-report-card-grid" in styles
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in styles
    assert "content:attr(data-label)" in styles


def test_event_result_maps_contract_to_shared_decision_report():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert 'import { DecisionReport, DecisionReportData }' in source
    assert "decision_reason: string" in source
    assert "input_mode?: string" in source
    assert "submittedSubject" in source
    assert "const requestSubject = form.event_name.trim()" in source
    assert "setSubmittedSubject(requestSubject)" in source
    assert "function selectEventPanel" in source
    assert "function findEventRevision" in source
    assert "function buildEventReport" in source
    assert "top_risks[0]" in source
    assert "addresses_risk_ids.includes(riskId)" in source
    assert "uniqueEvidenceCount(panel.evidence_ids)" in source
    assert "left.confidence" in source
    assert "left.persona.localeCompare(right.persona)" in source
    assert 'opinionVisible={visibleOpinions.has(panel.persona)}' in source
    assert "feedback.input_mode" in source
    assert "<DecisionReport" in source
    assert "reactionDetails={" in source
    assert "evidenceDetails={" in source
    assert "agentDetails={" in source
    assert "result.fallback_used &&" not in source
    assert "ref={decisionHeading}" not in source


def test_audience_cards_can_hide_duplicate_opinion_and_name_confidence_correctly():
    source = (ROOT / "components" / "AudienceCards.tsx").read_text(encoding="utf-8")

    assert "opinionVisible = true" in source
    assert "opinionVisible ?" in source
    assert "대표 의견은 관련 이용자 유형 카드에 함께 표시했습니다" in source
    assert source.count("근거 일치도") == 2
    assert "<small>신뢰도</small>" not in source


def test_decision_report_css_is_parseable():
    script = '''
import fs from "node:fs";
import postcss from "./frontend/node_modules/postcss/lib/postcss.js";

postcss.parse(fs.readFileSync("frontend/app/globals.css", "utf8"));
'''

    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
