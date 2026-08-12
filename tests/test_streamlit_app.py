from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest


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
    labels = [item.label for item in app.expander]
    assert labels == [
        "1. 수집 에이전트",
        "2. 근거 분석 에이전트",
        "3. 레드팀 에이전트",
        "4. 감사·전략 에이전트",
    ]
    assert all(not item.proto.expanded for item in app.expander)


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
