from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.claim_extractor import ExtractionError, extract_claims


async def test_extract_claims_returns_claims_from_tool_use_block():
    tool_block = SimpleNamespace(
        type="tool_use",
        name="extract_claims",
        input={"claims": ["Paris is the capital of France.", "France is in Europe."]},
    )
    message = SimpleNamespace(content=[tool_block], stop_reason="tool_use")
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))

    claims = await extract_claims(
        client, model="claude-sonnet-5",
        response_text="Paris is the capital of France. France is in Europe.",
    )

    assert claims == ["Paris is the capital of France.", "France is in Europe."]
    client.messages.create.assert_awaited_once()


async def test_extract_claims_returns_empty_list_when_no_tool_use_block():
    message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="no claims")], stop_reason="end_turn"
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))

    claims = await extract_claims(client, model="claude-sonnet-5", response_text="hi")

    assert claims == []


async def test_extract_claims_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.claim_extractor.asyncio.sleep", AsyncMock())
    tool_block = SimpleNamespace(
        type="tool_use", name="extract_claims", input={"claims": ["claim-a"]}
    )
    message = SimpleNamespace(content=[tool_block], stop_reason="tool_use")
    create = AsyncMock(side_effect=[RuntimeError("timeout"), message])
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    claims = await extract_claims(
        client, model="claude-sonnet-5", response_text="claim-a", max_retries=2
    )

    assert claims == ["claim-a"]
    assert create.await_count == 2


async def test_extract_claims_raises_extraction_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.claim_extractor.asyncio.sleep", AsyncMock())
    create = AsyncMock(side_effect=RuntimeError("timeout"))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    with pytest.raises(ExtractionError):
        await extract_claims(
            client, model="claude-sonnet-5", response_text="x", max_retries=2
        )

    assert create.await_count == 3


async def test_extract_claims_raises_extraction_error_on_max_tokens_truncation(monkeypatch):
    monkeypatch.setattr("app.claim_extractor.asyncio.sleep", AsyncMock())
    message = SimpleNamespace(content=[], stop_reason="max_tokens")
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    with pytest.raises(ExtractionError):
        await extract_claims(
            client, model="claude-sonnet-5", response_text="x", max_retries=0
        )
