from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import voyageai
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, HTTPException, Query

from . import pipeline, repository, schemas
from .config import Settings, get_settings
from .db import init_db, make_engine, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)

    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.anthropic_client = AsyncAnthropic(
        api_key=settings.anthropic_api_key, timeout=60.0, max_retries=0
    )
    app.state.voyage_client = voyageai.Client(
        api_key=settings.voyage_api_key, timeout=60.0, max_retries=3
    )
    yield


app = FastAPI(title="Evidence Audit Agent", lifespan=lifespan)


def get_app_settings() -> Settings:
    return app.state.settings


def get_anthropic_client() -> AsyncAnthropic:
    return app.state.anthropic_client


def get_voyage_client() -> voyageai.Client:
    return app.state.voyage_client


def get_session():
    session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def _to_audit_response(audit) -> schemas.AuditResponse:
    return schemas.AuditResponse(
        audit_id=audit.id,
        overall=schemas.AuditOverall(
            grounded_ratio=audit.grounded_ratio, claim_count=audit.claim_count
        ),
        claims=[
            schemas.ClaimResult(
                claim_text=c.claim_text, verdict=c.verdict, citations=c.citations, rationale=c.rationale
            )
            for c in audit.claims
        ],
        created_at=audit.created_at,
    )


@app.post("/audits", response_model=schemas.AuditResponse)
async def create_audit(
    request: schemas.AuditRequest,
    session=Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    anthropic_client: AsyncAnthropic = Depends(get_anthropic_client),
    voyage_client: voyageai.Client = Depends(get_voyage_client),
):
    chunk_dicts = [c.model_dump() for c in request.source_chunks]
    try:
        result = await pipeline.run_audit(
            anthropic_client=anthropic_client,
            voyage_client=voyage_client,
            settings=settings,
            response_text=request.response_text,
            source_chunks=chunk_dicts,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="upstream LLM/embedding provider error"
        ) from exc
    audit = repository.save_audit(
        session,
        response_text=request.response_text,
        metadata=request.metadata,
        grounded_ratio=result["grounded_ratio"],
        claims=result["claims"],
        source_chunks=[{"chunk_id": c["id"], "chunk_text": c["text"]} for c in chunk_dicts],
    )
    return _to_audit_response(audit)


@app.get("/audits/{audit_id}", response_model=schemas.AuditResponse)
async def get_audit(audit_id: str, session=Depends(get_session)):
    audit = repository.get_audit(session, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return _to_audit_response(audit)


@app.get("/audits", response_model=list[schemas.AuditResponse])
async def list_audits(
    source_system: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    session=Depends(get_session),
):
    audits = repository.list_audits(
        session,
        source_system=source_system,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )
    return [_to_audit_response(a) for a in audits]
