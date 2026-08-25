import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from res.corpus import (
    BehaviorCode,
    CorpusBuildError,
    EphemeralSteamReview,
    Quality,
    ReasonCode,
    ReviewLabel,
    Stance,
    TopicTag,
    build_corpus,
    classify_with_codex,
    corpus_status,
    search_corpus,
)


def _review(evidence_id: str, language: str, text: str) -> EphemeralSteamReview:
    observed_at = datetime(2026, 8, 1, tzinfo=UTC)
    return EphemeralSteamReview(
        evidence_id=evidence_id,
        language=language,
        created_at=observed_at,
        updated_at=observed_at,
        text=text,
    )


def _labels(reviews: list[EphemeralSteamReview]) -> list[ReviewLabel]:
    return [
        ReviewLabel(
            item_id=review.evidence_id,
            quality=Quality.USABLE,
            stance=Stance.MIXED,
            reason_codes=[ReasonCode.BALANCE, ReasonCode.PREDICTABILITY],
            behavior_codes=[BehaviorCode.WAIT_AND_SEE],
            topic_tags=[TopicTag.WEAPON_BALANCE, TopicTag.CORE_GAMEPLAY],
            confidence=0.86,
        )
        for review in reviews
    ]


def test_codex_classification_uses_only_subscription_cli_environment(monkeypatch):
    review = _review("a" * 24, "ko", "user@example.com 무기 밸런스")
    for key in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "SLACK_TOKEN",
    ):
        monkeypatch.setenv(key, f"secret-{key}")
    allowed_keys = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
    }
    expected_env = {
        key: value for key, value in os.environ.items() if key in allowed_keys
    }

    def fake_run(args, **kwargs):
        schema_path = args[args.index("--output-schema") + 1]
        prompt = Path(__file__).parents[1].joinpath("res/corpus_prompt.md").read_text(
            encoding="utf-8"
        )
        assert args == [
            "/opt/codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--output-schema",
            schema_path,
            prompt,
        ]
        assert kwargs["env"] == expected_env
        assert "user@example.com" not in kwargs["input"]
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps({"items": [item.model_dump(mode="json") for item in _labels([review])]}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert classify_with_codex([review], codex_bin="/opt/codex") == _labels([review])


def test_build_activates_only_safe_derived_corpus_and_search_is_stable(tmp_path):
    db_path = tmp_path / "pubg.sqlite3"
    source = {
        "ko": [
            _review("a" * 24, "ko", "RAW-SENTINEL-한국어 user@example.com"),
            _review("b" * 24, "ko", "RAW-SENTINEL-한국어-2 https://private.test"),
        ],
        "en": [
            _review("c" * 24, "en", "RAW-SENTINEL-English @private_user"),
            _review("d" * 24, "en", "RAW-SENTINEL-English-2 76561198000000000"),
        ],
    }

    def fetch_reviews(**kwargs):
        return iter(source[kwargs["language"]])

    manifest = build_corpus(
        db_path,
        target_per_language=2,
        batch_size=2,
        fetch_reviews=fetch_reviews,
        classify=_labels,
        classifier_name="codex-test",
        snapshot_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    assert manifest["status"] == "active"
    assert manifest["ko_count"] == "2"
    assert manifest["en_count"] == "2"
    assert corpus_status(db_path)["content_hash"] == manifest["content_hash"]
    database_bytes = db_path.read_bytes()
    for forbidden in (
        b"RAW-SENTINEL",
        b"user@example.com",
        b"private.test",
        b"private_user",
        b"76561198000000000",
    ):
        assert forbidden not in database_bytes

    first = search_corpus("무기 피해", db_path=db_path, language="ko", limit=2)
    second = search_corpus("무기 피해", db_path=db_path, language="ko", limit=2)
    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    assert len(first) == 2
    assert all("주요 이유" in item.summary for item in first)


def test_search_cutoff_compares_equivalent_offsets_in_utc(tmp_path):
    db_path = tmp_path / "pubg.sqlite3"
    source = {
        language: [_review(character * 24, language, "weapon balance review")]
        for language, character in (("ko", "a"), ("en", "b"))
    }
    build_corpus(
        db_path,
        target_per_language=1,
        batch_size=1,
        fetch_reviews=lambda **kwargs: iter(source[kwargs["language"]]),
        classify=_labels,
        classifier_name="codex-test",
        snapshot_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    utc_cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    seoul_cutoff = datetime.fromisoformat("2026-08-01T09:00:00+09:00")

    assert search_corpus(
        "weapon balance", db_path=db_path, language="en", cutoff_at=utc_cutoff
    ) == []
    assert search_corpus(
        "weapon balance", db_path=db_path, language="en", cutoff_at=seoul_cutoff
    ) == []


def test_failed_rebuild_keeps_previous_active_corpus(tmp_path):
    db_path = tmp_path / "pubg.sqlite3"

    def complete_source(**kwargs):
        marker = "a" if kwargs["language"] == "ko" else "b"
        return iter([_review(marker * 24, kwargs["language"], "temporary raw")])

    build_corpus(
        db_path,
        target_per_language=1,
        batch_size=1,
        fetch_reviews=complete_source,
        classify=_labels,
        classifier_name="codex-test",
        snapshot_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    active_before = db_path.read_bytes()

    with pytest.raises(CorpusBuildError, match="모으지 못했습니다"):
        build_corpus(
            db_path,
            target_per_language=2,
            batch_size=1,
            fetch_reviews=lambda **_kwargs: iter(()),
            classify=_labels,
            classifier_name="codex-test",
            snapshot_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    assert db_path.read_bytes() == active_before


def test_resume_rejects_a_different_classifier_version(tmp_path):
    db_path = tmp_path / "pubg.sqlite3"
    with pytest.raises(CorpusBuildError, match="모으지 못했습니다"):
        build_corpus(
            db_path,
            target_per_language=1,
            fetch_reviews=lambda **_kwargs: iter(()),
            classify=_labels,
            classifier_name="codex-old",
            snapshot_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    with pytest.raises(CorpusBuildError, match="분류기"):
        build_corpus(
            db_path,
            target_per_language=1,
            resume=True,
            fetch_reviews=lambda **_kwargs: iter(()),
            classify=_labels,
            classifier_name="codex-new",
        )
