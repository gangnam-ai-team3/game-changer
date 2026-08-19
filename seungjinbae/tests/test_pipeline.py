from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import pipeline


def _settings(**overrides):
    defaults = dict(
        claim_extract_model="claude-sonnet-5",
        claim_judge_model="claude-sonnet-5",
        embedding_model="voyage-3",
        top_n_candidates=8,
        judge_concurrency=5,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_run_audit_returns_empty_for_blank_response():
    result = await pipeline.run_audit(
        anthropic_client=None, voyage_client=None, settings=_settings(),
        response_text="   ", source_chunks=[],
    )
    assert result == {"claims": [], "grounded_ratio": None}


async def test_run_audit_returns_empty_when_no_claims_extracted(monkeypatch):
    monkeypatch.setattr(pipeline.claim_extractor, "extract_claims", AsyncMock(return_value=[]))

    result = await pipeline.run_audit(
        anthropic_client=None, voyage_client=None, settings=_settings(),
        response_text="hi there", source_chunks=[{"id": "c1", "text": "..."}],
    )

    assert result == {"claims": [], "grounded_ratio": None}


async def test_run_audit_marks_all_not_grounded_when_no_source_chunks(monkeypatch):
    monkeypatch.setattr(
        pipeline.claim_extractor, "extract_claims",
        AsyncMock(return_value=["Paris is the capital of France."]),
    )

    result = await pipeline.run_audit(
        anthropic_client=None, voyage_client=None, settings=_settings(),
        response_text="Paris is the capital of France.", source_chunks=[],
    )

    assert result["grounded_ratio"] == 0.0
    assert result["claims"][0]["verdict"] == "not_grounded"


async def test_run_audit_judges_each_claim_and_aggregates_ratio(monkeypatch):
    monkeypatch.setattr(
        pipeline.claim_extractor, "extract_claims",
        AsyncMock(return_value=["claim-a", "claim-b"]),
    )
    monkeypatch.setattr(
        pipeline.embedder, "embed_texts",
        AsyncMock(side_effect=[[[1.0, 0.0]], [[1.0, 0.0], [0.0, 1.0]]]),
    )
    monkeypatch.setattr(
        pipeline.judge, "judge_claim",
        AsyncMock(side_effect=[
            {"verdict": "grounded", "citations": ["c1"], "rationale": "matches"},
            {"verdict": "not_grounded", "citations": [], "rationale": "no match"},
        ]),
    )

    result = await pipeline.run_audit(
        anthropic_client=None, voyage_client=None, settings=_settings(),
        response_text="claim-a claim-b", source_chunks=[{"id": "c1", "text": "..."}],
    )

    assert result["grounded_ratio"] == 0.5
    assert len(result["claims"]) == 2


async def test_run_audit_degrades_to_judgment_failed_on_malformed_judge_output(monkeypatch):
    """End-to-end through the real judge.judge_claim (not mocked out): a judge tool_use
    response with an out-of-enum verdict must degrade the claim to judgment_failed rather
    than crashing run_audit's asyncio.gather with an unhandled exception."""
    monkeypatch.setattr("app.judge.asyncio.sleep", AsyncMock())
    monkeypatch.setattr(
        pipeline.claim_extractor, "extract_claims", AsyncMock(return_value=["claim-a"])
    )
    monkeypatch.setattr(
        pipeline.embedder, "embed_texts", AsyncMock(side_effect=[[[1.0, 0.0]], [[1.0, 0.0]]])
    )

    tool_block = SimpleNamespace(
        type="tool_use",
        name="judge_claim",
        input={"verdict": "not_a_real_verdict", "citations": [], "rationale": "bad"},
    )
    message = SimpleNamespace(content=[tool_block])
    fake_anthropic_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=message))
    )

    result = await pipeline.run_audit(
        anthropic_client=fake_anthropic_client, voyage_client=None, settings=_settings(),
        response_text="claim-a", source_chunks=[{"id": "c1", "text": "..."}],
    )

    assert result["claims"][0]["verdict"] == "judgment_failed"
    assert result["grounded_ratio"] is None


async def test_run_audit_excludes_judgment_failed_claims_from_ratio(monkeypatch):
    monkeypatch.setattr(
        pipeline.claim_extractor, "extract_claims", AsyncMock(return_value=["claim-a"])
    )
    monkeypatch.setattr(
        pipeline.embedder, "embed_texts",
        AsyncMock(side_effect=[[[1.0, 0.0]], [[1.0, 0.0]]]),
    )
    monkeypatch.setattr(
        pipeline.judge, "judge_claim", AsyncMock(side_effect=pipeline.judge.JudgeError("boom"))
    )

    result = await pipeline.run_audit(
        anthropic_client=None, voyage_client=None, settings=_settings(),
        response_text="claim-a", source_chunks=[{"id": "c1", "text": "..."}],
    )

    assert result["claims"][0]["verdict"] == "judgment_failed"
    assert result["grounded_ratio"] is None
