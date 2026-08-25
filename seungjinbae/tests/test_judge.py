from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.judge import JUDGE_MAX_TOKENS, JudgeError, judge_claim


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
    client.messages.create.assert_awaited_once()
    request = client.messages.create.await_args.kwargs
    assert request["max_tokens"] == JUDGE_MAX_TOKENS == 1024
    assert request["thinking"] == {"type": "disabled"}


async def test_judge_claim_returns_complete_twelve_citation_result_in_one_call():
    citations = [f"c{index}" for index in range(12)]
    result_body = {
        "verdict": "grounded",
        "citations": citations,
        "rationale": "열두 근거가 모두 주장과 연결됩니다.",
    }
    tool_block = SimpleNamespace(type="tool_use", name="judge_claim", input=result_body)
    message = SimpleNamespace(content=[tool_block])
    create = AsyncMock(return_value=message)
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    result = await judge_claim(
        client,
        model="claude-sonnet-5",
        claim_text="위험 판정은 열두 근거로 뒷받침됩니다.",
        candidate_chunks=[{"id": citation, "text": f"근거 {citation}"} for citation in citations],
    )

    assert result == result_body
    assert result["rationale"]
    assert create.await_count == 1


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
