import hashlib
from datetime import UTC, datetime, timedelta

import res.corpus_collectors as corpus_collectors
from agents.evidence_rag import EvidenceRagAgent
from contracts import ArtifactStatus, EventBrief, InputMode
from hy.corpus import (
    BehaviorCode,
    CorpusRecord,
    EphemeralSteamReview,
    Quality,
    ReasonCode,
    ReviewLabel,
    Stance,
    TopicTag,
    build_corpus,
)
from res.corpus_collectors import EventCorpusCollector, UpdateCorpusCollector
from update_review.evidence import UpdateEvidenceAgent
from update_review.fixtures import load_dragunov_brief


def _source_rows(language: str):
    observed_at = datetime(2026, 8, 18, tzinfo=UTC)
    rows = []
    for index in range(100):
        kind = "event" if index < 50 else "weapon"
        evidence_id = hashlib.sha256(f"{language}:{index}".encode()).hexdigest()[:24]
        rows.append(
            EphemeralSteamReview(
                evidence_id=evidence_id,
                language=language,
                created_at=observed_at,
                updated_at=observed_at,
                text=f"temporary {kind} raw review {index}",
            )
        )
    return rows


def _classify(reviews):
    labels = []
    for review in reviews:
        event = "event" in review.text
        labels.append(
            ReviewLabel(
                item_id=review.evidence_id,
                quality=Quality.USABLE,
                stance=Stance.NEGATIVE if event else Stance.MIXED,
                reason_codes=(
                    [ReasonCode.COST_VALUE, ReasonCode.PREDICTABILITY]
                    if event
                    else [ReasonCode.BALANCE, ReasonCode.PREDICTABILITY]
                ),
                behavior_codes=[BehaviorCode.WAIT_AND_SEE],
                topic_tags=(
                    [TopicTag.RANDOMNESS, TopicTag.REWARD_SYSTEM, TopicTag.MONETIZATION]
                    if event
                    else [TopicTag.WEAPON_BALANCE, TopicTag.CORE_GAMEPLAY]
                ),
                confidence=0.9,
            )
        )
    return labels


def _build_test_corpus(db_path):
    build_corpus(
        db_path,
        target_per_language=100,
        batch_size=100,
        fetch_reviews=lambda **kwargs: iter(_source_rows(kwargs["language"])),
        classify=_classify,
        classifier_name="codex-test",
        snapshot_at=datetime(2026, 8, 19, 12, tzinfo=UTC),
    )


def test_corpus_collectors_feed_existing_res_contracts(tmp_path, event):
    db_path = tmp_path / "pubg.sqlite3"
    _build_test_corpus(db_path)
    cutoff = datetime(2026, 8, 20, tzinfo=UTC)
    event = EventBrief.model_validate(
        event.model_dump()
        | {
            "event_name": "2단계 확률형 보상 이벤트",
            "goal": "상자 보상과 구매 비용을 명확하게 안내한다.",
            "probability_guarantee": "2단계 확률 상자와 목표 보상",
            "cutoff_at": cutoff,
            "starts_at": cutoff + timedelta(days=1),
            "ends_at": cutoff + timedelta(days=8),
        }
    )

    feedback = EventCorpusCollector(db_path).run(event)
    evidence = EvidenceRagAgent().run(feedback)

    assert feedback.status is ArtifactStatus.COMPLETE
    assert feedback.input_mode is InputMode.CORPUS
    assert len(feedback.evidence) == 40
    assert all(sample.sufficient for sample in feedback.samples)
    assert evidence.issues
    assert len(evidence.personas) == 4

    update = load_dragunov_brief("update-corpus").model_copy(
        update={
            "cutoff_at": cutoff,
            "planned_at": cutoff + timedelta(days=1),
        }
    )
    update_feedback = UpdateCorpusCollector(db_path).run(update)
    update_evidence = UpdateEvidenceAgent().run(update_feedback)

    assert update_feedback.status is ArtifactStatus.COMPLETE
    assert update_feedback.input_mode is InputMode.CORPUS
    assert len(update_feedback.evidence) == 40
    assert all(sample.sufficient for sample in update_feedback.samples)
    assert update_evidence.split_conditions


def test_corpus_newer_than_cutoff_fails_closed(tmp_path, event):
    db_path = tmp_path / "pubg.sqlite3"
    _build_test_corpus(db_path)

    feedback = EventCorpusCollector(db_path).run(event)

    assert feedback.status is ArtifactStatus.FAILED
    assert feedback.evidence == []
    assert feedback.input_mode is InputMode.CORPUS


def test_relevance_rank_restarts_for_each_language_when_korean_has_fewer_than_20(
    monkeypatch, tmp_path, event
):
    observed_at = event.cutoff_at - timedelta(days=1)

    def records(language: str, count: int):
        return [
            CorpusRecord(
                evidence_id=hashlib.sha256(f"{language}:{index}".encode()).hexdigest()[:24],
                language=language,
                created_at=observed_at.isoformat(),
                updated_at=observed_at.isoformat(),
                stance="negative",
                summary="무기 밸런스에 대한 비식별 의견입니다.",
                reason_codes=("balance",),
                behavior_codes=("wait_and_see",),
                topic_tags=("weapon_balance",),
                confidence=0.9,
            )
            for index in range(count)
        ]

    rows = {"ko": records("ko", 5), "en": records("en", 20)}
    monkeypatch.setattr(
        corpus_collectors,
        "corpus_status",
        lambda _path: {
            "status": "active",
            "snapshot_at": (event.cutoff_at - timedelta(days=2)).isoformat(),
            "corpus_version": "test-corpus",
            "ko_count": "100",
            "en_count": "100",
        },
    )
    monkeypatch.setattr(
        corpus_collectors,
        "search_corpus",
        lambda _query, *, language, **_kwargs: rows[language],
    )

    feedback = EventCorpusCollector(tmp_path / "unused.sqlite3").run(event)
    relevance = {
        language: [
            item.relevance
            for item in feedback.evidence
            if item.language.value == language
        ]
        for language in ("ko", "en")
    }

    assert [len(relevance[language]) for language in ("ko", "en")] == [5, 20]
    assert relevance["ko"][0] == relevance["en"][0] == 0.9
    assert all(
        first >= second
        for values in relevance.values()
        for first, second in zip(values, values[1:])
    )
