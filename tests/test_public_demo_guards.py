from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from agents.structured import ClaudeBudget
import backend.app.main as api_main
from backend.app.main import app
from backend.app.schemas import PipelineRunRequest, UpdateRunRequest
from tests.test_api import request_payload
from tests.test_update_api import payload as update_payload


@pytest.fixture
def public_demo(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "1")
    monkeypatch.setattr(api_main, "_PUBLIC_DEMO_BUDGET", None)


def test_public_budget_is_reused_by_sequential_event_and_update_runs(
    monkeypatch, public_demo
):
    captured = []

    class StopAfterWiring(RuntimeError):
        pass

    class SpyOrchestrator:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def run(self, *_args, **_kwargs):
            raise StopAfterWiring

    monkeypatch.setattr(api_main, "EventPreflightOrchestrator", SpyOrchestrator)
    monkeypatch.setattr(api_main, "UpdateReviewOrchestrator", SpyOrchestrator)

    with pytest.raises(StopAfterWiring):
        api_main._run(
            PipelineRunRequest.model_validate(
                request_payload() | {"use_llm": True, "llm_provider": "openai"}
            ),
            "public-event",
        )
    with pytest.raises(StopAfterWiring):
        api_main._run_update(
            UpdateRunRequest.model_validate(update_payload() | {"use_llm": True}),
            "public-update",
        )

    assert captured[0]["budget"] is captured[1]["budget"]
    assert captured[0]["llm_provider"] == "claude"
    assert captured[0]["budget"].max_requests == 12
    assert captured[0]["budget"].max_usd == 3.0


def test_team_sidecars_reuse_supplied_budget():
    budget = ClaudeBudget(max_requests=12, max_usd=3)

    returned, runner, probe = api_main._team_sidecars(budget)

    assert returned is runner.budget is probe.budget is budget


def test_both_public_requests_default_to_no_llm():
    event_body = request_payload()
    update_body = update_payload()
    event_body.pop("use_llm", None)
    update_body.pop("use_llm", None)

    assert PipelineRunRequest.model_validate(event_body).use_llm is False
    assert UpdateRunRequest.model_validate(update_body).use_llm is False


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/runs", request_payload()),
        ("/api/runs/stream", request_payload()),
        ("/api/update-runs", update_payload()),
        ("/api/update-runs/stream", update_payload()),
    ],
)
def test_public_demo_rejects_a_second_concurrent_run(path, body, public_demo):
    assert api_main._PUBLIC_DEMO_RUN_LOCK.acquire(blocking=False)
    try:
        response = TestClient(app).post(path, json=body)
    finally:
        api_main._PUBLIC_DEMO_RUN_LOCK.release()

    assert response.status_code == 429
    assert "다른 점검" in response.json()["detail"]


def _assert_public_lock_available():
    assert api_main._PUBLIC_DEMO_RUN_LOCK.acquire(blocking=False)
    api_main._PUBLIC_DEMO_RUN_LOCK.release()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/runs", request_payload()),
        ("/api/runs/stream", request_payload()),
        ("/api/update-runs", update_payload()),
        ("/api/update-runs/stream", update_payload()),
    ],
)
def test_run_id_failure_does_not_leak_public_lock(
    monkeypatch, path, body, public_demo
):
    def fail_uuid():
        raise RuntimeError("unsafe-uuid-detail")

    monkeypatch.setattr(api_main, "uuid4", fail_uuid)

    response = TestClient(app, raise_server_exceptions=False).post(path, json=body)

    assert response.status_code == 500
    assert "unsafe-uuid-detail" not in response.text
    _assert_public_lock_available()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/runs/stream", request_payload()),
        ("/api/update-runs/stream", update_payload()),
    ],
)
def test_sse_queue_failure_does_not_leak_public_lock(
    monkeypatch, path, body, public_demo
):
    def fail_queue():
        raise RuntimeError("unsafe-queue-detail")

    monkeypatch.setattr(api_main, "Queue", fail_queue)

    response = TestClient(app, raise_server_exceptions=False).post(path, json=body)

    assert response.status_code == 500
    assert "unsafe-queue-detail" not in response.text
    _assert_public_lock_available()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/runs/stream", request_payload()),
        ("/api/update-runs/stream", update_payload()),
    ],
)
def test_sse_thread_start_failure_releases_public_lock(
    monkeypatch, path, body, public_demo
):
    class FailingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("unsafe-thread-detail")

    monkeypatch.setattr(api_main, "Thread", FailingThread)

    response = TestClient(app, raise_server_exceptions=False).post(path, json=body)

    assert response.status_code == 500
    assert "unsafe-thread-detail" not in response.text
    _assert_public_lock_available()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/runs",
            request_payload() | {"source_mode": "live", "steam_app_id": 578080},
        ),
        (
            "/api/runs/stream",
            request_payload()
            | {
                "source_mode": "import",
                "imported_csv": base64.b64encode(b"source,summary\nsteam,safe").decode(),
            },
        ),
        (
            "/api/update-runs",
            update_payload()
            | {
                "source_mode": "live",
                "steam_app_id": 578080,
                "period_start": "2026-08-12T00:00:00Z",
                "period_end": "2026-08-13T00:00:00Z",
            },
        ),
        (
            "/api/update-runs/stream",
            update_payload() | {"source_mode": "import", "imported_csv": "safe"},
        ),
    ],
)
def test_public_demo_allows_only_fixture_or_corpus(path, body, public_demo):
    response = TestClient(app).post(path, json=body)

    assert response.status_code == 403
    assert "검증된 저장 자료" in response.json()["detail"]


def test_public_demo_does_not_write_run_jsonl(monkeypatch, tmp_path, public_demo):
    monkeypatch.setattr(api_main, "ROOT", tmp_path)

    response = TestClient(app).post("/api/runs", json=request_payload())

    assert response.status_code == 200, response.text
    assert not (tmp_path / ".data" / "runs").exists()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_DEMO_MAX_REQUESTS", "invalid-request-count"),
        ("PUBLIC_DEMO_MAX_REQUESTS", "-1"),
        ("PUBLIC_DEMO_MAX_USD", "invalid-budget"),
        ("PUBLIC_DEMO_MAX_USD", "-0.01"),
        ("PUBLIC_DEMO_MAX_USD", "nan"),
        ("PUBLIC_DEMO_MAX_USD", "inf"),
    ],
)
def test_invalid_public_budget_fails_before_provider_without_leaking_value(
    monkeypatch, name, value, public_demo
):
    provider_started = False

    class ProviderSpy:
        def __init__(self, **_kwargs):
            nonlocal provider_started
            provider_started = True

    monkeypatch.setenv(name, value)
    monkeypatch.setattr(api_main, "EventPreflightOrchestrator", ProviderSpy)

    response = TestClient(app).post(
        "/api/runs", json=request_payload() | {"use_llm": True}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "검토 실행 중 오류가 발생했습니다."
    assert value not in response.text
    assert provider_started is False
    _assert_public_lock_available()


def test_zero_public_budget_is_valid(monkeypatch, public_demo):
    monkeypatch.setenv("PUBLIC_DEMO_MAX_REQUESTS", "0")
    monkeypatch.setenv("PUBLIC_DEMO_MAX_USD", "0")

    budget = api_main._public_demo_budget()

    assert budget.max_requests == 0
    assert budget.max_usd == 0


def test_nonpublic_run_keeps_existing_jsonl_behavior(monkeypatch, tmp_path):
    monkeypatch.delenv("PUBLIC_DEMO_MODE", raising=False)
    monkeypatch.setattr(api_main, "ROOT", tmp_path)

    response = TestClient(app).post("/api/runs", json=request_payload())

    assert response.status_code == 200, response.text
    assert len(list((tmp_path / ".data" / "runs").glob("*.jsonl"))) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"goal": "가" * 8_001},
        {"target_users": [f"이용자-{index}" for index in range(21)]},
        {"target_users": ["가" * 1_001]},
        {"x_query": "가" * 501},
    ],
)
def test_event_request_rejects_oversized_text_and_lists(change):
    response = TestClient(app).post("/api/runs", json=request_payload() | change)

    assert response.status_code == 422
    assert "요청 형식이 올바르지 않습니다" in response.text
