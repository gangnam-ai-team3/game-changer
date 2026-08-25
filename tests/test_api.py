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
    assert "시간이 부족한 복귀 이용자" in result["brief"]["executive_summary"]
    assert "가성비를 중시하는 이용자" in result["brief"]["executive_summary"]
    assert "긍정 반응을 뒷받침할 신호보다" in result["brief"]["executive_summary"]
    assert "수정을 먼저 반영하는 것이 합당" in result["brief"]["executive_summary"]
    assert "판정은 반응 수가 아니라 검증된 위험의 크기" in result["brief"]["executive_summary"]
    assert "수정안을 반영한 뒤 Black Market 2025의 기획안을 다시 검토" in result["brief"]["executive_summary"]
    assert "이용자 유형" not in result["brief"]["executive_summary"]
    assert result["feedback"]["evidence"]
    assert result["events"]
    assert all("개 우선 위험" not in panel["reaction"] for panel in result["brief"]["panel_results"])
    assert all(
        "예상 대표 의견:" in panel["reaction"] and "예상 행동:" in panel["reaction"]
        for panel in result["brief"]["panel_results"]
    )
    assert all(
        "위험 때문에 원안 참여" not in panel["reaction"]
        for panel in result["brief"]["panel_results"]
    )


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
    assert "긍정 반응과 우려 반응을 따로 분류하지 않으므로" in result["brief"]["executive_summary"]
    assert "높은 위험으로 검증되지 않았으므로" in result["brief"]["executive_summary"]
    assert all(
        "예상 대표 의견:" in panel["reaction"] and "예상 행동:" in panel["reaction"]
        for panel in result["brief"]["panel_results"]
    )
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
