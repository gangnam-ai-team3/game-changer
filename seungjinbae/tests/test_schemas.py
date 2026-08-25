import pytest
from pydantic import ValidationError

from app.schemas import AuditOverall, AuditRequest, AuditResponse, ClaimResult, SourceChunk


def test_audit_request_defaults():
    req = AuditRequest(response_text="hello")
    assert req.source_chunks == []
    assert req.metadata == {}


def test_audit_request_with_chunks():
    req = AuditRequest(response_text="hello", source_chunks=[{"id": "c1", "text": "..."}])
    assert req.source_chunks[0] == SourceChunk(id="c1", text="...")


def test_claim_result_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        ClaimResult(claim_text="x", verdict="maybe", citations=[], rationale="")


def test_audit_response_roundtrip():
    resp = AuditResponse(
        audit_id="a1",
        overall=AuditOverall(grounded_ratio=0.5, claim_count=2),
        claims=[ClaimResult(claim_text="x", verdict="grounded", citations=["c1"], rationale="r")],
        created_at="2026-08-18T00:00:00Z",
    )
    data = resp.model_dump(mode="json")
    assert data["overall"]["grounded_ratio"] == 0.5
    assert AuditResponse.model_validate(data).audit_id == "a1"
