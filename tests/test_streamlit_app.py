from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents.collector import CollectionOptions, CollectorAgent
from contracts import InputMode
from orchestrator import EventPreflightOrchestrator


def run_fixture():
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=20)
    assert not app.exception
    app.button[0].click().run(timeout=20)
    assert not app.exception
    return app


def test_default_fixture_renders_decision_brief():
    app = run_fixture()
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["최종 판정"] == "Revise"
    assert metrics["공식 핵심 문제 발견"] == "4/4"
    assert metrics["상위 위험 근거 연결"] == "100%"


def test_completed_fixture_prioritizes_decision_and_has_four_collapsed_agent_traces():
    app = run_fixture()
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["최종 판정"] == "Revise"
    warnings = [item.value for item in app.warning]
    assert any("자문용" in warning and "사람이 최종 결정" in warning for warning in warnings)
    labels = [item.label for item in app.expander]
    assert labels == [
        "1. 수집 에이전트",
        "2. 근거 분석 에이전트",
        "3. 레드팀 에이전트",
        "4. 감사·전략 에이전트",
    ]
    assert all(not item.proto.expanded for item in app.expander)


def test_completed_view_surfaces_fallback_warning():
    app = run_fixture()
    result = app.session_state["preflight_result"]
    result.fallback_used = True
    app.session_state["preflight_result"] = result

    app.run(timeout=20)

    warnings = [item.value for item in app.warning]
    assert any("안전 경로" in warning and "불완전" in warning for warning in warnings)


def test_empty_live_result_does_not_run_demo_backtest(monkeypatch, event):
    class EmptySteam:
        def fetch_reviews(self, _app_id, language, cutoff_at, limit=100):
            return []

    live_result = EventPreflightOrchestrator(
        collector=CollectorAgent(steam=EmptySteam())
    ).run(event, CollectionOptions(use_fixture=False, steam_app_id=578080))
    assert live_result.feedback.input_mode == InputMode.LIVE
    assert live_result.brief.evidence == []
    monkeypatch.setattr(
        "orchestrator.EventPreflightOrchestrator.run",
        lambda *_args, **_kwargs: live_result,
    )

    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=20)
    app.radio[0].set_value("Steam 실시간 갱신").run(timeout=20)
    app.button[0].click().run(timeout=20)

    text = "\n".join(item.value for item in app.markdown)
    assert "데모 전용 백테스트" not in text
    assert "공식 핵심 문제 발견" not in {metric.label for metric in app.metric}


def test_unexpected_submitted_error_is_sanitized_and_clears_stale_result(monkeypatch):
    app = run_fixture()
    assert "preflight_result" in app.session_state
    monkeypatch.setattr(
        "orchestrator.EventPreflightOrchestrator.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("username alice raw internal detail")
        ),
    )

    app.button[0].click().run(timeout=20)

    assert not app.exception
    assert "preflight_result" not in app.session_state
    assert app.session_state["preflight_error"] == "예상하지 못한 오류로 실행을 중단했습니다."
    rendered_errors = "\n".join(item.value for item in app.error)
    assert "alice" not in rendered_errors
    assert "raw internal detail" not in rendered_errors


def test_agent_trace_contains_intermediate_outputs_and_evidence():
    app = run_fixture()
    text = "\n".join(item.value for item in app.markdown)
    assert "FeedbackBundle" in text
    assert "EvidencePack" in text
    assert "RiskAssessment" in text
    assert "ValidatedDecision" in text
    assert "근거 ID" in text
    assert "실행 지표" in text


def test_recovery_runs_a_fresh_fixture_pipeline():
    app = run_fixture()
    initial_run_id = app.session_state["preflight_result"].brief.run_id
    app.date_input[0].set_value(date(2026, 2, 1))
    app.date_input[1].set_value(date(2026, 1, 1))
    app.run(timeout=20)
    app.button[0].click().run(timeout=20)
    assert "preflight_result" not in app.session_state

    app.date_input[0].set_value(date(2026, 1, 1))
    app.date_input[1].set_value(date(2026, 2, 1))
    app.run(timeout=20)
    app.button[1].click().run(timeout=20)

    assert app.radio[0].value == "검증된 저장 데이터"
    assert app.session_state["preflight_result"].brief.run_id != initial_run_id
