from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from . import models


def save_audit(
    session: Session,
    *,
    response_text: str,
    metadata: dict,
    grounded_ratio: float | None,
    claims: list[dict],
    source_chunks: list[dict],
) -> models.Audit:
    audit = models.Audit(
        response_text=response_text,
        metadata_json=metadata,
        source_system=metadata.get("source_system"),
        grounded_ratio=grounded_ratio,
        claim_count=len(claims),
    )
    audit.claims = [
        models.AuditClaim(
            claim_text=c["claim_text"],
            verdict=c["verdict"],
            citations=c["citations"],
            rationale=c["rationale"],
        )
        for c in claims
    ]
    audit.source_chunks = [
        models.AuditSourceChunk(chunk_id=c["chunk_id"], chunk_text=c["chunk_text"])
        for c in source_chunks
    ]
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return audit


def get_audit(session: Session, audit_id: str) -> models.Audit | None:
    return session.get(models.Audit, audit_id)


def list_audits(
    session: Session,
    *,
    source_system: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
) -> list[models.Audit]:
    query = session.query(models.Audit).options(selectinload(models.Audit.claims))
    if source_system:
        query = query.filter(models.Audit.source_system == source_system)
    if created_from:
        query = query.filter(models.Audit.created_at >= created_from)
    if created_to:
        query = query.filter(models.Audit.created_at <= created_to)
    return query.order_by(models.Audit.created_at.desc()).limit(limit).all()
