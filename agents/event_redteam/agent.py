from __future__ import annotations

import os
from pathlib import Path

from agents.structured import parse_structured
from contracts import (
    ArtifactStatus,
    EventBrief,
    EvidencePack,
    Producer,
    RiskAssessment,
    RiskItem,
)
from policy import RISK_SPECS


class EventRedteamAgent:
    model = os.getenv("OPENAI_REDTEAM_MODEL", "gpt-5.6-terra")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, use_llm: bool = False, client=None) -> None:
        self.use_llm = use_llm
        self.client = client

    def run(self, event: EventBrief, pack: EvidencePack) -> RiskAssessment:
        if self.use_llm:
            return parse_structured(
                model=self.model,
                prompt_path=self.prompt_path,
                output_type=RiskAssessment,
                payload={"event": event.model_dump(mode="json"), "evidence_pack": pack.model_dump(mode="json")},
                client=self.client,
            )

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
