from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["grounded", "not_grounded", "partially_grounded", "judgment_failed"]


class SourceChunk(BaseModel):
    id: str
    text: str


class AuditRequest(BaseModel):
    response_text: str
    source_chunks: list[SourceChunk] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ClaimResult(BaseModel):
    claim_text: str
    verdict: Verdict
    citations: list[str] = Field(default_factory=list)
    rationale: str = ""


class AuditOverall(BaseModel):
    grounded_ratio: float | None
    claim_count: int


class AuditResponse(BaseModel):
    audit_id: str
    overall: AuditOverall
    claims: list[ClaimResult]
    created_at: datetime
