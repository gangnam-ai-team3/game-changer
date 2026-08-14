from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import ClaudeBudget, StructuredModelError, parse_claude_structured, parse_structured, require_korean_text
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

    def __init__(self, use_llm: bool = False, client=None, provider: str | None = None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.provider = provider or ("openai" if client is not None else os.getenv("LLM_PROVIDER", "claude"))
        self.budget = budget

    def run(
        self,
        event: EventBrief,
        pack: EvidencePack,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> RiskAssessment:
        base = self.run_deterministic(event, pack, on_event=on_event)
        if self.use_llm:
            if self.provider == "claude":
                notify = on_event or (lambda _node, _message, _metrics: None)
                notify("claude_narrative", "Claude가 위험 설명과 실패 경로를 작성합니다.", {"provider": "claude"})
                narrative = parse_claude_structured(
                    model=os.getenv("CLAUDE_REDTEAM_MODEL", "claude-haiku-4-5"),
                    prompt_path=self.prompt_path,
                    output_type=RedteamNarrative,
                    payload=base,
                    client=self.client,
                    budget=self.budget,
                )
                require_korean_text(
                    [
                        text
                        for risk in narrative.risks
                        for text in (risk.title, risk.failure_path, risk.revision_question)
                    ]
                )
                notify("claude_output_checked", "Claude 위험 설명의 근거 연결을 확인했습니다.", {"provider": "claude"})
            else:
                narrative = parse_structured(
                    model=self.model,
                    prompt_path=self.prompt_path,
                    output_type=RedteamNarrative,
                    payload=base,
                    client=self.client,
                )
            return self._merge_narrative(base, narrative)
        return base

    def run_deterministic(
        self,
        event: EventBrief,
        pack: EvidencePack,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> RiskAssessment:
        notify = on_event or (lambda _node, _message, _metrics: None)
        visible_languages = [
            insight.language for insight in pack.language_insights if insight.conclusion is not None
        ]
        notify(
            "event_reviewed",
            "이벤트 조건과 공개 가능한 언어권을 검토했습니다.",
            {"languages": len(visible_languages)},
        )
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
        notify(
            "failure_paths_built",
            "위험별 실패 경로를 구성했습니다.",
            {"risks": len(risks)},
        )
        notify(
            "impact_linked",
            "영향 대상과 근거를 연결했습니다.",
            {"linked_risks": len(risks)},
        )
        notify(
            "risks_graded",
            "정책 위험 등급을 적용했습니다.",
            {"risks": len(risks)},
        )
        result = RiskAssessment(
            run_id=event.run_id,
            status=ArtifactStatus.PARTIAL if pack.errors else ArtifactStatus.COMPLETE,
            producer=Producer.EVENT_REDTEAM,
            input_refs=[event.ref, pack.ref],
            errors=list(pack.errors),
            risks=risks,
        )
        notify(
            "assessment_ready",
            "RiskAssessment 계약을 통과했습니다.",
            {"risks": len(risks)},
        )
        return result

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
