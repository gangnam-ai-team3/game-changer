from __future__ import annotations

import json

from fastapi.testclient import TestClient

import backend.app.main as api_main
from backend.app.main import app


def event_payload() -> dict:
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


def payload() -> dict:
    return {
        "game": "PUBG: BATTLEGROUNDS",
        "update_name": "Dragunov 확률 피해 제거",
        "update_type": "weapon_balance",
        "current_state": "기본 58, 최대 73의 확률형 피해",
        "change_summary": "피해를 60으로 고정",
        "goal": "전투 결과 예측 가능성을 높인다.",
        "expected_benefits": ["공정성 인식 개선"],
        "concerns": ["실제 전투 성능은 확인 필요"],
        "scope": "일반 매칭",
        "planned_on": "2026-08-20",
        "cutoff_on": "2026-08-13",
        "official_context_url": "https://pubg.com/en/news/6616",
        "official_context": "PUBG Update 25.2의 확률형 피해 제거 공식 변경 맥락",
        "details": {
            "kind": "weapon_balance",
            "target_weapon": "Dragunov",
            "damage": "기본 58·최대 73 확률 → 60 고정",
            "recoil": "현행 유지",
            "rate_of_fire": "해당 없음",
            "ammunition": "7.62mm",
            "spawn_and_modes": "일반 매칭",
        },
        "source_mode": "fixture",
        "fixture_case": "dragunov_random_damage_removal",
        "use_llm": False,
    }


def test_update_fixture_endpoint_returns_prelaunch_test_decision():
    response = TestClient(app).post("/api/update-runs", json=payload())

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["brief"]["decision"] == "Test"
    assert result["feedback"]["input_mode"] == "fixture"
    assert {item["period"] for item in result["brief"]["evidence"]} == {
        "comparable_reference"
    }
    assert all(item["synthetic"] for item in result["brief"]["evidence"])
    assert result["fallback_used"] is False
    assert result["analysis_incomplete"] is False
    assert result["llm_provider"] == "deterministic"
    assert result["llm_requested"] is False
    assert result["events"]


def test_update_type_details_must_match():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {"update_type": "ui_ux"},
    )

    assert response.status_code == 422
    assert "details kind must match update_type" in response.text


def test_update_live_request_requires_time_window_and_connector():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {"source_mode": "live"},
    )

    assert response.status_code == 422
    assert "live source requires" in response.text


def test_dragunov_fixture_is_available_only_for_weapon_balance():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload()
        | {
            "update_type": "ui_ux",
            "details": {
                "kind": "ui_ux",
                "changed_screen": "인벤토리",
                "user_journey": "상품 선택 → 착용",
                "exposed_information": "능력치",
                "possible_errors": "해당 없음",
            },
        },
    )

    assert response.status_code == 422
    assert "Dragunov fixture requires weapon_balance" in response.text


def test_update_stream_emits_agent_nodes_and_result():
    response = TestClient(app).post("/api/update-runs/stream", json=payload())

    assert response.status_code == 200
    frames = [frame for frame in response.text.split("\n\n") if frame]
    event_names = [
        line.removeprefix("event: ")
        for frame in frames
        for line in frame.splitlines()
        if line.startswith("event: ")
    ]
    assert event_names[0] == "started"
    assert event_names[-2:] == ["result", "done"]
    assert event_names.count("agent_event") >= 4
    assert '"decision": "Test"' in response.text


def test_update_import_failure_is_partial_hold_and_never_persists_raw_text(
    monkeypatch, tmp_path
):
    secret = "raw-import-secret-should-never-persist"
    csv_with_banned_column = (
        "source,source_url,source_id,language,observed_at,period,sentiment,summary,"
        "mechanism_tags,raw_text\n"
        f"reddit,https://reddit.com/r/PUBATTLEGROUNDS/a,example,ko,"
        f"2026-08-12T00:00:00+00:00,before,negative,summary,balance_regression,{secret}\n"
    )
    monkeypatch.setattr(api_main, "ROOT", tmp_path)

    response = TestClient(app).post(
        "/api/update-runs",
        json=payload()
        | {"source_mode": "import", "imported_csv": csv_with_banned_column},
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["feedback"]["status"] == "partial"
    assert result["brief"]["decision"] == "Hold"
    assert result["analysis_incomplete"] is True
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / ".data" / "runs").glob("*.jsonl")
    )
    assert secret not in json.dumps(result, ensure_ascii=False)
    assert secret not in persisted


def test_update_request_rejects_key_fields_without_reflecting_secret():
    secret = "test-credential-value-must-not-appear"
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {"anthropic_api_key": secret},
    )

    assert response.status_code == 422
    assert secret not in response.text


def test_update_stream_never_exposes_import_raw_text(monkeypatch, tmp_path):
    secret = "raw-stream-secret-should-never-persist"
    csv_with_banned_column = (
        "source,source_url,source_id,language,observed_at,period,sentiment,summary,"
        "mechanism_tags,raw_text\n"
        f"reddit,https://reddit.com/r/PUBATTLEGROUNDS/a,example,ko,"
        f"2026-08-12T00:00:00+00:00,before,negative,summary,balance_regression,{secret}\n"
    )
    monkeypatch.setattr(api_main, "ROOT", tmp_path)

    response = TestClient(app).post(
        "/api/update-runs/stream",
        json=payload()
        | {"source_mode": "import", "imported_csv": csv_with_banned_column},
    )

    assert response.status_code == 200
    assert '"decision": "Hold"' in response.text
    assert secret not in response.text
    assert "event: done" in response.text


def test_existing_event_endpoint_still_works():
    response = TestClient(app).post("/api/runs", json=event_payload())

    assert response.status_code == 200
    assert response.json()["result"]["brief"]["decision"] == "Revise"
