from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import repository
from app.config import Settings
from app.db import init_db, make_engine, make_session_factory
from app.main import app, get_anthropic_client, get_app_settings, get_session, get_voyage_client


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def _test_settings() -> Settings:
    return Settings(anthropic_api_key="test-key", voyage_api_key="test-key", database_url="sqlite:///:memory:")


def _client_with_mocks(monkeypatch, claims, grounded_ratio):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    SessionFactory = make_session_factory(engine)

    def override_session():
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(
        "app.main.pipeline.run_audit",
        AsyncMock(return_value={"claims": claims, "grounded_ratio": grounded_ratio}),
    )

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_app_settings] = _test_settings
    app.dependency_overrides[get_anthropic_client] = lambda: None
    app.dependency_overrides[get_voyage_client] = lambda: None

    return TestClient(app)


def test_create_audit_persists_and_returns_result(monkeypatch):
    claims = [
        {
            "claim_text": "Paris is the capital of France.",
            "verdict": "grounded",
            "citations": ["c1"],
            "rationale": "matches c1",
        }
    ]
    client = _client_with_mocks(monkeypatch, claims, grounded_ratio=1.0)

    response = client.post(
        "/audits",
        json={
            "response_text": "Paris is the capital of France.",
            "source_chunks": [{"id": "c1", "text": "Paris is the capital of France."}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["grounded_ratio"] == 1.0
    assert body["claims"][0]["verdict"] == "grounded"


def test_get_audit_returns_404_for_missing_id(monkeypatch):
    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)

    response = client.get("/audits/does-not-exist")

    assert response.status_code == 404


def test_full_round_trip_create_then_get(monkeypatch):
    claims = [{"claim_text": "x", "verdict": "grounded", "citations": ["c1"], "rationale": "r"}]
    client = _client_with_mocks(monkeypatch, claims, grounded_ratio=1.0)

    created = client.post(
        "/audits", json={"response_text": "x", "source_chunks": [{"id": "c1", "text": "x"}]}
    ).json()
    fetched = client.get(f"/audits/{created['audit_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["audit_id"] == created["audit_id"]


def test_create_audit_returns_502_when_pipeline_raises(monkeypatch):
    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)
    monkeypatch.setattr(
        "app.main.pipeline.run_audit", AsyncMock(side_effect=RuntimeError("upstream boom"))
    )

    response = client.post(
        "/audits", json={"response_text": "x", "source_chunks": [{"id": "c1", "text": "x"}]}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream LLM/embedding provider error"


def test_list_audits_filters_by_source_system_and_orders_desc(monkeypatch):
    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)

    first = client.post(
        "/audits", json={"response_text": "a", "metadata": {"source_system": "sys-a"}}
    ).json()
    client.post("/audits", json={"response_text": "b", "metadata": {"source_system": "sys-b"}})
    second = client.post(
        "/audits", json={"response_text": "c", "metadata": {"source_system": "sys-a"}}
    ).json()

    response = client.get("/audits", params={"source_system": "sys-a"})

    assert response.status_code == 200
    body = response.json()
    assert [item["audit_id"] for item in body] == [second["audit_id"], first["audit_id"]]


def test_list_audits_rejects_limit_above_upper_bound(monkeypatch):
    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)

    response = client.get("/audits", params={"limit": 500})

    assert response.status_code == 422


def test_list_audits_filters_by_created_from(monkeypatch):
    from datetime import datetime, timedelta, timezone

    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)
    client.post("/audits", json={"response_text": "a", "metadata": {"source_system": "sys-a"}})

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.get("/audits", params={"created_from": future})

    assert response.status_code == 200
    assert response.json() == []


class _FakeAnthropicMessages:
    """Mimics AsyncAnthropic's messages.create for both extract_claims and judge_claim calls."""

    def __init__(self, claims: list[str], judge_responses: dict[str, dict]):
        self._claims = claims
        self._judge_responses = judge_responses

    async def create(self, *, model, max_tokens, tools, tool_choice, messages):
        tool_name = tool_choice["name"]
        if tool_name == "extract_claims":
            block = SimpleNamespace(
                type="tool_use", name="extract_claims", input={"claims": self._claims}
            )
            return SimpleNamespace(content=[block], stop_reason="tool_use")
        assert tool_name == "judge_claim"
        prompt = messages[0]["content"]
        for claim_text, tool_input in self._judge_responses.items():
            if f"Claim: {claim_text}" in prompt:
                block = SimpleNamespace(type="tool_use", name="judge_claim", input=tool_input)
                return SimpleNamespace(content=[block], stop_reason="tool_use")
        raise AssertionError(f"no fake judge response configured for prompt: {prompt}")


class _FakeVoyageClient:
    def embed(self, texts, model):
        return SimpleNamespace(embeddings=[[float(len(t) % 7)] for t in texts])


def test_create_audit_end_to_end_through_real_pipeline(monkeypatch):
    """Runs the real pipeline (no pipeline mock) against fake LLM/embedding clients, so the
    pipeline -> repository seam (including Critical #1's validation) executes for real."""
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    SessionFactory = make_session_factory(engine)

    def override_session():
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()

    claims = ["Paris is the capital of France.", "The moon is made of cheese."]
    judge_responses = {
        "Paris is the capital of France.": {
            "verdict": "grounded",
            "citations": ["c1"],
            "rationale": "matches c1",
        },
        # Deliberately malformed / out-of-enum verdict to exercise Critical #1's validation
        # seam end-to-end: this must degrade to judgment_failed, not 500 the request.
        "The moon is made of cheese.": {
            "verdict": "definitely_not_a_real_verdict",
            "citations": [],
            "rationale": "bad",
        },
    }
    anthropic_client = SimpleNamespace(messages=_FakeAnthropicMessages(claims, judge_responses))
    voyage_client = _FakeVoyageClient()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_app_settings] = _test_settings
    app.dependency_overrides[get_anthropic_client] = lambda: anthropic_client
    app.dependency_overrides[get_voyage_client] = lambda: voyage_client

    client = TestClient(app)
    response = client.post(
        "/audits",
        json={
            "response_text": "Paris is the capital of France. The moon is made of cheese.",
            "source_chunks": [{"id": "c1", "text": "Paris is the capital of France."}],
            "metadata": {"source_system": "chatbot-x"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    verdicts = {c["claim_text"]: c["verdict"] for c in body["claims"]}
    assert verdicts["Paris is the capital of France."] == "grounded"
    assert verdicts["The moon is made of cheese."] == "judgment_failed"

    # Verify source_chunks and metadata["source_system"] actually landed in the DB via the API,
    # not by calling repository functions directly to prepare the fixture.
    session = SessionFactory()
    try:
        audit = repository.get_audit(session, body["audit_id"])
        assert audit.source_system == "chatbot-x"
        assert len(audit.source_chunks) == 1
        assert audit.source_chunks[0].chunk_id == "c1"
        assert audit.source_chunks[0].chunk_text == "Paris is the capital of France."
    finally:
        session.close()
