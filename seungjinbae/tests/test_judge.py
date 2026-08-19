from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.judge import JudgeError, judge_claim


async def test_judge_claim_returns_parsed_verdict():
    tool_block = SimpleNamespace(
        type="tool_use",
        name="judge_claim",
        input={"verdict": "grounded", "citations": ["c1"], "rationale": "matches c1"},
    )
    message = SimpleNamespace(content=[tool_block])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))

    result = await judge_claim(
        client, model="claude-sonnet-5", claim_text="Paris is the capital of France.",
        candidate_chunks=[{"id": "c1", "text": "Paris is the capital of France."}],
    )

    assert result == {"verdict": "grounded", "citations": ["c1"], "rationale": "matches c1"}


async def test_judge_claim_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    tool_block = SimpleNamespace(
        type="tool_use", name="judge_claim",
        input={"verdict": "not_grounded", "citations": [], "rationale": "no match"},
    )
    message = SimpleNamespace(content=[tool_block])
    create = AsyncMock(side_effect=[RuntimeError("timeout"), message])
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    result = await judge_claim(
        client, model="claude-sonnet-5", claim_text="x", candidate_chunks=[], max_retries=2
    )

    assert result["verdict"] == "not_grounded"
    assert create.await_count == 2


async def test_judge_claim_raises_judge_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    create = AsyncMock(side_effect=RuntimeError("timeout"))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    with pytest.raises(JudgeError):
        await judge_claim(
            client, model="claude-sonnet-5", claim_text="x", candidate_chunks=[], max_retries=2
        )

    assert create.await_count == 3


async def test_judge_claim_raises_judge_error_on_missing_key(monkeypatch):
    """A truncated/malformed tool_use block (missing a required key) must degrade to
    JudgeError -- caught by the retry loop and eventually the caller's judgment_failed
    fallback -- instead of raising a bare KeyError that crashes the whole audit request."""
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    tool_block = SimpleNamespace(
        type="tool_use", name="judge_claim", input={"verdict": "grounded", "rationale": "x"}
    )
    message = SimpleNamespace(content=[tool_block])
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    with pytest.raises(JudgeError):
        await judge_claim(
            client, model="claude-sonnet-5", claim_text="x", candidate_chunks=[], max_retries=0
        )


async def test_judge_claim_raises_judge_error_on_invalid_verdict(monkeypatch):
    """An out-of-enum verdict must never be returned as a valid result -- it should raise
    JudgeError (and thus degrade to judgment_failed upstream) rather than silently persisting
    an invalid verdict value into the DB / response schema."""
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    tool_block = SimpleNamespace(
        type="tool_use",
        name="judge_claim",
        input={"verdict": "maybe_grounded", "citations": [], "rationale": "x"},
    )
    message = SimpleNamespace(content=[tool_block])
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    with pytest.raises(JudgeError):
        await judge_claim(
            client, model="claude-sonnet-5", claim_text="x", candidate_chunks=[], max_retries=0
        )


async def test_judge_claim_raises_judge_error_on_unexpected_extra_key(monkeypatch):
    """An unexpected extra key in the tool input must not reach the caller (and thence the
    ORM constructor) -- it should be caught and raised as JudgeError instead."""
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    tool_block = SimpleNamespace(
        type="tool_use",
        name="judge_claim",
        input={
            "verdict": "grounded",
            "citations": [],
            "rationale": "x",
            "confidence": 0.9,
        },
    )
    message = SimpleNamespace(content=[tool_block])
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    with pytest.raises(JudgeError):
        await judge_claim(
            client, model="claude-sonnet-5", claim_text="x", candidate_chunks=[], max_retries=0
        )
