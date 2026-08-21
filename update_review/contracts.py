from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import (
    Artifact,
    InputMode,
    Language,
    LanguageSample,
    PersonaKind,
    SearchRecord,
    Severity,
    SourceType,
)


class UpdateType(StrEnum):
    WEAPON_BALANCE = "weapon_balance"
    UI_UX = "ui_ux"
    SYSTEM_RULES = "system_rules"


class EvidencePeriod(StrEnum):
    BEFORE = "before"
    AFTER = "after"
    COMPARABLE_REFERENCE = "comparable_reference"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class UpdateDecision(StrEnum):
    GO = "Go"
    REVISE = "Revise"
    TEST = "Test"
    HOLD = "Hold"


class UpdateRiskCategory(StrEnum):
    BALANCE_REGRESSION = "balance_regression"
    FAIRNESS_REGRESSION = "fairness_regression"
    INFORMATION_CLARITY = "information_clarity"
    FLOW_DISRUPTION = "flow_disruption"
    RULE_EXCEPTION = "rule_exception"
    LEARNING_BURDEN = "learning_burden"


class WeaponBalanceDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["weapon_balance"] = "weapon_balance"
    target_weapon: str = Field(min_length=1)
    damage: str = Field(min_length=1)
    recoil: str = Field(min_length=1)
    rate_of_fire: str = Field(min_length=1)
    ammunition: str = Field(min_length=1)
    spawn_and_modes: str = Field(min_length=1)


class UiUxDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ui_ux"] = "ui_ux"
    changed_screen: str = Field(min_length=1)
    user_journey: str = Field(min_length=1)
    exposed_information: str = Field(min_length=1)
    possible_errors: str = Field(min_length=1)


class SystemRulesDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["system_rules"] = "system_rules"
    participation_conditions: str = Field(min_length=1)
    rewards: str = Field(min_length=1)
    restrictions: str = Field(min_length=1)
    exception_rules: str = Field(min_length=1)
    existing_user_impact: str = Field(min_length=1)


UpdateDetails = Annotated[
    WeaponBalanceDetails | UiUxDetails | SystemRulesDetails,
    Field(discriminator="kind"),
]


class UpdateBrief(Artifact):
    game: str = Field(min_length=1)
    update_name: str = Field(min_length=1)
    update_type: UpdateType
    current_state: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_benefits: list[str] = Field(min_length=1)
    concerns: list[str] = Field(min_length=1)
    scope: str = Field(min_length=1)
    planned_at: datetime
    cutoff_at: datetime
    official_context: str | None = Field(default=None, min_length=1)
    official_context_url: str | None = Field(default=None, pattern=r"^https://")
    details: UpdateDetails

    @model_validator(mode="after")
    def validate_update(self) -> UpdateBrief:
        if self.cutoff_at > self.planned_at:
            raise ValueError("cutoff_at must not be later than planned_at")
        if self.cutoff_at.tzinfo is None or self.planned_at.tzinfo is None:
            raise ValueError("update datetimes must be timezone-aware")
        if self.details.kind != self.update_type.value:
            raise ValueError("details kind must match update_type")
        return self


class UpdateEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    source: SourceType
    source_url: str = Field(pattern=r"^https://")
    source_id: str = Field(min_length=8)
    language: Language
    observed_at: datetime
    period: EvidencePeriod
    sentiment: Sentiment
    summary: str = Field(min_length=8, max_length=500)
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)
    synthetic: bool = False
    contains_personal_data: Literal[False] = False


class UpdateFeedbackBundle(Artifact):
    input_mode: InputMode
    cutoff_at: datetime
    search_log: list[SearchRecord]
    samples: list[LanguageSample]
    evidence: list[UpdateEvidenceItem]

    @model_validator(mode="after")
    def validate_bundle(self) -> UpdateFeedbackBundle:
        if len({sample.language for sample in self.samples}) != len(self.samples):
            raise ValueError("language samples must be unique")
        leaked = [item.evidence_id for item in self.evidence if item.observed_at >= self.cutoff_at]
        if leaked:
            raise ValueError(f"cutoff leakage: {', '.join(leaked[:3])}")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return self


class ReactionSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    sentiment: Sentiment
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    def validate_refs(self, evidence_ids: set[str]) -> ReactionSignal:
        unknown = set(self.evidence_ids) - evidence_ids
        if unknown:
            raise ValueError(f"unknown evidence: {', '.join(sorted(unknown))}")
        return self


class SplitCondition(ReactionSignal):
    sentiment: Literal[Sentiment.MIXED] = Sentiment.MIXED


class UpdateLanguageInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    conclusion: str | None
    hidden_reason: str | None = None
    sentiment_counts: dict[Sentiment, int]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def explain_hidden_conclusion(self) -> UpdateLanguageInsight:
        if self.conclusion is None and not self.hidden_reason:
            raise ValueError("a hidden conclusion requires hidden_reason")
        return self


class UpdatePersonaImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: PersonaKind
    expected_reaction: str = Field(min_length=1)
    positive_signal_ids: list[str]
    negative_signal_ids: list[str]
    split_signal_ids: list[str]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_evidence_only_for_linked_signals(self) -> UpdatePersonaImpact:
        signal_ids = (
            self.positive_signal_ids
            + self.negative_signal_ids
            + self.split_signal_ids
        )
        if signal_ids and not self.evidence_ids:
            raise ValueError("linked persona signal requires evidence")
        if not signal_ids and (self.evidence_ids or self.confidence != 0):
            raise ValueError("unlinked persona cannot claim evidence or confidence")
        return self


class UpdateEvidencePack(Artifact):
    positive_signals: list[ReactionSignal]
    negative_signals: list[ReactionSignal]
    split_conditions: list[SplitCondition]
    persona_impacts: list[UpdatePersonaImpact]
    language_insights: list[UpdateLanguageInsight]
    evidence: list[UpdateEvidenceItem]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateEvidencePack:
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        evidence_ids = set(evidence_by_id)
        signals = [*self.positive_signals, *self.negative_signals, *self.split_conditions]
        if any(item.sentiment is not Sentiment.POSITIVE for item in self.positive_signals):
            raise ValueError("positive_signals must use positive sentiment")
        if any(item.sentiment is not Sentiment.NEGATIVE for item in self.negative_signals):
            raise ValueError("negative_signals must use negative sentiment")
        signal_ids = {item.signal_id for item in signals}
        for signal in signals:
            signal.validate_refs(evidence_ids)
        for signal in self.positive_signals:
            if any(
                evidence_by_id[item_id].sentiment is not Sentiment.POSITIVE
                for item_id in signal.evidence_ids
            ):
                raise ValueError("positive signal references non-positive evidence")
        for signal in self.negative_signals:
            if any(
                evidence_by_id[item_id].sentiment is not Sentiment.NEGATIVE
                for item_id in signal.evidence_ids
            ):
                raise ValueError("negative signal references non-negative evidence")
        for signal in self.split_conditions:
            if any(
                evidence_by_id[item_id].sentiment is not Sentiment.MIXED
                for item_id in signal.evidence_ids
            ):
                raise ValueError("split condition references non-mixed evidence")
        for impact in self.persona_impacts:
            if not set(impact.evidence_ids) <= evidence_ids:
                raise ValueError("persona impact references unknown evidence")
            impact_signal_ids = (
                impact.positive_signal_ids
                + impact.negative_signal_ids
                + impact.split_signal_ids
            )
            if not set(impact_signal_ids) <= signal_ids:
                raise ValueError("persona impact references unknown signal")
        for insight in self.language_insights:
            if not set(insight.evidence_ids) <= evidence_ids:
                raise ValueError("language insight references unknown evidence")
        return self


class ExpectedImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    affected_personas: list[PersonaKind] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class UpdateRiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1)
    category: UpdateRiskCategory
    title: str = Field(min_length=1)
    severity: Severity
    affected_personas: list[PersonaKind] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ValidationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    success_condition: str = Field(min_length=1)
    addresses_risk_ids: list[str] = Field(min_length=1)


class UpdateImpactAssessment(Artifact):
    expected_positive: list[ExpectedImpact]
    expected_negative: list[ExpectedImpact]
    risks: list[UpdateRiskItem]
    validation_metrics: list[ValidationMetric]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateImpactAssessment:
        risk_ids = {item.risk_id for item in self.risks}
        evidence_ids = {
            evidence_id
            for item in [*self.expected_positive, *self.expected_negative, *self.risks]
            for evidence_id in item.evidence_ids
        }
        if not evidence_ids and not self.errors:
            raise ValueError("impact assessment requires evidence")
        for metric in self.validation_metrics:
            if not set(metric.addresses_risk_ids) <= risk_ids:
                raise ValueError("metric references unknown risk")
        if risk_ids and not all(
            any(risk_id in metric.addresses_risk_ids for metric in self.validation_metrics)
            for risk_id in risk_ids
        ):
            raise ValueError("every risk requires a validation metric")
        return self


class RejectedUpdateRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class UpdateRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int = Field(ge=1)
    title: str = Field(min_length=1)
    action: str = Field(min_length=1)
    addresses_risk_ids: list[str] = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class UpdateValidatedDecision(Artifact):
    decision: UpdateDecision
    decision_reason: str = Field(min_length=1)
    validated_risks: list[UpdateRiskItem]
    rejected_risks: list[RejectedUpdateRisk]
    recommendations: list[UpdateRecommendation]
    validation_metrics: list[ValidationMetric]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateValidatedDecision:
        risk_ids = {item.risk_id for item in self.validated_risks}
        metric_ids = {item.metric_id for item in self.validation_metrics}
        for item in self.recommendations:
            if not set(item.addresses_risk_ids) <= risk_ids:
                raise ValueError("recommendation references unknown risk")
            if not set(item.validation_metric_ids) <= metric_ids:
                raise ValueError("recommendation references unknown metric")
        return self


class UpdateDecisionBrief(Artifact):
    decision: UpdateDecision
    executive_summary: str = Field(min_length=1)
    official_context: str | None = Field(default=None, min_length=1)
    official_context_url: str | None = Field(default=None, pattern=r"^https://")
    expected_positive: list[ExpectedImpact]
    expected_negative: list[ExpectedImpact]
    split_conditions: list[SplitCondition]
    persona_impacts: list[UpdatePersonaImpact]
    language_insights: list[UpdateLanguageInsight]
    top_risks: list[UpdateRiskItem]
    validation_metrics: list[ValidationMetric]
    evidence: list[UpdateEvidenceItem]
    recommendations: list[UpdateRecommendation]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateDecisionBrief:
        evidence_ids = {item.evidence_id for item in self.evidence}
        risk_ids = {item.risk_id for item in self.top_risks}
        metric_ids = {item.metric_id for item in self.validation_metrics}
        linked_evidence = [
            *self.expected_positive,
            *self.expected_negative,
            *self.top_risks,
            *self.split_conditions,
            *self.persona_impacts,
            *self.language_insights,
        ]
        for item in linked_evidence:
            if not set(item.evidence_ids) <= evidence_ids:
                raise ValueError("brief references unknown evidence")
        for metric in self.validation_metrics:
            if not set(metric.addresses_risk_ids) <= risk_ids:
                raise ValueError("brief metric references unknown risk")
        for item in self.recommendations:
            risk_refs_valid = set(item.addresses_risk_ids) <= risk_ids
            metric_refs_valid = set(item.validation_metric_ids) <= metric_ids
            if not risk_refs_valid or not metric_refs_valid:
                raise ValueError("brief recommendation references unknown data")
        return self
