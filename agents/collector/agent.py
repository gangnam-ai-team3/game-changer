from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from connectors import ConnectorError, RawFeedback
from connectors.importer import import_approved_csv
from connectors.steam import SteamClient
from connectors.x import ProjectBudget, XClient
from contracts import (
    SUPPORTED_LANGUAGES,
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
    SearchRecord,
)
from evaluation.fixtures import load_feedback_fixture


@dataclass(slots=True)
class CollectionOptions:
    use_fixture: bool = True
    imported_csv: bytes | None = None
    steam_app_id: int | None = None
    use_x: bool = False
    x_query: str = "PUBG Black Market"
    x_estimated_total_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.x_estimated_total_cost_usd <= 10:
            raise ValueError("X estimated project cost must be between $0 and $10")

    @property
    def input_mode(self) -> InputMode:
        if self.use_fixture:
            return InputMode.FIXTURE
        if self.steam_app_id or self.use_x:
            return InputMode.LIVE
        return InputMode.IMPORT


class CollectorAgent:
    model = os.getenv("OPENAI_COLLECTOR_MODEL", "gpt-5.6-luna")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, steam: SteamClient | None = None, x_client: XClient | None = None) -> None:
        self.steam = steam or SteamClient()
        self.x_client = x_client or XClient(os.getenv("X_BEARER_TOKEN"), ProjectBudget(cap_usd=10))

    def run(self, event: EventBrief, options: CollectionOptions) -> FeedbackBundle:
        if options.use_fixture:
            bundle = load_feedback_fixture(event)
            return bundle.model_copy(update={"input_refs": [event.ref]})

        evidence: list[EvidenceItem] = []
        search_log: list[SearchRecord] = []
        errors: list[PipelineError] = []
        general_counts = {language: 0 for language in SUPPORTED_LANGUAGES}

        if options.imported_csv:
            try:
                imported = import_approved_csv(options.imported_csv, event.cutoff_at)
                evidence.extend(imported)
                for item in imported:
                    general_counts[item.language] += 1
            except ConnectorError as exc:
                errors.append(PipelineError(code=exc.code, message=str(exc)))

        for language in SUPPORTED_LANGUAGES:
            raw: list[RawFeedback] = []
            if options.steam_app_id:
                raw.extend(self._collect_steam(options.steam_app_id, language, event, errors))
                search_log.append(
                    SearchRecord(
                        source="steam",
                        language=language,
                        query=f"app:{options.steam_app_id}",
                        requested_at=datetime.now(UTC),
                        result_count=len(raw),
                    )
                )
            if options.use_x:
                before = len(raw)
                estimated_cost = options.x_estimated_total_cost_usd / len(SUPPORTED_LANGUAGES)
                try:
                    raw.extend(
                        self.x_client.fetch_recent(
                            options.x_query,
                            language,
                            event.cutoff_at,
                            estimated_cost_usd=estimated_cost,
                        )
                    )
                except ConnectorError as exc:
                    errors.append(PipelineError(code=exc.code, message=str(exc)))
                search_log.append(
                    SearchRecord(
                        source="x",
                        language=language,
                        query=options.x_query,
                        requested_at=datetime.now(UTC),
                        result_count=len(raw) - before,
                        estimated_cost_usd=estimated_cost,
                    )
                )
            general_counts[language] += len(raw)
            evidence.extend(_summarize_without_persisting_raw(raw))

        samples = [
            LanguageSample(
                language=language,
                general_count=general_counts[language],
                mechanism_count=sum(item.language == language for item in evidence),
            )
            for language in SUPPORTED_LANGUAGES
        ]
        for sample in samples:
            if not sample.sufficient:
                errors.append(
                    PipelineError(
                        code=ErrorCode.INSUFFICIENT_EVIDENCE,
                        message=f"{sample.language.value}: requires 100 general and 15 mechanism items",
                    )
                )

        status = ArtifactStatus.PARTIAL if errors else ArtifactStatus.COMPLETE
        fatal_codes = {
            ErrorCode.AUTH_FAILED,
            ErrorCode.BUDGET_EXCEEDED,
            ErrorCode.SOURCE_UNAVAILABLE,
            ErrorCode.INVALID_IMPORT,
        }
        if not evidence and any(error.code in fatal_codes for error in errors):
            status = ArtifactStatus.FAILED
        return FeedbackBundle(
            run_id=event.run_id,
            status=status,
            producer=Producer.COLLECTOR,
            input_refs=[event.ref],
            errors=errors,
            input_mode=options.input_mode,
            cutoff_at=event.cutoff_at,
            search_log=search_log,
            samples=samples,
            evidence=evidence,
        )

    def _collect_steam(
        self,
        app_id: int,
        language: Language,
        event: EventBrief,
        errors: list[PipelineError],
    ) -> list[RawFeedback]:
        try:
            return self.steam.fetch_reviews(app_id, language, event.cutoff_at, limit=100)
        except ConnectorError as exc:
            errors.append(PipelineError(code=exc.code, message=str(exc)))
            return []


def _summarize_without_persisting_raw(items: list[RawFeedback]) -> list[EvidenceItem]:
    results: list[EvidenceItem] = []
    for index, item in enumerate(items):
        tags = _mechanism_tags(item.text)
        if not tags:
            continue
        results.append(
            EvidenceItem(
                evidence_id=f"live-{item.source.value}-{item.source_id}-{index}",
                source=item.source,
                source_url=item.source_url,
                source_id=item.source_id,
                language=item.language,
                observed_at=item.observed_at,
                summary=f"비식별 피드백에서 {', '.join(tags)} 메커니즘 우려가 확인됨.",
                mechanism_tags=tags,
                relevance=0.6,
            )
        )
    return results


def _mechanism_tags(text: str) -> list[str]:
    lowered = text.lower()
    keywords = {
        "double_gacha": ("double gacha", "two-step", "2단계", "二阶段"),
        "fragmented_flow": ("confusing", "complex", "복잡", "复杂", "confuso"),
        "opaque_progress": ("progress", "guarantee", "진행", "보장", "进度"),
        "random_bonus": ("random", "chance", "확률", "随机", "aleatorio"),
        "expiring_currency": ("expire", "expiry", "만료", "过期", "caduca"),
    }
    return [tag for tag, words in keywords.items() if any(word in lowered for word in words)]
