from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from contracts import (
    ArtifactStatus,
    ErrorCode,
    EventBrief,
    EvidenceItem,
    FeedbackBundle,
    InputMode,
    Language,
    LanguageSample,
    PipelineError,
    Producer,
    RiskCategory,
    SearchRecord,
    SourceType,
)
from hy.corpus import CorpusBuildError, CorpusRecord, corpus_status, search_corpus
from update_review.contracts import (
    EvidencePeriod,
    Sentiment,
    UpdateBrief,
    UpdateEvidenceItem,
    UpdateFeedbackBundle,
)

CORPUS_LANGUAGES = {"ko": Language.KOREAN, "en": Language.ENGLISH}


class EventCorpusCollector:
    """Res-owned adapter: active Hy corpus -> existing FeedbackBundle."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def run(self, event: EventBrief, _options=None, on_event=None) -> FeedbackBundle:
        notify = on_event or (lambda _node, _message, _metrics: None)
        query = _event_query(event)
        try:
            manifest = _manifest_before_cutoff(self.db_path, event.cutoff_at)
            records = _search_languages(self.db_path, query, event.cutoff_at)
        except (CorpusBuildError, OSError, sqlite3.Error, ValueError) as exc:
            return _failed_event_bundle(event, str(exc))

        notify(
            "corpus_selected",
            "활성 PUBG Steam 코퍼스를 선택했습니다.",
            {"corpus_version": manifest["corpus_version"]},
        )
        evidence = [
            EvidenceItem(
                evidence_id=record.evidence_id,
                source=SourceType.STEAM,
                source_url="https://steamcommunity.com",
                source_id=record.evidence_id,
                language=CORPUS_LANGUAGES[record.language],
                observed_at=datetime.fromisoformat(record.updated_at),
                summary=record.summary,
                mechanism_tags=_event_tags(record, query),
                relevance=relevance,
            )
            for record, relevance in _ranked_records(records)
        ]
        samples, errors = _samples_and_errors(evidence, manifest)
        notify(
            "corpus_retrieved",
            "기획안과 관련 있는 비식별 근거를 찾았습니다.",
            {"evidence": len(evidence)},
        )
        return FeedbackBundle(
            run_id=event.run_id,
            status=ArtifactStatus.PARTIAL if errors else ArtifactStatus.COMPLETE,
            producer=Producer.COLLECTOR,
            input_refs=[event.ref],
            errors=errors,
            input_mode=InputMode.CORPUS,
            cutoff_at=event.cutoff_at,
            search_log=_search_log(records, manifest),
            samples=samples,
            evidence=evidence,
        )


class UpdateCorpusCollector:
    """Res-owned adapter: active Hy corpus -> existing UpdateFeedbackBundle."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def run(self, brief: UpdateBrief, _options=None, on_event=None) -> UpdateFeedbackBundle:
        notify = on_event or (lambda _node, _message, _metrics: None)
        query = _update_query(brief)
        try:
            manifest = _manifest_before_cutoff(self.db_path, brief.cutoff_at)
            records = _search_languages(self.db_path, query, brief.cutoff_at)
        except (CorpusBuildError, OSError, sqlite3.Error, ValueError) as exc:
            return _failed_update_bundle(brief, str(exc))

        notify(
            "corpus_selected",
            "활성 PUBG Steam 코퍼스를 선택했습니다.",
            {"corpus_version": manifest["corpus_version"]},
        )
        evidence = [
            UpdateEvidenceItem(
                evidence_id=record.evidence_id,
                source=SourceType.STEAM,
                source_url="https://steamcommunity.com",
                source_id=record.evidence_id,
                language=CORPUS_LANGUAGES[record.language],
                observed_at=datetime.fromisoformat(record.updated_at),
                period=EvidencePeriod.COMPARABLE_REFERENCE,
                sentiment=Sentiment(record.stance),
                summary=record.summary,
                mechanism_tags=_update_tags(record),
                relevance=relevance,
            )
            for record, relevance in _ranked_records(records)
        ]
        samples, errors = _samples_and_errors(evidence, manifest)
        notify(
            "corpus_retrieved",
            "변경안과 관련 있는 비식별 근거를 찾았습니다.",
            {"evidence": len(evidence)},
        )
        return UpdateFeedbackBundle(
            run_id=brief.run_id,
            status=ArtifactStatus.PARTIAL if errors else ArtifactStatus.COMPLETE,
            producer=Producer.COLLECTOR,
            input_refs=[brief.ref],
            errors=errors,
            input_mode=InputMode.CORPUS,
            cutoff_at=brief.cutoff_at,
            search_log=_search_log(records, manifest),
            samples=samples,
            evidence=evidence,
        )


def _manifest_before_cutoff(db_path: Path, cutoff_at: datetime) -> dict[str, str]:
    manifest = corpus_status(db_path)
    if manifest.get("status") != "active":
        raise CorpusBuildError("활성 코퍼스를 찾지 못했습니다.")
    snapshot_at = datetime.fromisoformat(manifest["snapshot_at"])
    if snapshot_at >= cutoff_at:
        raise CorpusBuildError("코퍼스 기준 시점이 검토 기준일보다 늦습니다.")
    return manifest


def _search_languages(
    db_path: Path, query: str, cutoff_at: datetime
) -> list[CorpusRecord]:
    return [
        record
        for language in ("ko", "en")
        for record in search_corpus(
            query,
            db_path=db_path,
            language=language,
            limit=20,
            cutoff_at=cutoff_at,
        )
    ]


def _samples_and_errors(evidence, manifest):
    samples = []
    errors = []
    for code, language in CORPUS_LANGUAGES.items():
        relevant = sum(item.language is language for item in evidence)
        sample = LanguageSample(
            language=language,
            general_count=int(manifest[f"{code}_count"]),
            mechanism_count=relevant,
        )
        samples.append(sample)
        if not sample.sufficient:
            errors.append(
                PipelineError(
                    code=ErrorCode.INSUFFICIENT_EVIDENCE,
                    message=f"{language.value} 언어권의 관련 근거를 더 확보해야 합니다.",
                )
            )
    return samples, errors


def _search_log(records: list[CorpusRecord], manifest: dict[str, str]):
    now = datetime.now(UTC)
    return [
        SearchRecord(
            source=SourceType.STEAM,
            language=language,
            query=f"corpus:{manifest['corpus_version']}",
            requested_at=now,
            result_count=sum(
                item.language == code for item in records
            ),
        )
        for code, language in CORPUS_LANGUAGES.items()
    ]


def _event_query(event: EventBrief) -> str:
    return " ".join(
        [
            event.event_name,
            event.goal,
            event.participation_rule,
            event.repeat_rule,
            *event.rewards,
            *event.currencies,
            event.probability_guarantee,
            event.monetization_policy,
            event.expiration_policy,
        ]
    )


def _update_query(brief: UpdateBrief) -> str:
    details = [
        str(value)
        for value in brief.details.model_dump(mode="python").values()
        if isinstance(value, str)
    ]
    return " ".join(
        [
            brief.update_name,
            brief.current_state,
            brief.change_summary,
            brief.goal,
            *brief.expected_benefits,
            *brief.concerns,
            brief.scope,
            *details,
        ]
    )


def _event_tags(record: CorpusRecord, query: str) -> list[str]:
    topics = set(record.topic_tags)
    reasons = set(record.reason_codes)
    lowered = query.lower()
    tags: list[str] = []
    if "randomness" in topics:
        tags.append(RiskCategory.RANDOM_BONUS.value)
        if any(token in lowered for token in ("2단계", "이중", "gacha", "상자")):
            tags.append(RiskCategory.DOUBLE_GACHA.value)
    if "event_flow" in topics or "complexity" in reasons:
        tags.append(RiskCategory.FRAGMENTED_FLOW.value)
    if "progression" in topics or "progress_clarity" in reasons:
        tags.append(RiskCategory.OPAQUE_PROGRESS.value)
    if any(token in lowered for token in ("만료", "소멸", "expire")):
        tags.append(RiskCategory.EXPIRING_CURRENCY.value)
    return list(dict.fromkeys(tags or [*record.topic_tags, *record.reason_codes]))


def _update_tags(record: CorpusRecord) -> list[str]:
    topics = set(record.topic_tags)
    reasons = set(record.reason_codes)
    tags: list[str] = []
    if "predictability" in reasons:
        tags.append("predictability")
    if "fairness" in reasons:
        tags.append(
            "skill_fairness" if record.stance == "positive" else "fairness_regression"
        )
    if "weapon_balance" in topics or "balance" in reasons:
        tags.extend(("balance_regression", "validation_needed"))
    if "interface" in topics:
        tags.extend(("information_clarity", "flow_disruption"))
    if "complexity" in reasons:
        tags.append("learning_burden")
    return list(dict.fromkeys(tags or ["validation_needed"]))


def _rank_confidence(record: CorpusRecord, index: int) -> float:
    return max(0.0, min(1.0, record.confidence - index * 0.005))


def _ranked_records(records: list[CorpusRecord]):
    indexes = {language: 0 for language in CORPUS_LANGUAGES}
    for record in records:
        index = indexes[record.language]
        yield record, _rank_confidence(record, index)
        indexes[record.language] = index + 1


def _failed_event_bundle(event: EventBrief, _reason: str) -> FeedbackBundle:
    return FeedbackBundle(
        run_id=event.run_id,
        status=ArtifactStatus.FAILED,
        producer=Producer.COLLECTOR,
        input_refs=[event.ref],
        errors=[
            PipelineError(
                code=ErrorCode.SOURCE_UNAVAILABLE,
                message="활성 PUBG Steam 코퍼스를 안전하게 읽지 못했습니다.",
            )
        ],
        input_mode=InputMode.CORPUS,
        cutoff_at=event.cutoff_at,
        search_log=[],
        samples=[],
        evidence=[],
    )


def _failed_update_bundle(brief: UpdateBrief, _reason: str) -> UpdateFeedbackBundle:
    return UpdateFeedbackBundle(
        run_id=brief.run_id,
        status=ArtifactStatus.FAILED,
        producer=Producer.COLLECTOR,
        input_refs=[brief.ref],
        errors=[
            PipelineError(
                code=ErrorCode.SOURCE_UNAVAILABLE,
                message="활성 PUBG Steam 코퍼스를 안전하게 읽지 못했습니다.",
            )
        ],
        input_mode=InputMode.CORPUS,
        cutoff_at=brief.cutoff_at,
        search_log=[],
        samples=[],
        evidence=[],
    )
