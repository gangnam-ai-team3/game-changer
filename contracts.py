from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class ErrorCode(StrEnum):
    AUTH_FAILED = "AUTH_FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    INVALID_IMPORT = "INVALID_IMPORT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    LLM_REFUSAL = "LLM_REFUSAL"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class ArtifactStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class Producer(StrEnum):
    USER = "user"
    COLLECTOR = "collector"
    EVIDENCE_RAG = "evidence_rag"
    EVENT_REDTEAM = "event_redteam"
    AUDIT_STRATEGY = "audit_strategy"
    ORCHESTRATOR = "orchestrator"


class Language(StrEnum):
    ENGLISH = "en"
    KOREAN = "ko"
    CHINESE_SIMPLIFIED = "zh-CN"
    SPANISH = "es"
    PORTUGUESE_BRAZIL = "pt-BR"


SUPPORTED_LANGUAGES = tuple(Language)


class SourceType(StrEnum):
    STEAM = "steam"
    X = "x"
    REDDIT_IMPORT = "reddit_import"
    THREADS_IMPORT = "threads_import"
    INSTAGRAM_IMPORT = "instagram_import"
    SYNTHETIC = "synthetic"


class InputMode(StrEnum):
    FIXTURE = "fixture"
    LIVE = "live"
    IMPORT = "import"


class Decision(StrEnum):
    GO = "Go"
    REVISE = "Revise"
    HOLD = "Hold"


class Severity(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class PersonaKind(StrEnum):
    TIME_CONSTRAINED = "time_constrained_casual_returning"
    VALUE_SEEKING = "value_seeking_free_low_spend"
    COLLECTOR = "collector_high_engagement"
    CORE_GAMEPLAY = "core_combat_first"


class RiskCategory(StrEnum):
    DOUBLE_GACHA = "double_gacha"
    FRAGMENTED_FLOW = "fragmented_flow"
    OPAQUE_PROGRESS = "opaque_progress"
    RANDOM_BONUS = "random_bonus"
    EXPIRING_CURRENCY = "expiring_currency"
    GRIND_PRESSURE = "grind_pressure"
    FAIRNESS = "fairness"
    LOCALIZATION = "localization"


class PipelineError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool = False


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    policy_version: str = "1.0"
    input_snapshot_hash: str = Field(default="pending", pattern=r"^(pending|[0-9a-f]{64})$")
    status: ArtifactStatus = ArtifactStatus.COMPLETE
    producer: Producer
    input_refs: list[str] = Field(default_factory=list)
    errors: list[PipelineError] = Field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.producer.value}:{self.run_id}"


class EventBrief(Artifact):
    game: str = Field(min_length=1)
    event_name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    target_users: list[str] = Field(min_length=1)
    participation_rule: str = Field(min_length=1)
    repeat_rule: str = Field(min_length=1)
    rewards: list[str] = Field(min_length=1)
    currencies: list[str] = Field(min_length=1)
    probability_guarantee: str = Field(min_length=1)
    monetization_policy: str = Field(min_length=1)
    expiration_policy: str = Field(min_length=1)
    cutoff_at: datetime

    @model_validator(mode="after")
    def validate_dates(self) -> EventBrief:
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be earlier than ends_at")
        if self.cutoff_at > self.starts_at:
            raise ValueError("cutoff_at must not be later than starts_at")
        if any(value.tzinfo is None for value in (self.starts_at, self.ends_at, self.cutoff_at)):
            raise ValueError("event datetimes must be timezone-aware")
        return self


class SearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceType
    language: Language
    query: str = Field(min_length=1)
    requested_at: datetime
    result_count: int = Field(ge=0)
    estimated_cost_usd: float = Field(default=0, ge=0)


class LanguageSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    general_count: int = Field(ge=0)
    mechanism_count: int = Field(ge=0)

    @property
    def sufficient(self) -> bool:
        return self.general_count >= 100 and self.mechanism_count >= 15


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    source: SourceType
    source_url: str = Field(pattern=r"^https://")
    source_id: str = Field(min_length=8)
    language: Language
    observed_at: datetime
    summary: str = Field(min_length=8, max_length=500)
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)
    synthetic: bool = False
    contains_personal_data: Literal[False] = False


class FeedbackBundle(Artifact):
    input_mode: InputMode
    cutoff_at: datetime
    search_log: list[SearchRecord]
    samples: list[LanguageSample]
    evidence: list[EvidenceItem]

    @model_validator(mode="after")
    def validate_bundle(self) -> FeedbackBundle:
        if len({sample.language for sample in self.samples}) != len(self.samples):
            raise ValueError("language samples must be unique")
        leaked = [item.evidence_id for item in self.evidence if item.observed_at >= self.cutoff_at]
        if leaked:
            raise ValueError(f"cutoff leakage: {', '.join(leaked[:3])}")
        ids = [item.evidence_id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("evidence_id values must be unique")
        return self


class MechanismIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    category: RiskCategory
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class LanguageInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    conclusion: str | None
    hidden_reason: str | None = None
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def explain_hidden_conclusion(self) -> LanguageInsight:
        if self.conclusion is None and not self.hidden_reason:
            raise ValueError("a hidden conclusion requires hidden_reason")
        return self


class ExploratoryInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PersonaKind
    label: str = Field(min_length=1)
    motivations: list[str] = Field(min_length=1)
    churn_triggers: list[str] = Field(min_length=1)
    play_constraints: list[str] = Field(min_length=1)
    payment_sensitivity: str = Field(min_length=1)
    language_differences: dict[Language, str]
    evidence_ids: list[str] = Field(min_length=15)
    confidence: float = Field(ge=0, le=1)


class EvidencePack(Artifact):
    issues: list[MechanismIssue]
    language_insights: list[LanguageInsight]
    evidence: list[EvidenceItem]
    personas: list[Persona]
    exploratory_insights: list[ExploratoryInsight] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_refs(self) -> EvidencePack:
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        linked = [*self.issues, *self.language_insights, *self.personas, *self.exploratory_insights]
        for item in linked:
            unknown = set(item.evidence_ids) - evidence_by_id.keys()
            if unknown:
                raise ValueError(f"unknown evidence: {', '.join(sorted(unknown))}")
        for issue in self.issues:
            if any(
                issue.category.value not in evidence_by_id[item_id].mechanism_tags
                for item_id in issue.evidence_ids
            ):
                raise ValueError("issue category does not match evidence tags")
        return self


class RiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1)
    category: RiskCategory
    title: str = Field(min_length=1)
    severity: Severity
    affected_personas: list[PersonaKind] = Field(min_length=1)
    affected_languages: list[Language]
    evidence_ids: list[str] = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class RiskAssessment(Artifact):
    risks: list[RiskItem]


class RejectedRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RevisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int = Field(ge=1)
    title: str = Field(min_length=1)
    change: str = Field(min_length=1)
    success_metric: str = Field(min_length=1)
    addresses_risk_ids: list[str] = Field(min_length=1)


class ValidatedDecision(Artifact):
    decision: Decision
    decision_reason: str = Field(min_length=1)
    validated_risks: list[RiskItem]
    rejected_risks: list[RejectedRisk]
    priority_revisions: list[RevisionAction]

    @model_validator(mode="after")
    def validate_revision_risk_refs(self) -> ValidatedDecision:
        validated_ids = {risk.risk_id for risk in self.validated_risks}
        for revision in self.priority_revisions:
            if not set(revision.addresses_risk_ids) <= validated_ids:
                raise ValueError("revision references unvalidated risk")
        return self


class PersonaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: PersonaKind
    reaction: str = Field(min_length=1)
    risk_ids: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DecisionBrief(Artifact):
    decision: Decision
    executive_summary: str = Field(min_length=1)
    top_risks: list[RiskItem]
    language_results: list[LanguageInsight]
    panel_results: list[PersonaResult]
    evidence: list[EvidenceItem]
    revision_plan: list[RevisionAction]
    exploratory_insights: list[ExploratoryInsight] = Field(default_factory=list)
