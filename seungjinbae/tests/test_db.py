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
