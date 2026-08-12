from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_default_fixture_renders_decision_brief():
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=20)
    assert not app.exception
    app.button[0].click().run(timeout=20)
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["판단"] == "Revise"
    assert metrics["공식 핵심 문제 발견"] == "4/4"
    assert metrics["상위 위험 근거 연결"] == "100%"
