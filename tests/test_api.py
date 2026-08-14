from fastapi.testclient import TestClient

from backend.app.main import app


def request_payload() -> dict:
    return {
        "game": "PUBG: BATTLEGROUNDS",
        "event_name": "Black Market 2025",
        "goal": "목표 보상까지의 비용과 진행 경로를 명확히 이해할 수 있도록 한다.",
        "target_users": ["복귀 유저"],
        "starts_on": "2025-06-11",
        "ends_on": "2025-07-22",
        "cutoff_on": "2025-06-11",
        "participation_rule": "패스 미션",
        "repeat_rule": "일일 미션",
        "rewards": ["Progressive weapon skin"],
        "currencies": ["G-Coin"],
        "probability_guarantee": "고정 보장 없음",
        "monetization_policy": "확률형 상품 판매",
        "expiration_policy": "종료 후 삭제",
        "source_mode": "fixture",
    }


def test_health_endpoint():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_fixture_run_returns_pipeline_artifacts():
    response = TestClient(app).post("/api/runs", json=request_payload())
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["brief"]["decision"] == "Revise"
    assert "수정 필요" in result["brief"]["executive_summary"]
    assert result["feedback"]["evidence"]
    assert result["events"]
    assert all("개 우선 위험" not in panel["reaction"] for panel in result["brief"]["panel_results"])


def test_weekly_supply_fixture_is_a_clear_go_case():
    response = TestClient(app).post(
        "/api/runs",
        json=request_payload()
        | {
            "event_name": "Weekly Supply",
            "goal": "주간 미션과 BP 보상을 명확히 이해하도록 한다.",
            "target_users": ["모든 이용자"],
            "ends_on": "2025-07-09",
            "participation_rule": "주간 미션 완료",
            "repeat_rule": "매주 수요일 UTC 02:00 초기화",
            "rewards": ["최대 23,000 BP"],
            "currencies": ["BP"],
            "probability_guarantee": "확률 없음. 정해진 BP 보상",
            "monetization_policy": "유료 구매 없음",
            "expiration_policy": "초기화 전에 보상 수령",
            "fixture_case": "weekly_supply_2025",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["brief"]["decision"] == "Go"
    assert result["brief"]["top_risks"] == []
    assert len(result["feedback"]["evidence"]) == 75
    assert result["feedback"]["evidence"][0]["source_url"].startswith("https://pubg.com/")


def test_claude_request_without_key_uses_fixture_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = TestClient(app).post("/api/runs", json=request_payload() | {"use_llm": True})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["llm_requested"] is True
    assert result["llm_provider"] == "claude"
    assert result["fallback_used"] is True
    assert result["brief"]["decision"] == "Revise"


def test_live_source_requires_connector():
    payload = request_payload() | {"source_mode": "live"}
    response = TestClient(app).post("/api/runs", json=payload)
    assert response.status_code == 422
    assert "live source requires" in response.json()["detail"][0]["msg"]


def test_stream_run_emits_agent_events_and_final_result():
    response = TestClient(app).post("/api/runs/stream", json=request_payload())
    assert response.status_code == 200
    assert "event: agent_event" in response.text
    assert '"decision": "Revise"' in response.text
    assert "event: done" in response.text
