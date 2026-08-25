# Evidence Audit & Verification Judgment Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service that audits whether an LLM-generated response is grounded in a set of provided source chunks, judging each claim individually with Claude and citing the chunks that support it.

**Architecture:** A synchronous FastAPI endpoint orchestrates a pipeline: extract claims from the response (Claude tool-use call), embed the request's source chunks and claims (Voyage AI), retrieve the top-N most similar candidate chunks per claim (in-memory cosine similarity — no persistent vector store), judge each claim against its candidates (Claude tool-use call, run concurrently with a semaphore), then persist the audit and its per-claim verdicts to a relational DB (SQLite for dev/test, Postgres-compatible via `DATABASE_URL`).

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, `anthropic` SDK (`AsyncAnthropic`), `voyageai` SDK, NumPy, pytest + pytest-asyncio (`asyncio_mode = auto`), FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-08-18-evidence-audit-agent-design.md`

## Global Constraints

- Verdict values are exactly: `grounded`, `not_grounded`, `partially_grounded`, `judgment_failed` (spec §4, §6).
- Default `top_n_candidates` = 8 (spec §3).
- Default `judge_concurrency` (semaphore limit on parallel judge calls) = 5 (spec §3).
- Judge LLM call retries: up to 2 retries (3 attempts total) with exponential backoff before marking a claim `judgment_failed` (spec §6).
- DB tables: `audits`, `audit_claims`, `audit_source_chunks` (spec §5) — source chunks are snapshotted per audit, not deduplicated globally.
- API surface: `POST /audits`, `GET /audits/{audit_id}`, `GET /audits?source_system=&limit=` (spec §4).
- Empty `source_chunks`: skip the judge LLM call entirely, mark every extracted claim `not_grounded` (spec §6).
- Zero claims extracted: return `claims: []`, `grounded_ratio: null` (spec §6).
- Golden regression suite makes real API calls and must be excluded from the default `pytest` run (spec §7) — implemented via a `golden` pytest marker and `addopts = "-m 'not golden'"`.

---

### Task 1: Project scaffold & configuration

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (frozen dataclass with fields `anthropic_api_key: str`, `voyage_api_key: str`, `database_url: str`, `claim_extract_model: str = "claude-sonnet-5"`, `claim_judge_model: str = "claude-sonnet-5"`, `embedding_model: str = "voyage-3"`, `top_n_candidates: int = 8`, `judge_concurrency: int = 5`); `app.config.get_settings() -> Settings`.

- [ ] **Step 1: Scaffold the project files**

`pyproject.toml`:

```toml
[project]
name = "evidence-audit-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "pydantic>=2.7",
    "anthropic>=0.34",
    "voyageai>=0.3",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["golden: real-API regression suite, excluded from default run"]
addopts = "-m 'not golden'"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]
```

`app/__init__.py`: empty file.

`tests/__init__.py`: empty file.

`tests/conftest.py`:

```python
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("VOYAGE_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
```

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:

```python
from app.config import get_settings


def test_get_settings_reads_required_env_and_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-456")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.anthropic_api_key == "ak-123"
    assert settings.voyage_api_key == "vk-456"
    assert settings.database_url == "sqlite:///./audit.db"
    assert settings.claim_extract_model == "claude-sonnet-5"
    assert settings.claim_judge_model == "claude-sonnet-5"
    assert settings.embedding_model == "voyage-3"
    assert settings.top_n_candidates == 8
    assert settings.judge_concurrency == 5


def test_get_settings_reads_database_url_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")

    settings = get_settings()

    assert settings.database_url == "postgresql://x/y"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -e ".[dev]"` then `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: Write minimal implementation**

`app/config.py`:

```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    voyage_api_key: str
    database_url: str
    claim_extract_model: str = "claude-sonnet-5"
    claim_judge_model: str = "claude-sonnet-5"
    embedding_model: str = "voyage-3"
    top_n_candidates: int = 8
    judge_concurrency: int = 5


def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./audit.db"),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/__init__.py app/config.py tests/__init__.py tests/conftest.py tests/test_config.py
git commit -m "feat: add project scaffold and settings loader"
```

---

### Task 2: DB models & engine setup

**Files:**
- Create: `app/models.py`
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `app.models.Base`, `app.models.Audit` (fields: `id`, `response_text`, `metadata_json` [maps to DB column `metadata`], `source_system`, `grounded_ratio`, `claim_count`, `created_at`, relationships `claims`, `source_chunks`), `app.models.AuditClaim` (fields: `id`, `audit_id`, `claim_text`, `verdict`, `citations`, `rationale`), `app.models.AuditSourceChunk` (fields: `id`, `audit_id`, `chunk_id`, `chunk_text`); `app.db.make_engine(database_url: str)`, `app.db.make_session_factory(engine)`, `app.db.init_db(engine)`.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:

```python
from app.db import init_db, make_engine, make_session_factory
from app import models


def _session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)()


def test_can_create_and_query_audit_with_relations():
    session = _session()

    audit = models.Audit(
        response_text="Paris is the capital of France.",
        metadata_json={"source_system": "test"},
        source_system="test",
        grounded_ratio=1.0,
        claim_count=1,
    )
    audit.claims.append(
        models.AuditClaim(
            claim_text="Paris is the capital of France.",
            verdict="grounded",
            citations=["c1"],
            rationale="matches chunk c1",
        )
    )
    audit.source_chunks.append(
        models.AuditSourceChunk(chunk_id="c1", chunk_text="Paris is the capital of France.")
    )
    session.add(audit)
    session.commit()

    fetched = session.get(models.Audit, audit.id)
    assert fetched.response_text == "Paris is the capital of France."
    assert fetched.source_system == "test"
    assert fetched.metadata_json == {"source_system": "test"}
    assert len(fetched.claims) == 1
    assert fetched.claims[0].verdict == "grounded"
    assert fetched.claims[0].citations == ["c1"]
    assert len(fetched.source_chunks) == 1
    assert fetched.source_chunks[0].chunk_id == "c1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

`app/models.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    response_text: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    source_system: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    grounded_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    claims: Mapped[list["AuditClaim"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    source_chunks: Mapped[list["AuditSourceChunk"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )


class AuditClaim(Base):
    __tablename__ = "audit_claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id"))
    claim_text: Mapped[str] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(String)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(String, default="")

    audit: Mapped["Audit"] = relationship(back_populates="claims")


class AuditSourceChunk(Base):
    __tablename__ = "audit_source_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id"))
    chunk_id: Mapped[str] = mapped_column(String)
    chunk_text: Mapped[str] = mapped_column(String)

    audit: Mapped["Audit"] = relationship(back_populates="source_chunks")
```

`app/db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/db.py tests/test_db.py
git commit -m "feat: add SQLAlchemy models and DB engine setup"
```

---

### Task 3: Pydantic request/response schemas

**Files:**
- Create: `app/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `app.schemas.Verdict` (Literal type), `app.schemas.SourceChunk(id, text)`, `app.schemas.AuditRequest(response_text, source_chunks=[], metadata={})`, `app.schemas.ClaimResult(claim_text, verdict, citations=[], rationale="")`, `app.schemas.AuditOverall(grounded_ratio, claim_count)`, `app.schemas.AuditResponse(audit_id, overall, claims, created_at)`.

- [ ] **Step 1: Write the failing test**

`tests/test_schemas.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas'`

- [ ] **Step 3: Write minimal implementation**

`app/schemas.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py tests/test_schemas.py
git commit -m "feat: add Pydantic request/response schemas"
```

---

### Task 4: Repository (persistence layer)

**Files:**
- Create: `app/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `app.db.make_engine`, `make_session_factory`, `init_db` (Task 2); `app.models.Audit/AuditClaim/AuditSourceChunk` (Task 2).
- Produces: `app.repository.save_audit(session, *, response_text: str, metadata: dict, grounded_ratio: float | None, claims: list[dict], source_chunks: list[dict]) -> models.Audit` (each `claims` dict has keys `claim_text, verdict, citations, rationale`; each `source_chunks` dict has keys `chunk_id, chunk_text`); `app.repository.get_audit(session, audit_id: str) -> models.Audit | None`; `app.repository.list_audits(session, *, source_system: str | None = None, created_from: datetime | None = None, created_to: datetime | None = None, limit: int = 50) -> list[models.Audit]`.

- [ ] **Step 1: Write the failing test**

`tests/test_repository.py`:

```python
from datetime import datetime, timedelta, timezone

from app.db import init_db, make_engine, make_session_factory
from app import repository


def _session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)()


def test_save_and_get_audit_round_trip():
    session = _session()
    audit = repository.save_audit(
        session,
        response_text="Paris is the capital of France.",
        metadata={"source_system": "chatbot-x"},
        grounded_ratio=1.0,
        claims=[
            {
                "claim_text": "Paris is the capital of France.",
                "verdict": "grounded",
                "citations": ["c1"],
                "rationale": "matches c1",
            }
        ],
        source_chunks=[{"chunk_id": "c1", "chunk_text": "Paris is the capital of France."}],
    )

    fetched = repository.get_audit(session, audit.id)
    assert fetched.response_text == "Paris is the capital of France."
    assert fetched.grounded_ratio == 1.0
    assert fetched.claim_count == 1
    assert fetched.claims[0].verdict == "grounded"
    assert fetched.source_chunks[0].chunk_id == "c1"


def test_get_audit_returns_none_when_missing():
    session = _session()
    assert repository.get_audit(session, "does-not-exist") is None


def test_list_audits_filters_by_source_system_and_date():
    session = _session()
    repository.save_audit(
        session, response_text="a", metadata={"source_system": "sys-a"},
        grounded_ratio=1.0, claims=[], source_chunks=[],
    )
    repository.save_audit(
        session, response_text="b", metadata={"source_system": "sys-b"},
        grounded_ratio=1.0, claims=[], source_chunks=[],
    )

    results = repository.list_audits(session, source_system="sys-a")
    assert len(results) == 1
    assert results[0].response_text == "a"

    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert repository.list_audits(session, created_from=future) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.repository'`

- [ ] **Step 3: Write minimal implementation**

`app/repository.py`:

```python
from datetime import datetime

from sqlalchemy.orm import Session

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
    audit.claims = [models.AuditClaim(**c) for c in claims]
    audit.source_chunks = [models.AuditSourceChunk(**c) for c in source_chunks]
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
    query = session.query(models.Audit)
    if source_system:
        query = query.filter(models.Audit.source_system == source_system)
    if created_from:
        query = query.filter(models.Audit.created_at >= created_from)
    if created_to:
        query = query.filter(models.Audit.created_at <= created_to)
    return query.order_by(models.Audit.created_at.desc()).limit(limit).all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repository.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/repository.py tests/test_repository.py
git commit -m "feat: add audit persistence repository"
```

---

### Task 5: Claim extractor

**Files:**
- Create: `app/claim_extractor.py`
- Test: `tests/test_claim_extractor.py`

**Interfaces:**
- Consumes: nothing from prior tasks (takes any object exposing `.messages.create(...)` — an `anthropic.AsyncAnthropic` client in production).
- Produces: `app.claim_extractor.extract_claims(client, *, model: str, response_text: str) -> list[str]`.

- [ ] **Step 1: Write the failing test**

`tests/test_claim_extractor.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.claim_extractor import extract_claims


async def test_extract_claims_returns_claims_from_tool_use_block():
    tool_block = SimpleNamespace(
        type="tool_use",
        name="extract_claims",
        input={"claims": ["Paris is the capital of France.", "France is in Europe."]},
    )
    message = SimpleNamespace(content=[tool_block])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))

    claims = await extract_claims(
        client, model="claude-sonnet-5",
        response_text="Paris is the capital of France. France is in Europe.",
    )

    assert claims == ["Paris is the capital of France.", "France is in Europe."]
    client.messages.create.assert_awaited_once()


async def test_extract_claims_returns_empty_list_when_no_tool_use_block():
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="no claims")])
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))

    claims = await extract_claims(client, model="claude-sonnet-5", response_text="hi")

    assert claims == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_claim_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.claim_extractor'`

- [ ] **Step 3: Write minimal implementation**

`app/claim_extractor.py`:

```python
EXTRACT_TOOL = {
    "name": "extract_claims",
    "description": "Extract discrete factual claims from the response text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of individual factual claims found in the text.",
            }
        },
        "required": ["claims"],
    },
}


async def extract_claims(client, *, model: str, response_text: str) -> list[str]:
    message = await client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_claims"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Break the following response into a list of discrete, independently "
                    "checkable factual claims. Do not include greetings or filler.\n\n"
                    f"Response:\n{response_text}"
                ),
            }
        ],
    )
    for block in message.content:
        if block.type == "tool_use" and block.name == "extract_claims":
            return list(block.input["claims"])
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_claim_extractor.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/claim_extractor.py tests/test_claim_extractor.py
git commit -m "feat: add LLM claim extractor"
```

---

### Task 6: Chunk/claim embedder

**Files:**
- Create: `app/embedder.py`
- Test: `tests/test_embedder.py`

**Interfaces:**
- Consumes: nothing from prior tasks (takes any object exposing `.embed(texts, model=...)` — a `voyageai.Client` in production).
- Produces: `app.embedder.embed_texts(client, *, model: str, texts: list[str]) -> list[list[float]]`.

- [ ] **Step 1: Write the failing test**

`tests/test_embedder.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.embedder import embed_texts


async def test_embed_texts_returns_embeddings_from_client():
    client = MagicMock()
    client.embed.return_value = SimpleNamespace(embeddings=[[0.1, 0.2], [0.3, 0.4]])

    result = await embed_texts(client, model="voyage-3", texts=["a", "b"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    client.embed.assert_called_once_with(["a", "b"], model="voyage-3")


async def test_embed_texts_returns_empty_list_for_no_texts():
    client = MagicMock()

    result = await embed_texts(client, model="voyage-3", texts=[])

    assert result == []
    client.embed.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.embedder'`

- [ ] **Step 3: Write minimal implementation**

`app/embedder.py`:

```python
import asyncio


async def embed_texts(client, *, model: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    result = await asyncio.to_thread(client.embed, texts, model=model)
    return result.embeddings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/embedder.py tests/test_embedder.py
git commit -m "feat: add Voyage AI embedding wrapper"
```

---

### Task 7: Retriever (embedding similarity candidate filter)

**Files:**
- Create: `app/retriever.py`
- Test: `tests/test_retriever.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure function over embedding vectors).
- Produces: `app.retriever.top_n_candidates(claim_embedding: list[float], chunk_embeddings: list[list[float]], chunk_ids: list[str], *, n: int) -> list[str]`.

- [ ] **Step 1: Write the failing test**

`tests/test_retriever.py`:

```python
from app.retriever import top_n_candidates


def test_top_n_candidates_orders_by_cosine_similarity():
    claim_embedding = [1.0, 0.0]
    chunk_embeddings = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    chunk_ids = ["exact-match", "orthogonal", "close-match"]

    result = top_n_candidates(claim_embedding, chunk_embeddings, chunk_ids, n=2)

    assert result == ["exact-match", "close-match"]


def test_top_n_candidates_returns_empty_for_no_chunks():
    assert top_n_candidates([1.0, 0.0], [], [], n=5) == []


def test_top_n_candidates_caps_at_n():
    claim_embedding = [1.0, 0.0]
    chunk_embeddings = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3]]
    chunk_ids = ["a", "b", "c", "d"]

    result = top_n_candidates(claim_embedding, chunk_embeddings, chunk_ids, n=2)

    assert result == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retriever.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retriever'`

- [ ] **Step 3: Write minimal implementation**

`app/retriever.py`:

```python
import numpy as np


def top_n_candidates(
    claim_embedding: list[float],
    chunk_embeddings: list[list[float]],
    chunk_ids: list[str],
    *,
    n: int,
) -> list[str]:
    if not chunk_embeddings:
        return []
    claim_vec = np.array(claim_embedding)
    chunk_matrix = np.array(chunk_embeddings)
    claim_norm = claim_vec / (np.linalg.norm(claim_vec) + 1e-10)
    chunk_norms = chunk_matrix / (np.linalg.norm(chunk_matrix, axis=1, keepdims=True) + 1e-10)
    similarities = chunk_norms @ claim_norm
    top_indices = np.argsort(-similarities)[:n]
    return [chunk_ids[i] for i in top_indices]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retriever.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/retriever.py tests/test_retriever.py
git commit -m "feat: add embedding-similarity candidate retriever"
```

---

### Task 8: Judge

**Files:**
- Create: `app/judge.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- Consumes: nothing from prior tasks (takes any object exposing `.messages.create(...)`).
- Produces: `app.judge.judge_claim(client, *, model: str, claim_text: str, candidate_chunks: list[dict], max_retries: int = 2) -> dict` (dict has keys `verdict, citations, rationale`); `app.judge.JudgeError` (Exception subclass).

- [ ] **Step 1: Write the failing test**

`tests/test_judge.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_judge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.judge'`

- [ ] **Step 3: Write minimal implementation**

`app/judge.py`:

```python
import asyncio

JUDGE_TOOL = {
    "name": "judge_claim",
    "description": "Judge whether a claim is grounded in the provided source chunks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["grounded", "not_grounded", "partially_grounded"],
            },
            "citations": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "citations", "rationale"],
    },
}


class JudgeError(Exception):
    pass


async def judge_claim(
    client,
    *,
    model: str,
    claim_text: str,
    candidate_chunks: list[dict],
    max_retries: int = 2,
) -> dict:
    chunks_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in candidate_chunks)
    prompt = (
        "Given the claim and candidate source chunks below, judge whether the claim is "
        "grounded in the chunks. Cite the chunk ids that support your verdict.\n\n"
        f"Claim: {claim_text}\n\nCandidate chunks:\n{chunks_block}"
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=512,
                tools=[JUDGE_TOOL],
                tool_choice={"type": "tool", "name": "judge_claim"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in message.content:
                if block.type == "tool_use" and block.name == "judge_claim":
                    return dict(block.input)
            raise JudgeError("no tool_use block in response")
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)
    raise JudgeError(f"judge_claim failed after {max_retries + 1} attempts") from last_error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_judge.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/judge.py tests/test_judge.py
git commit -m "feat: add LLM claim judge with retry"
```

---

### Task 9: Pipeline orchestration

**Files:**
- Create: `app/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `app.claim_extractor.extract_claims` (Task 5), `app.embedder.embed_texts` (Task 6), `app.retriever.top_n_candidates` (Task 7), `app.judge.judge_claim` / `app.judge.JudgeError` (Task 8).
- Produces: `app.pipeline.run_audit(*, anthropic_client, voyage_client, settings, response_text: str, source_chunks: list[dict]) -> dict` where `source_chunks` items have keys `id, text`, and the return value is `{"claims": list[dict], "grounded_ratio": float | None}` (each claim dict has keys `claim_text, verdict, citations, rationale`).

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`app/pipeline.py`:

```python
import asyncio

from . import claim_extractor, embedder, judge, retriever


async def run_audit(
    *,
    anthropic_client,
    voyage_client,
    settings,
    response_text: str,
    source_chunks: list[dict],
) -> dict:
    if not response_text.strip():
        return {"claims": [], "grounded_ratio": None}

    claims = await claim_extractor.extract_claims(
        anthropic_client, model=settings.claim_extract_model, response_text=response_text
    )
    if not claims:
        return {"claims": [], "grounded_ratio": None}

    if not source_chunks:
        return {
            "claims": [
                {
                    "claim_text": c,
                    "verdict": "not_grounded",
                    "citations": [],
                    "rationale": "no source chunks provided",
                }
                for c in claims
            ],
            "grounded_ratio": 0.0,
        }

    chunk_ids = [c["id"] for c in source_chunks]
    chunk_by_id = {c["id"]: c["text"] for c in source_chunks}

    chunk_embeddings = await embedder.embed_texts(
        voyage_client, model=settings.embedding_model, texts=[c["text"] for c in source_chunks]
    )
    claim_embeddings = await embedder.embed_texts(
        voyage_client, model=settings.embedding_model, texts=claims
    )

    semaphore = asyncio.Semaphore(settings.judge_concurrency)

    async def judge_one(claim_text: str, claim_embedding: list[float]) -> dict:
        candidate_ids = retriever.top_n_candidates(
            claim_embedding, chunk_embeddings, chunk_ids, n=settings.top_n_candidates
        )
        candidate_chunks = [{"id": cid, "text": chunk_by_id[cid]} for cid in candidate_ids]
        async with semaphore:
            try:
                result = await judge.judge_claim(
                    anthropic_client,
                    model=settings.claim_judge_model,
                    claim_text=claim_text,
                    candidate_chunks=candidate_chunks,
                )
                return {"claim_text": claim_text, **result}
            except judge.JudgeError:
                return {
                    "claim_text": claim_text,
                    "verdict": "judgment_failed",
                    "citations": [],
                    "rationale": "judge failed after retries",
                }

    results = await asyncio.gather(
        *(judge_one(c, e) for c, e in zip(claims, claim_embeddings))
    )

    gradeable = [r for r in results if r["verdict"] != "judgment_failed"]
    grounded = [r for r in gradeable if r["verdict"] == "grounded"]
    grounded_ratio = (len(grounded) / len(gradeable)) if gradeable else None

    return {"claims": results, "grounded_ratio": grounded_ratio}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: add audit pipeline orchestration"
```

---

### Task 10: FastAPI endpoints

**Files:**
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `app.config.Settings/get_settings` (Task 1), `app.db.make_engine/make_session_factory/init_db` (Task 2), `app.schemas.*` (Task 3), `app.repository.save_audit/get_audit/list_audits` (Task 4), `app.pipeline.run_audit` (Task 9).
- Produces: `app.main.app` (FastAPI instance), dependency provider functions `get_session`, `get_app_settings`, `get_anthropic_client`, `get_voyage_client` (overridable via `app.dependency_overrides` in tests).

- [ ] **Step 1: Write the failing test**

`tests/test_api.py`:

```python
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import init_db, make_engine, make_session_factory
from app.main import app, get_anthropic_client, get_app_settings, get_session, get_voyage_client


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
    app.dependency_overrides.clear()


def test_get_audit_returns_404_for_missing_id(monkeypatch):
    client = _client_with_mocks(monkeypatch, claims=[], grounded_ratio=None)

    response = client.get("/audits/does-not-exist")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_full_round_trip_create_then_get(monkeypatch):
    claims = [{"claim_text": "x", "verdict": "grounded", "citations": ["c1"], "rationale": "r"}]
    client = _client_with_mocks(monkeypatch, claims, grounded_ratio=1.0)

    created = client.post(
        "/audits", json={"response_text": "x", "source_chunks": [{"id": "c1", "text": "x"}]}
    ).json()
    fetched = client.get(f"/audits/{created['audit_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["audit_id"] == created["audit_id"]
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

`app/main.py`:

```python
from typing import Optional

import voyageai
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, HTTPException

from . import pipeline, repository, schemas
from .config import Settings, get_settings
from .db import init_db, make_engine, make_session_factory

app = FastAPI(title="Evidence Audit Agent")

_settings = get_settings()
_engine = make_engine(_settings.database_url)
init_db(_engine)
_SessionFactory = make_session_factory(_engine)
_anthropic_client = AsyncAnthropic(api_key=_settings.anthropic_api_key)
_voyage_client = voyageai.Client(api_key=_settings.voyage_api_key)


def get_app_settings() -> Settings:
    return _settings


def get_anthropic_client() -> AsyncAnthropic:
    return _anthropic_client


def get_voyage_client() -> voyageai.Client:
    return _voyage_client


def get_session():
    session = _SessionFactory()
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
    result = await pipeline.run_audit(
        anthropic_client=anthropic_client,
        voyage_client=voyage_client,
        settings=settings,
        response_text=request.response_text,
        source_chunks=chunk_dicts,
    )
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
    source_system: Optional[str] = None, limit: int = 50, session=Depends(get_session)
):
    audits = repository.list_audits(session, source_system=source_system, limit=limit)
    return [_to_audit_response(a) for a in audits]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: All tests pass (golden suite excluded by default `addopts`).

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: add FastAPI audit endpoints"
```

---

### Task 11: Golden regression suite

**Files:**
- Create: `tests/golden/__init__.py`
- Create: `tests/golden/cases.json`
- Create: `tests/golden/test_golden.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 1), `app.pipeline.run_audit` (Task 9).
- Produces: nothing consumed by other tasks — this is a standalone, manually-run regression suite.

- [ ] **Step 1: Create the golden cases fixture**

`tests/golden/__init__.py`: empty file.

`tests/golden/cases.json`:

```json
[
  {
    "name": "single_grounded_claim",
    "response_text": "The Eiffel Tower is located in Paris, France.",
    "source_chunks": [
      {
        "id": "c1",
        "text": "The Eiffel Tower is a wrought-iron lattice tower located in Paris, France, completed in 1889."
      }
    ],
    "expected_verdicts": ["grounded"]
  },
  {
    "name": "single_not_grounded_claim",
    "response_text": "The Eiffel Tower is located in Berlin, Germany.",
    "source_chunks": [
      {
        "id": "c1",
        "text": "The Eiffel Tower is a wrought-iron lattice tower located in Paris, France, completed in 1889."
      }
    ],
    "expected_verdicts": ["not_grounded"]
  }
]
```

- [ ] **Step 2: Write the golden test**

`tests/golden/test_golden.py`:

```python
import json
import os
from pathlib import Path

import pytest
import voyageai
from anthropic import AsyncAnthropic

from app import pipeline
from app.config import get_settings

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())

pytestmark = pytest.mark.golden


def _has_real_keys() -> bool:
    return (
        os.environ.get("ANTHROPIC_API_KEY", "test-key") != "test-key"
        and os.environ.get("VOYAGE_API_KEY", "test-key") != "test-key"
    )


@pytest.mark.skipif(
    not _has_real_keys(), reason="set real ANTHROPIC_API_KEY/VOYAGE_API_KEY to run the golden suite"
)
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_golden_case_matches_expected_verdicts(case):
    settings = get_settings()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    voyage_client = voyageai.Client(api_key=settings.voyage_api_key)

    result = await pipeline.run_audit(
        anthropic_client=anthropic_client,
        voyage_client=voyage_client,
        settings=settings,
        response_text=case["response_text"],
        source_chunks=case["source_chunks"],
    )

    actual_verdicts = [c["verdict"] for c in result["claims"]]
    assert actual_verdicts == case["expected_verdicts"]
```

- [ ] **Step 3: Verify the suite is skipped without real keys**

Run: `pytest -m golden -v`
Expected: 2 tests reported as SKIPPED with reason "set real ANTHROPIC_API_KEY/VOYAGE_API_KEY to run the golden suite"

- [ ] **Step 4: Verify the default suite still excludes golden tests**

Run: `pytest -v`
Expected: no `test_golden_case_matches_expected_verdicts` entries appear in the output; all other tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/golden/__init__.py tests/golden/cases.json tests/golden/test_golden.py
git commit -m "test: add golden regression suite for judge quality"
```

---

## Manual verification (after Task 10)

Once Task 10 is complete, confirm the service runs end-to-end with real credentials:

```bash
export ANTHROPIC_API_KEY=<real key>
export VOYAGE_API_KEY=<real key>
uvicorn app.main:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/audits \
  -H "Content-Type: application/json" \
  -d '{"response_text": "The Eiffel Tower is in Paris.", "source_chunks": [{"id": "c1", "text": "The Eiffel Tower is located in Paris, France."}]}'
```

Confirm the response has `claims[0].verdict == "grounded"` and `claims[0].citations == ["c1"]`, then `curl http://127.0.0.1:8000/audits/<audit_id>` returns the same result.
