import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts import ArtifactStatus, EventBrief, InputMode, Producer
from res.corpus import (
    BehaviorCode,
    CorpusBuildError,
    Quality,
    ReasonCode,
    ReviewLabel,
    Stance,
    TopicTag,
    build_from_hy_db,
)
from res.corpus_collectors import EventCorpusCollector, UpdateCorpusCollector
from update_review.fixtures import load_dragunov_brief


SNAPSHOT = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _make_hy_db(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE reviews (
          recommendationid TEXT PRIMARY KEY,
          appid INTEGER NOT NULL,
          language TEXT NOT NULL,
          review TEXT,
          voted_up INTEGER,
          timestamp_created INTEGER NOT NULL,
          timestamp_updated INTEGER,
          steamid TEXT,
          playtime_forever_minutes INTEGER,
          collected_at INTEGER NOT NULL
        );
        CREATE TABLE collector_state (
          language TEXT PRIMARY KEY,
          done INTEGER NOT NULL,
          last_cursor TEXT,
          updated_at INTEGER,
          last_synced_at INTEGER,
          sync_boundary_id TEXT,
          last_run_had_errors INTEGER NOT NULL
        );
        """
    )
    collected_at = int(SNAPSHOT.timestamp() * 1000)
    observed_at = int((SNAPSHOT - timedelta(days=2)).timestamp())
    public_ids: list[str] = []
    rows = []
    for language in ("koreana", "english"):
        for index in range(101):
            public_id = f"public-{language}-{index:03d}"
            public_ids.append(public_id)
            text = (
                "RAW-shared Dragunov weapon damage balance review"
                if index == 0
                else f"RAW-{language}-{index:03d} Dragunov weapon damage balance review"
            )
            rows.append(
                (
                    public_id,
                    578080,
                    language,
                    text,
                    index % 2,
                    observed_at - index,
                    observed_at - index,
                    f"76561198000{index:06d}",
                    100 + index,
                    collected_at,
                )
            )
        duplicate_id = f"public-{language}-duplicate"
        public_ids.append(duplicate_id)
        rows.append(
            (
                duplicate_id,
                578080,
                language,
                "RAW-shared Dragunov weapon damage balance review",
                1,
                observed_at + 1,
                observed_at + 1,
                "76561198999999999",
                999,
                collected_at,
            )
        )
        later_id = f"public-{language}-later-sync"
        public_ids.append(later_id)
        rows.append(
            (
                later_id,
                578080,
                language,
                "LATER-SYNC anti-cheat review",
                0,
                observed_at + 10,
                observed_at + 10,
                "76561198888888888",
                10,
                collected_at + 1,
            )
        )
    connection.executemany(
        "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    connection.executemany(
        "INSERT INTO collector_state VALUES (?, 1, NULL, ?, ?, NULL, 0)",
        [
            (language, collected_at, collected_at)
            for language in ("koreana", "english")
        ],
    )
    connection.commit()
    connection.close()
    return public_ids


def _classify(reviews):
    return [
        ReviewLabel(
            item_id=review.evidence_id,
            quality=Quality.USABLE,
            stance=Stance.MIXED,
            reason_codes=(
                [ReasonCode.CHEATING_SECURITY]
                if "LATER-SYNC" in review.text
                else [ReasonCode.BALANCE, ReasonCode.PREDICTABILITY]
            ),
            behavior_codes=[BehaviorCode.WAIT_AND_SEE],
            topic_tags=(
                [TopicTag.ANTI_CHEAT]
                if "LATER-SYNC" in review.text
                else [TopicTag.WEAPON_BALANCE, TopicTag.CORE_GAMEPLAY]
            ),
            confidence=0.9,
        )
        for review in reviews
    ]


def _event() -> EventBrief:
    cutoff = SNAPSHOT + timedelta(days=1)
    return EventBrief(
        run_id="hy-res-event",
        producer=Producer.USER,
        game="PUBG: BATTLEGROUNDS",
        event_name="Dragunov weapon balance event",
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


def test_hy_raw_db_builds_safe_corpus_for_event_and_update(tmp_path):
    source = tmp_path / "steam-reviews.db"
    target = tmp_path / "pubg-corpus.sqlite3"
    public_ids = _make_hy_db(source)

    manifest = build_from_hy_db(
        source,
        target,
        target_per_language=101,
        batch_size=50,
        classify=_classify,
        classifier_name="codex-test",
    )

    assert manifest["snapshot_at"] == SNAPSHOT.isoformat()
    assert manifest["ko_count"] == manifest["en_count"] == "101"
    connection = sqlite3.connect(target)
    evidence_ids = {
        row[0] for row in connection.execute("SELECT evidence_id FROM evidence")
    }
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(evidence)")
    }
    stored_times = set(
        connection.execute("SELECT created_at, updated_at FROM evidence")
    )
    later_sync_count = connection.execute(
        "SELECT COUNT(*) FROM evidence WHERE topic_tags LIKE '%anti_cheat%'"
    ).fetchone()[0]
    connection.close()
    assert not {"review", "steamid", "recommendationid"} & columns
    assert evidence_ids.isdisjoint(public_ids)
    assert stored_times == {(SNAPSHOT.isoformat(), SNAPSHOT.isoformat())}
    assert later_sync_count == 0
    target_bytes = target.read_bytes()
    assert b"RAW-" not in target_bytes
    assert b"7656119" not in target_bytes
    assert b"public-koreana" not in target_bytes

    key_path = target.with_name(f".{target.name}.evidence-key")
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    build_from_hy_db(
        source,
        target,
        target_per_language=101,
        batch_size=50,
        classify=_classify,
        classifier_name="codex-test",
    )
    connection = sqlite3.connect(target)
    rebuilt_ids = {
        row[0] for row in connection.execute("SELECT evidence_id FROM evidence")
    }
    connection.close()
    assert rebuilt_ids == evidence_ids

    event_feedback = EventCorpusCollector(target).run(_event())
    update = load_dragunov_brief("hy-res-update").model_copy(
        update={
            "cutoff_at": SNAPSHOT + timedelta(days=1),
            "planned_at": SNAPSHOT + timedelta(days=2),
        }
    )
    update_feedback = UpdateCorpusCollector(target).run(update)

    assert event_feedback.status is ArtifactStatus.COMPLETE
    assert update_feedback.status is ArtifactStatus.COMPLETE
    assert event_feedback.input_mode is update_feedback.input_mode is InputMode.CORPUS
    assert len(event_feedback.evidence) == len(update_feedback.evidence) == 40


def test_invalid_hy_state_and_same_file_are_rejected_without_replacing_active(tmp_path):
    source = tmp_path / "steam-reviews.db"
    target = tmp_path / "pubg-corpus.sqlite3"
    _make_hy_db(source)
    build_from_hy_db(
        source,
        target,
        target_per_language=1,
        batch_size=1,
        classify=_classify,
        classifier_name="codex-test",
    )
    active = target.read_bytes()

    connection = sqlite3.connect(source)
    connection.execute(
        "UPDATE collector_state SET done = 0 WHERE language = 'koreana'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(CorpusBuildError, match="완료"):
        build_from_hy_db(
            source,
            target,
            target_per_language=1,
            classify=_classify,
            classifier_name="codex-test",
        )
    assert target.read_bytes() == active

    with pytest.raises(CorpusBuildError, match="같을 수 없습니다"):
        build_from_hy_db(
            source,
            source,
            target_per_language=1,
            classify=_classify,
            classifier_name="codex-test",
        )


def test_latest_sync_error_does_not_invalidate_completed_backfill(tmp_path):
    source = tmp_path / "steam-reviews.db"
    target = tmp_path / "pubg-corpus.sqlite3"
    _make_hy_db(source)
    connection = sqlite3.connect(source)
    connection.execute("UPDATE collector_state SET last_run_had_errors = 1")
    connection.commit()
    connection.close()

    manifest = build_from_hy_db(
        source,
        target,
        target_per_language=1,
        classify=_classify,
        classifier_name="codex-test",
    )

    assert manifest["status"] == "active"


def test_source_cannot_alias_target_staging_or_evidence_key(tmp_path):
    target = tmp_path / "pubg-corpus.sqlite3"
    stage = target.with_name(f"{target.name}.staging")
    source = tmp_path / "steam-reviews.db"
    _make_hy_db(source)
    os.link(source, stage)
    source_before = source.read_bytes()

    with pytest.raises(CorpusBuildError, match="같을 수 없습니다"):
        build_from_hy_db(
            source,
            target,
            target_per_language=1,
            classify=_classify,
            classifier_name="codex-test",
        )
    assert source.read_bytes() == source_before

    stage.unlink()
    key_source = target.with_name(f".{target.name}.evidence-key")
    _make_hy_db(key_source)
    key_source_before = key_source.read_bytes()
    with pytest.raises(CorpusBuildError, match="같을 수 없습니다"):
        build_from_hy_db(
            key_source,
            target,
            target_per_language=1,
            classify=_classify,
            classifier_name="codex-test",
        )
    assert key_source.read_bytes() == key_source_before


def test_hy_private_databases_and_keys_are_gitignored():
    ignored = Path(__file__).parents[1].joinpath(".gitignore").read_text()
    for value in (
        "hy/steam-reviews.db",
        "hy/steam-reviews.db-wal",
        "hy/steam-reviews.db-shm",
        "hy/steam-reviews.db-journal",
        "hy/steam-reviews.anon.db",
        "hy/.hash-salt",
        "hy/.evidence-key",
        "*.evidence-key",
    ):
        assert value in ignored


def test_hy_candidate_page_limit_must_be_positive(tmp_path):
    source = tmp_path / "steam-reviews.db"
    _make_hy_db(source)

    with pytest.raises(ValueError, match="max_pages"):
        build_from_hy_db(
            source,
            tmp_path / "pubg-corpus.sqlite3",
            target_per_language=1,
            max_pages=0,
            classify=_classify,
            classifier_name="codex-test",
        )
