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
