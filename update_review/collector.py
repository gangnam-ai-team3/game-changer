from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    require_prelaunch_narrative,
)
from connectors import RawFeedback
from connectors.steam import SteamClient
from connectors.x import ProjectBudget, XClient
from contracts import ErrorCode, InputMode
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

_RAW_OVERLAP_WINDOW = 10


def _normalized_text(value: str) -> str:
    """Normalize formatting without retaining a raw value in any artifact."""

    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def _text_tokens(value: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())


def _contains_meaningful_raw_overlap(raw_text: str, summary: str) -> bool:
    """Reject exact copies and substantial contiguous source fragments."""

    source = _normalized_text(raw_text)
    candidate = _normalized_text(summary)
    if not source or not candidate:
        return False
    if source == candidate:
        return True
    if min(len(source), len(candidate)) >= 8 and (
        source in candidate or candidate in source
    ):
        return True
    source_tokens = _text_tokens(raw_text)
    candidate_tokens = _text_tokens(summary)
    if len(source_tokens) >= 3 and len(candidate_tokens) >= 3:
        source_token_windows = {
            tuple(source_tokens[index : index + 3])
            for index in range(len(source_tokens) - 2)
        }
        if any(
            tuple(candidate_tokens[index : index + 3]) in source_token_windows
            for index in range(len(candidate_tokens) - 2)
        ):
            return True
    if min(len(source), len(candidate)) < _RAW_OVERLAP_WINDOW:
        return False
    source_windows = {
        source[index : index + _RAW_OVERLAP_WINDOW]
        for index in range(len(source) - _RAW_OVERLAP_WINDOW + 1)
    }
    return any(
        candidate[index : index + _RAW_OVERLAP_WINDOW] in source_windows
        for index in range(len(candidate) - _RAW_OVERLAP_WINDOW + 1)
    )


class ClassifiedRawItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    sentiment: Sentiment
    summary: str = Field(min_length=8, max_length=500)
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)


class ClassifiedRawBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ClassifiedRawItem]


@dataclass(slots=True)
class UpdateCollectionOptions:
    use_fixture: bool = True
    fixture_case: str = "dragunov_random_damage_removal"
    imported_csv: bytes | None = None
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
        if self.steam_app_id or self.use_x:
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
        # The Claude contract returns source_id only, so namespace collisions must
        # be rejected before raw text is sent to the classifier.
        if len({item.source_id for item in raw}) != len(raw):
            raise StructuredModelError(
                ErrorCode.SCHEMA_INVALID,
                "Claude classifier received ambiguous source identifiers.",
            )
        by_id = {item.source_id: item for item in raw}
        payload = {
            "update": brief.model_dump(mode="json"),
            "feedback": [
                {
                    "source_id": item.source_id,
                    "language": item.language.value,
                    "observed_at": item.observed_at.isoformat(),
                    "text": item.text,
                }
                for item in raw
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
        require_prelaunch_narrative([item.summary for item in batch.items])
        output = []
        for item in batch.items:
            original = by_id.get(item.source_id)
            if (
                original is None
                or not set(item.mechanism_tags) <= APPROVED_UPDATE_TAGS
                or _contains_meaningful_raw_overlap(original.text, item.summary)
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude classifier returned an unsafe structured summary.",
                )
            output.append(
                UpdateEvidenceItem(
                    evidence_id=f"live-update-{original.source.value}-{original.source_id}",
                    source=original.source,
                    source_url=original.source_url,
                    source_id=original.source_id,
                    language=original.language,
                    observed_at=original.observed_at,
                    period=EvidencePeriod.BEFORE,
                    sentiment=item.sentiment,
                    summary=item.summary,
                    mechanism_tags=item.mechanism_tags,
                    relevance=item.relevance,
                )
            )
        return output

    def run(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions,
        on_event: NodeCallback | None = None,
    ) -> UpdateFeedbackBundle:
        if not options.use_fixture:
            raise ValueError(
                "fixture source is required until an external update source is selected"
            )
        notify = on_event or (lambda _node, _message, _metrics: None)
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
