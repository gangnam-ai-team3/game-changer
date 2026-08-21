from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execution import ExecutionEvent
from update_review.contracts import (
    UpdateBrief,
    UpdateDecisionBrief,
    UpdateDetails,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateImpactAssessment,
    UpdateType,
    UpdateValidatedDecision,
)


_MAX_UPDATE_TEXT = 8_000
_MAX_UPDATE_LIST_ITEMS = 20
_MAX_UPDATE_CSV_BYTES = 2_000_000
_MAX_EVENT_CSV_BASE64 = 2_666_668
_FORBIDDEN_CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "anthropic_api_key",
        "openai_api_key",
        "authorization",
        "bearer_token",
        "x_bearer_token",
        "access_token",
        "secret",
        "password",
    }
)
RequestListText = Annotated[str, Field(min_length=1, max_length=1_000)]


class EventBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game: str = Field(min_length=1, max_length=200)
    event_name: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    target_users: list[RequestListText] = Field(
        min_length=1, max_length=_MAX_UPDATE_LIST_ITEMS
    )
    starts_on: date
    ends_on: date
    cutoff_on: date
    participation_rule: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    repeat_rule: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    rewards: list[RequestListText] = Field(
        min_length=1, max_length=_MAX_UPDATE_LIST_ITEMS
    )
    currencies: list[RequestListText] = Field(
        min_length=1, max_length=_MAX_UPDATE_LIST_ITEMS
    )
    probability_guarantee: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    monetization_policy: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    expiration_policy: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)


class PipelineRunRequest(EventBriefRequest):
    source_mode: Literal["fixture", "live", "import", "corpus"] = "fixture"
    fixture_case: Literal["black_market_2025", "weekly_supply_2025"] = "black_market_2025"
    steam_app_id: int | None = Field(default=None, ge=1)
    use_x: bool = False
    x_query: str = Field(default="PUBG Black Market", min_length=1, max_length=500)
    x_estimated_total_cost_usd: float = Field(default=0, ge=0, le=10)
    imported_csv: str | None = Field(default=None, max_length=_MAX_EVENT_CSV_BASE64)
    use_llm: bool = False
    llm_provider: Literal["claude", "openai"] = "claude"

    @model_validator(mode="after")
    def validate_source_payload(self) -> "PipelineRunRequest":
        if self.source_mode == "live" and not (self.steam_app_id or self.use_x):
            raise ValueError("live source requires steam_app_id or use_x")
        if self.source_mode == "import" and not self.imported_csv:
            raise ValueError("import source requires imported_csv")
        return self


class PipelineRunResponse(BaseModel):
    run_id: str
    result: dict


class UpdateRunRequest(BaseModel):
    """Validated, size-bounded public input for the update-only pipeline."""

    model_config = ConfigDict(extra="forbid")

    game: str = Field(min_length=1, max_length=200)
    update_name: str = Field(min_length=1, max_length=300)
    update_type: UpdateType
    current_state: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    change_summary: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    goal: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    expected_benefits: list[RequestListText] = Field(
        min_length=1, max_length=_MAX_UPDATE_LIST_ITEMS
    )
    concerns: list[RequestListText] = Field(
        min_length=1, max_length=_MAX_UPDATE_LIST_ITEMS
    )
    scope: str = Field(min_length=1, max_length=_MAX_UPDATE_TEXT)
    planned_on: date
    cutoff_on: date
    official_context_url: str | None = Field(
        default=None, min_length=8, max_length=2_000, pattern=r"^https://"
    )
    official_context: str | None = Field(
        default=None, min_length=1, max_length=_MAX_UPDATE_TEXT
    )
    details: UpdateDetails
    source_mode: Literal["fixture", "live", "import", "corpus"] = "fixture"
    fixture_case: Literal["dragunov_random_damage_removal"] = (
        "dragunov_random_damage_removal"
    )
    period_start: datetime | None = None
    period_end: datetime | None = None
    steam_app_id: int | None = Field(default=None, ge=1)
    use_x: bool = False
    x_query: str = Field(default="PUBG Dragunov damage", min_length=1, max_length=500)
    x_estimated_total_cost_usd: float = Field(default=0, ge=0, le=10)
    imported_csv: str | None = Field(default=None, max_length=_MAX_UPDATE_CSV_BYTES)
    use_llm: bool = True

    @model_validator(mode="before")
    @classmethod
    def reject_credential_fields(cls, value: Any) -> Any:
        """Keep credentials out of accepted payloads before they can be logged."""

        def has_forbidden_key(candidate: Any) -> bool:
            if isinstance(candidate, dict):
                for key, nested in candidate.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if (
                        normalized in _FORBIDDEN_CREDENTIAL_FIELD_NAMES
                        or normalized.endswith(("_api_key", "_token", "_secret"))
                    ):
                        return True
                    if has_forbidden_key(nested):
                        return True
            elif isinstance(candidate, list):
                return any(has_forbidden_key(item) for item in candidate)
            return False

        if has_forbidden_key(value):
            raise ValueError("credential fields are not accepted")
        return value

    @model_validator(mode="after")
    def validate_update_request(self) -> "UpdateRunRequest":
        if self.details.kind != self.update_type.value:
            raise ValueError("details kind must match update_type")
        if self.cutoff_on > self.planned_on:
            raise ValueError("cutoff_on must not be later than planned_on")
        if (
            self.source_mode == "fixture"
            and self.update_type is not UpdateType.WEAPON_BALANCE
        ):
            raise ValueError("Dragunov fixture requires weapon_balance update_type")
        if self.source_mode == "live":
            if not (self.steam_app_id or self.use_x):
                raise ValueError("live source requires steam_app_id or use_x")
            if self.period_start is None or self.period_end is None:
                raise ValueError("live source requires period_start and period_end")
            if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
                raise ValueError("live source period requires timezone-aware datetimes")
            if self.period_start >= self.period_end:
                raise ValueError("live source period_start must be earlier than period_end")
            cutoff_at = datetime.combine(self.cutoff_on, time.min, tzinfo=UTC)
            if self.period_end.astimezone(UTC) > cutoff_at:
                raise ValueError("live source period_end must not be later than cutoff_on")
        if self.source_mode == "import" and not self.imported_csv:
            raise ValueError("import source requires imported_csv")
        if self.imported_csv is not None:
            try:
                encoded_length = len(self.imported_csv.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError("imported_csv must be UTF-8 text") from exc
            if encoded_length > _MAX_UPDATE_CSV_BYTES:
                raise ValueError("imported_csv is limited to 2 MB")
        if any(
            len(value) > _MAX_UPDATE_TEXT
            for value in self.details.model_dump(mode="python").values()
            if isinstance(value, str)
        ):
            raise ValueError("update details exceed the allowed size")
        return self


class UpdateRunResult(BaseModel):
    """Only update-review artifacts safe for REST and SSE serialization."""

    model_config = ConfigDict(extra="forbid")

    brief: UpdateDecisionBrief
    feedback: UpdateFeedbackBundle
    evidence: UpdateEvidencePack
    impact: UpdateImpactAssessment
    validated: UpdateValidatedDecision
    events: list[ExecutionEvent]
    fallback_used: bool
    analysis_incomplete: bool
    llm_provider: Literal["deterministic", "claude"]
    llm_requested: bool


class UpdatePipelineRunResponse(BaseModel):
    run_id: str
    result: UpdateRunResult


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
