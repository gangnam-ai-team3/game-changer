from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts import ArtifactStatus, EventBrief, Producer
from res.corpus import (
    BehaviorCode,
    CorpusBuildError,
    EphemeralSteamReview,
    PUBLIC_DEMO_CLASSIFIER,
    PUBLIC_DEMO_CORPUS_VERSION,
    Quality,
    ReasonCode,
    ReviewLabel,
    Stance,
    TAXONOMY_VERSION,
    TopicTag,
    _summary,
    build_corpus,
    build_public_demo_corpus,
)
from res.corpus_collectors import EventCorpusCollector, UpdateCorpusCollector
from update_review.fixtures import load_dragunov_brief


SNAPSHOT = datetime(2026, 8, 19, 11, 41, 41, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures/corpus/pubg_steam_demo.sqlite3"
TABLES = {
    "manifest",
    "evidence",
    "evidence_fts",
    "evidence_fts_config",
    "evidence_fts_content",
    "evidence_fts_data",
    "evidence_fts_docsize",
    "evidence_fts_idx",
}
EVIDENCE_COLUMNS = (
    "evidence_id",
    "app_id",
    "language",
    "created_at",
    "updated_at",
    "stance",
    "summary",
    "reason_codes",
    "behavior_codes",
    "topic_tags",
    "confidence",
    "classifier",
    "taxonomy_version",
)


def _source_reviews(language: str):
    for index in range(500):
        observed_at = SNAPSHOT - timedelta(minutes=index + 1)
        yield EphemeralSteamReview(
            evidence_id=hashlib.sha256(
                f"old-source-{language}-{index}".encode()
            ).hexdigest()[:24],
            language=language,
            created_at=observed_at,
            updated_at=observed_at,
            text="temporary Dragunov weapon damage balance review",
        )


def _classify(reviews):
    return [
        ReviewLabel(
            item_id=review.evidence_id,
            quality=Quality.USABLE,
            stance=(Stance.POSITIVE if index % 3 == 0 else Stance.MIXED),
            reason_codes=[ReasonCode.BALANCE, ReasonCode.PREDICTABILITY],
            behavior_codes=[BehaviorCode.WAIT_AND_SEE],
            topic_tags=[TopicTag.WEAPON_BALANCE, TopicTag.CORE_GAMEPLAY],
            confidence=0.9,
        )
        for index, review in enumerate(reviews)
    ]


def _content_hash(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute(
        "SELECT * FROM evidence ORDER BY language, evidence_id"
    ):
        digest.update(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()
        )
    return digest.hexdigest()


def _make_source(path: Path) -> tuple[set[str], set[str]]:
    build_corpus(
        path,
        target_per_language=500,
        batch_size=100,
        fetch_reviews=lambda **kwargs: _source_reviews(kwargs["language"]),
        classify=_classify,
        classifier_name="unsafe-source-classifier",
        snapshot_at=SNAPSHOT,
    )
    connection = sqlite3.connect(path)
    old_ids = {row[0] for row in connection.execute("SELECT evidence_id FROM evidence")}
    old_times = {
        value
        for row in connection.execute("SELECT created_at, updated_at FROM evidence")
        for value in row
    }
    unsafe_summary = (
        "RAW review https://example.com person@example.com @player "
        "recommendationid steamid 76561198000000000"
    )
    connection.execute(
        "UPDATE evidence SET summary = ?, classifier = ?",
        (unsafe_summary, "unsafe-review-classifier"),
    )
    connection.execute("DELETE FROM evidence_fts")
    connection.execute(
        """
        INSERT INTO evidence_fts (evidence_id, search_text)
        SELECT evidence_id, summary || ' ' || reason_codes || ' ' ||
               behavior_codes || ' ' || topic_tags
        FROM evidence
        """
    )
    connection.execute(
        "UPDATE manifest SET value = ? WHERE key = 'content_hash'",
        (_content_hash(connection),),
    )
    connection.commit()
    connection.close()
    return old_ids, old_times


def _event() -> EventBrief:
    cutoff = SNAPSHOT + timedelta(days=1)
    return EventBrief(
        run_id="public-demo-event",
        producer=Producer.USER,
        game="PUBG: BATTLEGROUNDS",
        event_name="Dragunov weapon damage balance",
        goal="무기 피해와 밸런스 반응을 출시 전에 확인한다.",
        starts_at=cutoff + timedelta(days=1),
        ends_at=cutoff + timedelta(days=8),
        target_users=["PUBG 이용자"],
        participation_rule="게임 플레이",
        repeat_rule="제한 없음",
        rewards=["없음"],
        currencies=["없음"],
        probability_guarantee="확률 보상 없음",
        monetization_policy="추가 결제 없음",
        expiration_policy="만료 없음",
        cutoff_at=cutoff,
    )


def _audit_public_corpus(path: Path) -> tuple[set[str], set[str]]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        manifest = dict(connection.execute("SELECT key, value FROM manifest"))
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(evidence)")
        )
        rows = connection.execute(
            """
            SELECT evidence_id, language, created_at, updated_at, stance, summary,
                   reason_codes, behavior_codes, topic_tags, confidence,
                   classifier, taxonomy_version
            FROM evidence
            """
        ).fetchall()
        fts_rows = dict(
            connection.execute("SELECT evidence_id, search_text FROM evidence_fts")
        )
        ids = {row[0] for row in rows}
        times = {value for row in rows for value in row[2:4]}

        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0
        assert tables == TABLES
        assert columns == EVIDENCE_COLUMNS
        assert len(rows) == len(ids) == 1000
        assert re.fullmatch(r"[0-9a-f]{24}", next(iter(ids)))
        assert all(re.fullmatch(r"[0-9a-f]{24}", evidence_id) for evidence_id in ids)
        assert times == {manifest["snapshot_at"]}
        assert manifest["status"] == "active"
        assert manifest["app_id"] == "578080"
        assert manifest["ko_count"] == manifest["en_count"] == "500"
        assert manifest["classifier"] == PUBLIC_DEMO_CLASSIFIER
        assert manifest["corpus_version"] == PUBLIC_DEMO_CORPUS_VERSION
        assert manifest["taxonomy_version"] == TAXONOMY_VERSION
        assert manifest["content_hash"] == _content_hash(connection)
        assert (
            connection.execute("SELECT COUNT(*) FROM evidence_fts").fetchone()[0]
            == 1000
        )
        assert connection.execute(
            """
            SELECT COUNT(*) FROM evidence_fts AS f
            LEFT JOIN evidence AS e ON e.evidence_id = f.evidence_id
            WHERE e.evidence_id IS NULL
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM evidence AS e
            LEFT JOIN evidence_fts AS f ON f.evidence_id = e.evidence_id
            WHERE f.evidence_id IS NULL
            """
        ).fetchone()[0] == 0

        for row in rows:
            label = ReviewLabel(
                item_id=row[0],
                quality=Quality.USABLE,
                stance=row[4],
                reason_codes=json.loads(row[6]),
                behavior_codes=json.loads(row[7]),
                topic_tags=json.loads(row[8]),
                confidence=row[9],
            )
            assert row[5] == _summary(label)
            assert row[10] == PUBLIC_DEMO_CLASSIFIER
            assert row[11] == TAXONOMY_VERSION
            codes = " ".join(
                [*json.loads(row[6]), *json.loads(row[7]), *json.loads(row[8])]
            )
            assert fts_rows[row[0]] == f"{row[5]} {codes}"
    finally:
        connection.close()

    payload = path.read_bytes()
    printable = b"\n".join(re.findall(rb"[ -~]{4,}", payload)).lower()
    for marker in (
        b"raw",
        b"review",
        b"recommendationid",
        b"steamid",
        b"http://",
        b"https://",
        b"www.",
    ):
        assert marker not in printable
    assert not re.search(rb"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", printable)
    assert not re.search(rb"(?<![a-z0-9_])@[a-z0-9_]{2,32}\b", printable)
    assert not re.search(
        rb"(?<![0-9A-Za-z])\d{12,20}(?![0-9A-Za-z])", printable
    )
    return ids, times


def _assert_collectors(path: Path) -> None:
    event_feedback = EventCorpusCollector(path).run(_event())
    update = load_dragunov_brief("public-demo-update").model_copy(
        update={
            "cutoff_at": SNAPSHOT + timedelta(days=1),
            "planned_at": SNAPSHOT + timedelta(days=2),
        }
    )
    update_feedback = UpdateCorpusCollector(path).run(update)
    assert event_feedback.status is ArtifactStatus.COMPLETE
    assert update_feedback.status is ArtifactStatus.COMPLETE
    assert len(event_feedback.evidence) == len(update_feedback.evidence) == 40


def test_build_public_demo_corpus_discards_source_identifiers_and_raw_fields(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "demo.sqlite3"
    old_ids, old_times = _make_source(source)

    manifest = build_public_demo_corpus(source, target)
    ids, times = _audit_public_corpus(target)

    assert manifest["corpus_version"] == PUBLIC_DEMO_CORPUS_VERSION
    assert ids.isdisjoint(old_ids)
    assert times.isdisjoint(old_times)
    target_bytes = target.read_bytes()
    assert all(old_id.encode() not in target_bytes for old_id in old_ids)
    assert all(old_time.encode() not in target_bytes for old_time in old_times)

    _assert_collectors(target)


def test_public_demo_build_fails_closed_and_preserves_existing_target(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "demo.sqlite3"
    _make_source(source)
    target.write_bytes(b"existing-demo")

    connection = sqlite3.connect(source)
    connection.execute("UPDATE manifest SET value = 'staging' WHERE key = 'status'")
    connection.commit()
    connection.close()
    stage = target.with_name(f"{target.name}.staging")
    stage.write_bytes(b"abandoned-staging")

    with pytest.raises(CorpusBuildError, match="manifest"):
        build_public_demo_corpus(source, target)
    assert target.read_bytes() == b"existing-demo"
    assert not stage.exists()

    with pytest.raises(CorpusBuildError, match="같을 수 없습니다"):
        build_public_demo_corpus(target, target)


def test_stale_source_hash_preserves_existing_target(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "demo.sqlite3"
    _make_source(source)
    target.write_bytes(b"existing-demo")

    connection = sqlite3.connect(source)
    connection.execute(
        "UPDATE evidence SET confidence = 0.1 WHERE evidence_id = "
        "(SELECT evidence_id FROM evidence LIMIT 1)"
    )
    connection.commit()
    connection.close()

    with pytest.raises(CorpusBuildError, match="해시"):
        build_public_demo_corpus(source, target)
    assert target.read_bytes() == b"existing-demo"
    assert not target.with_name(f"{target.name}.staging").exists()


def test_public_demo_source_schema_and_key_alias_are_rejected(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "demo.sqlite3"
    _make_source(source)
    connection = sqlite3.connect(source)
    connection.execute("ALTER TABLE evidence ADD COLUMN raw_review TEXT")
    connection.commit()
    connection.close()

    with pytest.raises(CorpusBuildError, match="스키마"):
        build_public_demo_corpus(source, target)
    assert not target.exists()

    source.unlink()
    _make_source(source)
    key_path = target.with_name(f".{target.name}.evidence-key")
    os.link(source, key_path)
    with pytest.raises(CorpusBuildError, match="같을 수 없습니다"):
        build_public_demo_corpus(source, target)


def test_committed_public_demo_fixture_is_safe_and_complete():
    _audit_public_corpus(FIXTURE)
    _assert_collectors(FIXTURE)
    assert stat.S_IMODE(FIXTURE.stat().st_mode) == 0o644
