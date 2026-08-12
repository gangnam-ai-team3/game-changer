from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import StructuredModelError, parse_structured
from contracts import (
    ArtifactStatus,
    ErrorCode,
    EventBrief,
    EvidencePack,
    Producer,
    RiskCategory,
    RiskAssessment,
    RiskItem,
)
from policy import RISK_SPECS


class RiskNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RiskCategory
    title: str = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class RedteamNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[RiskNarrative]


class EventRedteamAgent:
    model = os.getenv("OPENAI_REDTEAM_MODEL", "gpt-5.6-terra")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, use_llm: bool = False, client=None) -> None:
        self.use_llm = use_llm
        self.client = client

    def run(self, event: EventBrief, pack: EvidencePack) -> RiskAssessment:
        base = self.run_deterministic(event, pack)
        if self.use_llm:
            narrative = parse_structured(
                model=self.model,
                prompt_path=self.prompt_path,
                output_type=RedteamNarrative,
                payload=base,
                client=self.client,
            )
            return self._merge_narrative(base, narrative)
        return base

    def run_deterministic(self, event: EventBrief, pack: EvidencePack) -> RiskAssessment:
        visible_languages = [
            insight.language for insight in pack.language_insights if insight.conclusion is not None
        ]
        risks: list[RiskItem] = []
        for issue in pack.issues:
            spec = RISK_SPECS.get(issue.category)
            if not spec:
                continue
            title, severity, personas, failure_path, question = spec
            risks.append(
                RiskItem(
                    risk_id=f"risk-{issue.category.value}",
                    category=issue.category,
                    title=title,
                    severity=severity,
                    affected_personas=personas,
                    affected_languages=visible_languages,
                    evidence_ids=issue.evidence_ids,
                    failure_path=failure_path,
                    revision_question=question,
                    confidence=issue.confidence,
                )
            )
        return RiskAssessment(
            run_id=event.run_id,
            status=ArtifactStatus.PARTIAL if pack.errors else ArtifactStatus.COMPLETE,
            producer=Producer.EVENT_REDTEAM,
            input_refs=[event.ref, pack.ref],
            errors=list(pack.errors),
            risks=risks,
        )

    @staticmethod
    def _merge_narrative(
        base: RiskAssessment, narrative: RedteamNarrative
    ) -> RiskAssessment:
        risks_by_category = {
            risk.category: (index, risk) for index, risk in enumerate(base.risks)
        }
        risks = list(base.risks)
        for proposal in narrative.risks:
            official = risks_by_category.get(proposal.category)
            if official is None or not set(proposal.evidence_ids) <= set(official[1].evidence_ids):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "LLM narrative references unknown risk evidence",
                )
            index, risk = official
            risks[index] = risk.model_copy(
                update={
                    "title": proposal.title,
                    "failure_path": proposal.failure_path,
                    "revision_question": proposal.revision_question,
                }
            )
        return base.model_copy(update={"risks": risks})
