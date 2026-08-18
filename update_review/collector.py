from __future__ import annotations

import csv
import hashlib
import io
import math
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
)
from connectors import ConnectorError, RawFeedback
from connectors.steam import SteamClient
from connectors.x import ProjectBudget, XClient
from contracts import (
    ArtifactStatus,
    ErrorCode,
    InputMode,
    Language,
    LanguageSample,
    PipelineError,
    Producer,
    SearchRecord,
    SourceType,
    SUPPORTED_LANGUAGES,
)
from update_review.contracts import (
    EvidencePeriod,
    Sentiment,
    UpdateBrief,
    UpdateEvidenceItem,
    UpdateFeedbackBundle,
)
from update_review.fixtures import load_update_feedback_fixture


NodeCallback = Callable[[str, str, dict], None]

APPROVED_UPDATE_TAGS = frozenset(
    {
        "predictability",
        "skill_fairness",
        "balance_regression",
        "fairness_regression",
        "validation_needed",
        "information_clarity",
        "flow_disruption",
        "rule_exception",
        "learning_burden",
    }
)

REQUIRED_UPDATE_COLUMNS = frozenset(
    {
        "source",
        "source_url",
        "source_id",
        "language",
        "observed_at",
        "period",
        "sentiment",
        "summary",
        "mechanism_tags",
    }
)
FORBIDDEN_UPDATE_COLUMNS = frozenset(
    {
        "username",
        "user_name",
        "author",
        "handle",
        "raw_text",
        "text",
        "content",
        "account_id",
    }
)
APPROVED_UPDATE_IMPORT_HOSTS = {
    "reddit": (SourceType.REDDIT_IMPORT, frozenset({"reddit.com", "www.reddit.com"})),
    "threads": (SourceType.THREADS_IMPORT, frozenset({"threads.net", "www.threads.net"})),
    "instagram": (
        SourceType.INSTAGRAM_IMPORT,
        frozenset({"instagram.com", "www.instagram.com"}),
    ),
}
MAX_UPDATE_CSV_BYTES = 2_000_000
# Live connectors can return hundreds of long reviews.  The collector keeps
# the full count for the language sufficiency gate, but sends only a bounded,
# deterministic representative sample to Claude so one structured response
# stays within the request/output budget.
MAX_LIVE_CLASSIFICATION_PER_LANGUAGE = 15
MAX_LIVE_CLASSIFICATION_BATCH = 40

# Raw connector URLs are untrusted metadata.  Only these source hosts are
# accepted at the live boundary, and artifacts retain the corresponding
# code-owned canonical URL instead of a post/review path or query string.
LIVE_SOURCE_METADATA = {
    SourceType.STEAM: (
        frozenset({"steamcommunity.com", "www.steamcommunity.com"}),
        "https://steamcommunity.com",
    ),
    SourceType.X: (frozenset({"x.com", "www.x.com"}), "https://x.com"),
}

# Nothing originating with an external source is used in an artifact error,
# execution event, or JSONL record.  These code-owned messages deliberately
# retain the actionable error code while keeping rejected input ephemeral.
_SAFE_ERROR_MESSAGES = {
    ErrorCode.AUTH_FAILED: "외부 수집 또는 분류 인증을 확인하지 못했습니다.",
    ErrorCode.BUDGET_EXCEEDED: "외부 수집 또는 분류 예산 한도에 도달했습니다.",
    ErrorCode.SOURCE_UNAVAILABLE: "외부 자료 수집을 완료하지 못했습니다.",
    ErrorCode.INVALID_IMPORT: "승인 CSV 입력을 안전하게 검증하지 못했습니다.",
    ErrorCode.INSUFFICIENT_EVIDENCE: "수집된 관련 근거가 부족합니다.",
    ErrorCode.LLM_REFUSAL: "원문 분류 모델이 구조화된 결과를 반환하지 않았습니다.",
    ErrorCode.SCHEMA_INVALID: "외부 수집 또는 분류 결과가 계약을 충족하지 못했습니다.",
}

_TAG_SUMMARY_LABELS = {
    "predictability": "결과 예측 가능성",
    "skill_fairness": "실력 기반 공정성",
    "balance_regression": "성능 균형",
    "fairness_regression": "공정성 인식",
    "validation_needed": "검증 지표",
    "information_clarity": "변경 정보 이해",
    "flow_disruption": "이용 동선",
    "rule_exception": "예외 규칙",
    "learning_burden": "학습 부담",
}

_SENTIMENT_SUMMARY_LABELS = {
    Sentiment.POSITIVE: "긍정",
    Sentiment.NEGATIVE: "부정",
    Sentiment.NEUTRAL: "중립",
    Sentiment.MIXED: "혼합",
}


class ClassifiedRawItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    sentiment: Sentiment
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)


class ClassifiedRawBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ClassifiedRawItem]


def _code_owned_summary_from_fields(
    sentiment: Sentiment, mechanism_tags: list[str], relevance: float
) -> str:
    """Build persisted text solely from closed fields, never source text."""

    tags = "·".join(_TAG_SUMMARY_LABELS[tag] for tag in sorted(set(mechanism_tags)))
    relevance = (
        "높은 관련성"
        if relevance >= 0.75
        else "보통 관련성"
        if relevance >= 0.4
        else "낮은 관련성"
    )
    return (
        f"{tags} 관련 {_SENTIMENT_SUMMARY_LABELS[sentiment]} 신호가 "
        f"{relevance}으로 분류되어 출시 전 확인 필요."
    )


def _code_owned_summary(item: ClassifiedRawItem) -> str:
    return _code_owned_summary_from_fields(
        item.sentiment, item.mechanism_tags, item.relevance
    )


def _canonical_live_source_url(source: SourceType, value: object) -> str | None:
    """Validate a raw connector URL without ever retaining its path/query."""

    config = LIVE_SOURCE_METADATA.get(source)
    if config is None or not isinstance(value, str):
        return None
    hosts, canonical_url = config
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        return None
    return canonical_url


def _live_source_id(source: SourceType, raw_source_id: str) -> str:
    """Create a non-reversible, source-namespaced correlation/persistence ID."""

    digest = hashlib.sha256(
        f"{source.value}:{raw_source_id}".encode("utf-8")
    ).hexdigest()[:20]
    return f"{source.value}-{digest}"


def _classification_sample(raw: list[RawFeedback]) -> list[RawFeedback]:
    """Select a deterministic, source-balanced live sample for Claude."""

    by_language: dict[Language, dict[SourceType, list[RawFeedback]]] = {}
    for item in raw:
        by_language.setdefault(item.language, {}).setdefault(item.source, []).append(item)

    selected: list[RawFeedback] = []
    for language in SUPPORTED_LANGUAGES:
        groups = [
            items
            for _source, items in sorted(
                by_language.get(language, {}).items(), key=lambda pair: pair[0].value
            )
            if items
        ]
        language_count = 0
        while groups and language_count < MAX_LIVE_CLASSIFICATION_PER_LANGUAGE:
            progressed = False
            for group in groups:
                if group:
                    selected.append(group.pop(0))
                    language_count += 1
                    progressed = True
                    if language_count >= MAX_LIVE_CLASSIFICATION_PER_LANGUAGE:
                        break
            if not progressed:
                break
    return selected


def normalize_update_csv_text(data: bytes | str) -> str:
    """Decode an update-only approved CSV under its separate UTF-8 2 MB cap."""

    if isinstance(data, bytes):
        if len(data) > MAX_UPDATE_CSV_BYTES:
            raise ConnectorError(ErrorCode.INVALID_IMPORT, "approved CSV exceeds 2 MB")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ConnectorError(
                ErrorCode.INVALID_IMPORT, "approved CSV must be UTF-8 text"
            ) from exc
    if not isinstance(data, str):
        raise ConnectorError(ErrorCode.INVALID_IMPORT, "approved CSV must be UTF-8 text")
    try:
        encoded = data.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConnectorError(
            ErrorCode.INVALID_IMPORT, "approved CSV must be UTF-8 text"
        ) from exc
    if len(encoded) > MAX_UPDATE_CSV_BYTES:
        raise ConnectorError(ErrorCode.INVALID_IMPORT, "approved CSV exceeds 2 MB")
    return data.lstrip("\ufeff")


def _csv_cell(row: dict[str | None, str | None], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def import_update_csv(
    data: bytes | str, cutoff_at: datetime
) -> list[UpdateEvidenceItem]:
    """Normalize approved update CSV rows without persisting their free-text summary."""

    if cutoff_at.tzinfo is None:
        raise ConnectorError(
            ErrorCode.INVALID_IMPORT, "cutoff_at must be timezone-aware"
        )
    text = normalize_update_csv_text(data)
    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames or []
        if any(not isinstance(name, str) or not name.strip() for name in fieldnames):
            raise ConnectorError(ErrorCode.INVALID_IMPORT, "CSV column names are invalid")
        normalized_fieldnames = [name.strip().lower() for name in fieldnames]
        columns = set(normalized_fieldnames)
        if len(columns) != len(normalized_fieldnames):
            raise ConnectorError(ErrorCode.INVALID_IMPORT, "CSV column names must be unique")
        # DictReader has consumed only the header at this point; replace it
        # with normalized names so row access below is case/space agnostic.
        reader.fieldnames = normalized_fieldnames
        if forbidden := columns & FORBIDDEN_UPDATE_COLUMNS:
            raise ConnectorError(
                ErrorCode.INVALID_IMPORT,
                f"personal/raw columns are forbidden: {', '.join(sorted(forbidden))}",
            )
        if missing := REQUIRED_UPDATE_COLUMNS - columns:
            raise ConnectorError(
                ErrorCode.INVALID_IMPORT,
                f"missing columns: {', '.join(sorted(missing))}",
            )
        if columns - REQUIRED_UPDATE_COLUMNS:
            # An unknown extra field can itself carry raw user material.  Do
            # not reflect its name back to callers or accept it silently.
            raise ConnectorError(
                ErrorCode.INVALID_IMPORT, "unapproved CSV columns are not allowed"
            )

        output: list[UpdateEvidenceItem] = []
        seen_evidence_ids: set[str] = set()
        cutoff = cutoff_at.astimezone(UTC)
        for row_number, row in enumerate(reader, start=2):
            try:
                if None in row:
                    raise ValueError("unexpected CSV columns")
                source_name = _csv_cell(row, "source").lower()
                source, hosts = APPROVED_UPDATE_IMPORT_HOSTS[source_name]
                parsed = urlparse(_csv_cell(row, "source_url"))
                host = (parsed.hostname or "").lower()
                if (
                    parsed.scheme.lower() != "https"
                    or host not in hosts
                    or parsed.port not in (None, 443)
                    or parsed.username is not None
                    or parsed.password is not None
                ):
                    raise ValueError("source URL is not from an approved host")
                observed_at = datetime.fromisoformat(
                    _csv_cell(row, "observed_at")
                )
                if observed_at.tzinfo is None:
                    raise ValueError("observed_at must be timezone-aware")
                observed_at = observed_at.astimezone(UTC)
                if observed_at >= cutoff:
                    raise ValueError("row is on or after cutoff_at")
                period = EvidencePeriod(_csv_cell(row, "period").lower())
                if period is EvidencePeriod.AFTER:
                    raise ValueError("after period is not allowed in prelaunch import")
                sentiment = Sentiment(_csv_cell(row, "sentiment").lower())
                tags = sorted(
                    {
                        value.strip().lower()
                        for value in _csv_cell(row, "mechanism_tags").split("|")
                        if value.strip()
                    }
                )
                if not tags or not set(tags) <= APPROVED_UPDATE_TAGS:
                    raise ValueError(
                        "mechanism_tags must contain only approved update values"
                    )
                # Validate the supplied column without retaining its contents.
                _csv_cell(row, "summary")
                public_id = _csv_cell(row, "source_id")
                anonymous_id = hashlib.sha256(
                    f"{source.value}:{public_id}".encode()
                ).hexdigest()[:20]
                evidence_id = f"imp-update-{anonymous_id}"
                if evidence_id in seen_evidence_ids:
                    raise ValueError("duplicate approved source identifier")
                seen_evidence_ids.add(evidence_id)
                output.append(
                    UpdateEvidenceItem(
                        evidence_id=evidence_id,
                        source=source,
                        source_url=f"https://{host}",
                        source_id=anonymous_id,
                        language=Language(_csv_cell(row, "language")),
                        observed_at=observed_at,
                        period=period,
                        sentiment=sentiment,
                        summary=_code_owned_summary_from_fields(
                            sentiment, tags, 1.0
                        ),
                        mechanism_tags=tags,
                        relevance=1.0,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                # Known validation messages are code-owned.  Never reflect an
                # arbitrary source value (for example KeyError("user text"))
                # into a raised error that a caller could later serialize.
                safe_reason = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    and str(exc)
                    in {
                        "unexpected CSV columns",
                        "source URL is not from an approved host",
                        "observed_at must be timezone-aware",
                        "row is on or after cutoff_at",
                        "after period is not allowed in prelaunch import",
                        "mechanism_tags must contain only approved update values",
                        "duplicate approved source identifier",
                    }
                    else "approved CSV row is invalid"
                )
                raise ConnectorError(
                    ErrorCode.INVALID_IMPORT, f"row {row_number}: {safe_reason}"
                ) from exc
        return output
    except csv.Error as exc:
        raise ConnectorError(ErrorCode.INVALID_IMPORT, "approved CSV is malformed") from exc


@dataclass(slots=True)
class UpdateCollectionOptions:
    use_fixture: bool = True
    fixture_case: str = "dragunov_random_damage_removal"
    imported_csv: bytes | str | None = None
    steam_app_id: int | None = None
    use_x: bool = False
    x_query: str = "PUBG Dragunov damage"
    period_start: datetime | None = None
    period_end: datetime | None = None
    x_estimated_total_cost_usd: float = 0.0

    @property
    def input_mode(self) -> InputMode:
        if self.use_fixture:
            return InputMode.FIXTURE
        if self.steam_app_id is not None or self.use_x:
            return InputMode.LIVE
        return InputMode.IMPORT


class UpdateCollectorAgent:
    prompt_path = Path(__file__).with_name("prompts") / "collector.md"

    def __init__(
        self,
        steam: SteamClient | None = None,
        x_client: XClient | None = None,
        *,
        use_llm: bool = False,
        client=None,
        budget: ClaudeBudget | None = None,
    ) -> None:
        self.steam = steam or SteamClient()
        self.x_client = x_client or XClient(
            os.getenv("X_BEARER_TOKEN"), ProjectBudget(cap_usd=10)
        )
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def classify_raw(
        self, raw: list[RawFeedback], brief: UpdateBrief
    ) -> list[UpdateEvidenceItem]:
        if not raw:
            return []
        if not self.use_llm:
            raise StructuredModelError(
                ErrorCode.LLM_REFUSAL, "live raw classification requires Claude"
            )
        if any(
            not isinstance(item.source_id, str) or not item.source_id.strip()
            for item in raw
        ):
            raise StructuredModelError(
                ErrorCode.SCHEMA_INVALID,
                "Claude classifier received unsafe source metadata.",
            )
        # The Claude contract returns source_id only, so namespace collisions must
        # be rejected before raw text is sent to the classifier.
        if len({item.source_id for item in raw}) != len(raw):
            raise StructuredModelError(
                ErrorCode.SCHEMA_INVALID,
                "Claude classifier received ambiguous source identifiers.",
            )
        by_id: dict[str, RawFeedback] = {}
        for original in raw:
            if (
                (canonical_url := _canonical_live_source_url(
                    original.source, original.source_url
                ))
                is None
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude classifier received unsafe source metadata.",
                )
            correlation_id = _live_source_id(original.source, original.source_id)
            if correlation_id in by_id:
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude classifier received ambiguous source identifiers.",
                )
            # The classifier map carries only normalized metadata.  Claude sees
            # this code-owned correlation ID, while the caller clears the
            # original raw list immediately after classification.
            by_id[correlation_id] = RawFeedback(
                source=original.source,
                source_url=canonical_url,
                source_id=correlation_id,
                language=original.language,
                observed_at=original.observed_at,
                text=original.text,
            )
        output = []
        source_ids = list(by_id)
        for offset in range(0, len(source_ids), MAX_LIVE_CLASSIFICATION_BATCH):
            batch_ids = source_ids[offset : offset + MAX_LIVE_CLASSIFICATION_BATCH]
            payload = {
                "update": brief.model_dump(mode="json"),
                "feedback": [
                    {
                        "source_id": by_id[source_id].source_id,
                        "language": by_id[source_id].language.value,
                        "observed_at": by_id[source_id].observed_at.isoformat(),
                        "text": by_id[source_id].text,
                    }
                    for source_id in batch_ids
                ],
            }
            batch = parse_claude_structured(
                model=os.getenv("CLAUDE_UPDATE_COLLECTOR_MODEL", "claude-haiku-4-5"),
                prompt_path=self.prompt_path,
                output_type=ClassifiedRawBatch,
                payload=payload,
                client=self.client,
                budget=self.budget,
            )
            seen_source_ids: set[str] = set()
            for item in batch.items:
                original = by_id.get(item.source_id)
                if (
                    original is None
                    or item.source_id not in batch_ids
                    or item.source_id in seen_source_ids
                    or not set(item.mechanism_tags) <= APPROVED_UPDATE_TAGS
                ):
                    raise StructuredModelError(
                        ErrorCode.SCHEMA_INVALID,
                        "Claude classifier returned unsafe structured classifications.",
                    )
                seen_source_ids.add(item.source_id)
                output.append(
                    UpdateEvidenceItem(
                        evidence_id=f"live-update-{original.source_id}",
                        source=original.source,
                        source_url=original.source_url,
                        source_id=original.source_id,
                        language=original.language,
                        observed_at=original.observed_at,
                        period=EvidencePeriod.BEFORE,
                        sentiment=item.sentiment,
                        summary=_code_owned_summary(item),
                        mechanism_tags=item.mechanism_tags,
                        relevance=item.relevance,
                    )
                )
            if seen_source_ids != set(batch_ids):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude classifier returned incomplete structured classifications.",
                )
        return output

    @staticmethod
    def _safe_error(
        exc: Exception, *, default: ErrorCode = ErrorCode.SCHEMA_INVALID
    ) -> PipelineError:
        code = exc.code if isinstance(exc, (ConnectorError, StructuredModelError)) else default
        return PipelineError(
            code=code,
            message=_SAFE_ERROR_MESSAGES[code],
            retryable=False,
        )

    @staticmethod
    def _samples(
        general_counts: Counter[Language], evidence: list[UpdateEvidenceItem]
    ) -> list[LanguageSample]:
        mechanism_counts = Counter(item.language for item in evidence)
        return [
            LanguageSample(
                language=language,
                general_count=general_counts[language],
                mechanism_count=mechanism_counts[language],
            )
            for language in SUPPORTED_LANGUAGES
        ]

    @staticmethod
    def _bundle(
        brief: UpdateBrief,
        *,
        input_mode: InputMode,
        search_log: list[SearchRecord],
        samples: list[LanguageSample],
        evidence: list[UpdateEvidenceItem],
        errors: list[PipelineError],
    ) -> UpdateFeedbackBundle:
        # Downstream impact contracts intentionally allow an empty signal set
        # only when the collector made the insufficiency explicit.  A partial
        # live/import bundle therefore carries a safe error rather than asking
        # later agents to infer that an empty or undersized sample is usable.
        has_decision_signal = any(
            item.sentiment is not Sentiment.NEUTRAL for item in evidence
        )
        if (
            not errors
            and (
                not evidence
                or not has_decision_signal
                or any(not item.sufficient for item in samples)
            )
        ):
            errors.append(
                PipelineError(
                    code=ErrorCode.INSUFFICIENT_EVIDENCE,
                    message=_SAFE_ERROR_MESSAGES[ErrorCode.INSUFFICIENT_EVIDENCE],
                    retryable=False,
                )
            )
        status = ArtifactStatus.COMPLETE
        if errors or not evidence or any(not item.sufficient for item in samples):
            status = ArtifactStatus.PARTIAL
        return UpdateFeedbackBundle(
            run_id=brief.run_id,
            status=status,
            producer=Producer.COLLECTOR,
            input_refs=[brief.ref],
            errors=errors,
            input_mode=input_mode,
            cutoff_at=brief.cutoff_at,
            search_log=search_log,
            samples=samples,
            evidence=evidence,
        )

    @staticmethod
    def _valid_live_row(
        item: RawFeedback,
        *,
        source: SourceType,
        start_at: datetime,
        cutoff_at: datetime,
    ) -> bool:
        """Defend the collector boundary even when an injected connector misbehaves."""

        if (
            item.source is not source
            or item.observed_at.tzinfo is None
            or not isinstance(item.source_id, str)
            or not item.source_id.strip()
            or _canonical_live_source_url(item.source, item.source_url) is None
        ):
            return False
        observed_at = item.observed_at.astimezone(UTC)
        return (
            start_at <= observed_at < cutoff_at
        )

    @staticmethod
    def _valid_live_options(
        options: UpdateCollectionOptions, brief: UpdateBrief
    ) -> tuple[datetime, datetime] | None:
        start_at, cutoff_at = options.period_start, options.period_end
        if (
            not isinstance(start_at, datetime)
            or not isinstance(cutoff_at, datetime)
            or start_at.tzinfo is None
            or cutoff_at.tzinfo is None
            or not start_at < cutoff_at <= brief.cutoff_at
            or (
                options.steam_app_id is not None
                and (
                    not isinstance(options.steam_app_id, int)
                    or isinstance(options.steam_app_id, bool)
                    or options.steam_app_id < 1
                )
            )
            or not isinstance(options.x_estimated_total_cost_usd, (int, float))
            or not math.isfinite(options.x_estimated_total_cost_usd)
            or options.x_estimated_total_cost_usd < 0
            or (
                options.use_x
                and (
                    not isinstance(options.x_query, str)
                    or not options.x_query.strip()
                )
            )
        ):
            return None
        return start_at.astimezone(UTC), cutoff_at.astimezone(UTC)

    @staticmethod
    def _notify_bundle(
        notify: NodeCallback,
        bundle: UpdateFeedbackBundle,
        *,
        source_message: str,
        period_message: str,
    ) -> None:
        notify(
            "source_selected",
            source_message,
            {"input_mode": bundle.input_mode.value},
        )
        notify(
            "period_checked",
            period_message,
            {"accepted": len(bundle.evidence), "errors": len(bundle.errors)},
        )
        notify(
            "anonymized",
            "원문과 사용자 식별자를 저장하지 않고 코드 소유 요약만 남겼습니다.",
            {"evidence": len(bundle.evidence)},
        )
        notify(
            "samples_counted",
            "언어권별 관련 표본을 집계했습니다.",
            {"insufficient": sum(not item.sufficient for item in bundle.samples)},
        )
        notify(
            "bundle_ready",
            "UpdateFeedbackBundle 계약 검증을 통과했습니다.",
            {"evidence": len(bundle.evidence), "errors": len(bundle.errors)},
        )

    def _run_import(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions,
        notify: NodeCallback,
    ) -> UpdateFeedbackBundle:
        errors: list[PipelineError] = []
        evidence: list[UpdateEvidenceItem] = []
        search_log: list[SearchRecord] = []
        general_counts: Counter[Language] = Counter()
        data = options.imported_csv
        # The options object must not retain free-text CSV material after this
        # method returns.  The caller's original request remains its concern.
        options.imported_csv = None
        try:
            if data is None:
                raise ConnectorError(ErrorCode.INVALID_IMPORT, "missing approved CSV")
            evidence = import_update_csv(data, brief.cutoff_at)
            general_counts.update(item.language for item in evidence)
            grouped = Counter((item.source, item.language) for item in evidence)
            search_log = [
                SearchRecord(
                    source=source,
                    language=language,
                    query="approved update CSV import",
                    requested_at=brief.cutoff_at,
                    result_count=count,
                )
                for (source, language), count in sorted(
                    grouped.items(), key=lambda item: (item[0][0].value, item[0][1].value)
                )
            ]
        except Exception as exc:
            errors.append(self._safe_error(exc, default=ErrorCode.INVALID_IMPORT))
        finally:
            # Keep the entire text payload, including an invalid CSV, out of
            # long-lived collection state as soon as parsing is complete.
            del data

        samples = self._samples(general_counts, evidence)
        bundle = self._bundle(
            brief,
            input_mode=InputMode.IMPORT,
            search_log=search_log,
            samples=samples,
            evidence=evidence,
            errors=errors,
        )
        self._notify_bundle(
            notify,
            bundle,
            source_message="승인된 CSV 자료를 별도 입력 경로로 선택했습니다.",
            period_message="기준일 이전 행만 유지하고 실제 사후 반응 행을 거부했습니다.",
        )
        return bundle

    def _run_live(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions,
        notify: NodeCallback,
    ) -> UpdateFeedbackBundle:
        errors: list[PipelineError] = []
        evidence: list[UpdateEvidenceItem] = []
        search_log: list[SearchRecord] = []
        general_counts: Counter[Language] = Counter()
        window = self._valid_live_options(options, brief)
        if window is None:
            errors.append(
                PipelineError(
                    code=ErrorCode.SCHEMA_INVALID,
                    message=_SAFE_ERROR_MESSAGES[ErrorCode.SCHEMA_INVALID],
                    retryable=False,
                )
            )
            samples = self._samples(general_counts, evidence)
            bundle = self._bundle(
                brief,
                input_mode=InputMode.LIVE,
                search_log=search_log,
                samples=samples,
                evidence=evidence,
                errors=errors,
            )
            self._notify_bundle(
                notify,
                bundle,
                source_message="선택한 Steam/X 실시간 자료 경로를 확인했습니다.",
                period_message="실시간 수집 기간을 안전하게 검증하지 못했습니다.",
            )
            return bundle

        start_at, cutoff_at = window
        raw: list[RawFeedback] = []

        def collect(
            source: SourceType,
            language: Language,
            fetch,
            *,
            estimated_cost_usd: float = 0.0,
        ) -> bool:
            """Collect one language without letting raw values escape this closure."""

            rows: list[RawFeedback] = []
            try:
                rows = fetch()
                accepted = 0
                rejected = False
                for item in rows:
                    if self._valid_live_row(
                        item,
                        source=source,
                        start_at=start_at,
                        cutoff_at=cutoff_at,
                    ):
                        raw.append(item)
                        accepted += 1
                    else:
                        rejected = True
                general_counts[language] += accepted
                if rejected:
                    errors.append(
                        PipelineError(
                            code=ErrorCode.SCHEMA_INVALID,
                            message=_SAFE_ERROR_MESSAGES[ErrorCode.SCHEMA_INVALID],
                            retryable=False,
                        )
                    )
                search_log.append(
                    SearchRecord(
                        source=source,
                        language=language,
                        query=(
                            "Steam update reviews"
                            if source is SourceType.STEAM
                            else "X update search"
                        ),
                        requested_at=cutoff_at,
                        result_count=accepted,
                        estimated_cost_usd=estimated_cost_usd,
                    )
                )
                return True
            except Exception as exc:
                errors.append(self._safe_error(exc))
                search_log.append(
                    SearchRecord(
                        source=source,
                        language=language,
                        query=(
                            "Steam update reviews"
                            if source is SourceType.STEAM
                            else "X update search"
                        ),
                        requested_at=cutoff_at,
                        result_count=0,
                        estimated_cost_usd=estimated_cost_usd,
                    )
                )
                return False
            finally:
                # Do not retain an individual connector's raw batch after it
                # has been copied to the short-lived classifier buffer.
                del rows

        if options.steam_app_id is not None:
            steam_available = True
            for language in SUPPORTED_LANGUAGES:
                if not steam_available:
                    break
                steam_available = collect(
                    SourceType.STEAM,
                    language,
                    lambda language=language: self.steam.fetch_reviews(
                        options.steam_app_id,
                        language,
                        cutoff_at,
                        start_at=start_at,
                    ),
                )

        if options.use_x:
            x_available = True
            per_language_cost = options.x_estimated_total_cost_usd / len(
                SUPPORTED_LANGUAGES
            )
            for language in SUPPORTED_LANGUAGES:
                if not x_available:
                    break
                x_available = collect(
                    SourceType.X,
                    language,
                    lambda language=language: self.x_client.fetch_recent(
                        options.x_query,
                        language,
                        cutoff_at,
                        estimated_cost_usd=per_language_cost,
                        start_at=start_at,
                    ),
                    estimated_cost_usd=per_language_cost,
                )

        try:
            if raw:
                # Keep the full connector count for sufficiency, but bound the
                # ephemeral raw text sent to one Claude structured call.
                evidence = self.classify_raw(_classification_sample(raw), brief)
        except Exception as exc:
            errors.append(self._safe_error(exc))
            evidence = []
        finally:
            # RawFeedback includes the source text.  It must never become part
            # of the returned artifact, node metrics, or JSONL logging path.
            raw.clear()
            del raw

        samples = self._samples(general_counts, evidence)
        bundle = self._bundle(
            brief,
            input_mode=InputMode.LIVE,
            search_log=search_log,
            samples=samples,
            evidence=evidence,
            errors=errors,
        )
        self._notify_bundle(
            notify,
            bundle,
            source_message="선택한 Steam/X 실시간 자료 경로를 확인했습니다.",
            period_message="기준일 이전의 수집 기간만 유지하고 범위 밖 자료를 제외했습니다.",
        )
        return bundle

    def run(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions,
        on_event: NodeCallback | None = None,
    ) -> UpdateFeedbackBundle:
        notify = on_event or (lambda _node, _message, _metrics: None)
        if not options.use_fixture:
            if options.input_mode is InputMode.LIVE:
                return self._run_live(brief, options, notify)
            return self._run_import(brief, options, notify)
        result = load_update_feedback_fixture(brief, options.fixture_case)
        notify(
            "source_selected",
            "출시 전 예상을 위한 저장 비교 자료를 선택했습니다.",
            {"input_mode": options.input_mode.value},
        )
        notify(
            "period_checked",
            "모든 자료를 실제 사후 반응이 아닌 비교 참고로 구분했습니다.",
            {"comparable_reference": len(result.evidence)},
        )
        notify(
            "anonymized",
            "원문과 사용자 식별자 없이 합성 요약만 불러왔습니다.",
            {"evidence": len(result.evidence)},
        )
        notify(
            "samples_counted",
            "언어권별 관련 표본을 집계했습니다.",
            {"insufficient": sum(not item.sufficient for item in result.samples)},
        )
        notify(
            "bundle_ready",
            "UpdateFeedbackBundle 계약 검증을 통과했습니다.",
            {"evidence": len(result.evidence)},
        )
        return result
