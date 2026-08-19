from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import ClaudeBudget, parse_claude_structured, parse_structured, require_native_business_korean
from policy import MIN_RISK_CONFIDENCE, REVISION_SPECS, decide, expected_severity
from contracts import (
    ArtifactStatus,
    Decision,
    DecisionBrief,
    EventBrief,
    EvidencePack,
    FeedbackBundle,
    PersonaResult,
    Producer,
    RejectedRisk,
    RevisionAction,
    RiskAssessment,
    Severity,
    ValidatedDecision,
    RiskCategory,
)


class RevisionNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RiskCategory
    title: str = Field(min_length=1)
    change: str = Field(min_length=1)
    success_metric: str = Field(min_length=1)


class AuditNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_narrative: str = Field(min_length=1)
    revisions: list[RevisionNarrative]


class AuditStrategyAgent:
    model = os.getenv("OPENAI_AUDIT_MODEL", "gpt-5.6-terra")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, use_llm: bool = False, client=None, provider: str | None = None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.provider = provider or ("openai" if client is not None else os.getenv("LLM_PROVIDER", "claude"))
        self.budget = budget

    def run(
        self,
        bundle: FeedbackBundle,
        pack: EvidencePack,
        assessment: RiskAssessment,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> ValidatedDecision:
        base = self.run_deterministic(bundle, pack, assessment, on_event=on_event)
        if self.use_llm:
            if self.provider == "claude":
                notify = on_event or (lambda _node, _message, _metrics: None)
                notify("claude_narrative", "Claude가 최종 설명과 개선안 문구를 작성합니다.", {"provider": "claude"})
                narrative = parse_claude_structured(
                    model=os.getenv(
                        "CLAUDE_AUDIT_MODEL", "claude-haiku-4-5-20251001"
                    ),
                    prompt_path=self.prompt_path,
                    output_type=AuditNarrative,
                    payload=base,
                    client=self.client,
                    budget=self.budget,
                )
                require_native_business_korean(
                    [narrative.decision_narrative]
                    + [
                        text
                        for revision in narrative.revisions
                        for text in (revision.title, revision.change, revision.success_metric)
                    ]
                )
                notify("claude_output_checked", "최종 Go·Revise·Hold 판정은 코드 정책으로 재확인했습니다.", {"provider": "claude"})
            else:
                narrative = parse_structured(
                    model=self.model,
                    prompt_path=self.prompt_path,
                    output_type=AuditNarrative,
                    payload=base,
                    client=self.client,
                )
            return self._merge_narrative(base, narrative)
        return base

    def run_deterministic(
        self,
        bundle: FeedbackBundle,
        pack: EvidencePack,
        assessment: RiskAssessment,
        *,
        analysis_incomplete: bool = False,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> ValidatedDecision:
        notify = on_event or (lambda _node, _message, _metrics: None)
        evidence_by_id = {item.evidence_id: item for item in pack.evidence}
        validated = []
        rejected = []
        for risk in assessment.risks:
            expected = expected_severity(risk.category)
            linked = [evidence_by_id[item_id] for item_id in risk.evidence_ids if item_id in evidence_by_id]
            grounded = len(linked) == len(risk.evidence_ids) and all(
                risk.category.value in item.mechanism_tags for item in linked
            )
            if expected is None:
                rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="MVP 닫힌 위험 분류표 외 범주"))
            elif not grounded:
                rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="위험 범주와 연결 근거 불일치"))
            elif risk.severity != expected:
                rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="정책 위험 등급 불일치"))
            elif risk.confidence < MIN_RISK_CONFIDENCE:
                rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="근거 신뢰도 0.5 미만"))
            else:
                validated.append(risk)

        notify(
            "evidence_checked",
            "위험 근거의 존재와 메커니즘 연결을 확인했습니다.",
            {"evidence": len(evidence_by_id)},
        )
        notify(
            "risks_validated",
            "위험을 정책 기준으로 검증했습니다.",
            {"validated": len(validated), "rejected": len(rejected)},
        )

        decision, reason = decide(
            bundle.samples,
            validated,
            analysis_incomplete=analysis_incomplete,
        )
        notify(
            "sample_gate_applied",
            "언어권 표본 기준을 판단에 적용했습니다.",
            {"analysis_incomplete": analysis_incomplete},
        )
        notify(
            "decision_fixed",
            "의사결정 상태를 확정했습니다.",
            {"decision": decision.value},
        )

        revisions = []
        for priority, risk in enumerate(validated, start=1):
            title, change, metric = REVISION_SPECS[risk.category]
            revisions.append(
                RevisionAction(
                    priority=priority,
                    title=title,
                    change=change,
                    success_metric=metric,
                    addresses_risk_ids=[risk.risk_id],
                )
            )
        result = ValidatedDecision(
            run_id=assessment.run_id,
            status=ArtifactStatus.PARTIAL if assessment.errors else ArtifactStatus.COMPLETE,
            producer=Producer.AUDIT_STRATEGY,
            input_refs=[bundle.ref, pack.ref, assessment.ref],
            errors=list(assessment.errors),
            decision=decision,
            decision_reason=reason,
            validated_risks=validated,
            rejected_risks=rejected,
            priority_revisions=revisions,
        )
        notify(
            "revisions_built",
            "우선 수정안을 구성했습니다.",
            {"revisions": len(revisions)},
        )
        return result

    @staticmethod
    def _merge_narrative(
        base: ValidatedDecision, narrative: AuditNarrative
    ) -> ValidatedDecision:
        proposals = {proposal.category: proposal for proposal in narrative.revisions}
        categories_by_risk_id = {
            risk.risk_id: risk.category for risk in base.validated_risks
        }
        revisions = []
        for revision in base.priority_revisions:
            category = categories_by_risk_id[revision.addresses_risk_ids[0]]
            proposal = proposals.get(category)
            revisions.append(
                revision
                if proposal is None
                else revision.model_copy(
                    update={
                        "title": proposal.title,
                        "change": proposal.change,
                        "success_metric": proposal.success_metric,
                    }
                )
            )
        return base.model_copy(
            update={
                "decision_narrative": narrative.decision_narrative,
                "priority_revisions": revisions,
            }
        )

    def to_brief(
        self,
        event: EventBrief,
        pack: EvidencePack,
        decision: ValidatedDecision,
    ) -> DecisionBrief:
        severity_rank = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
        }
        top_risks = sorted(
            decision.validated_risks,
            key=lambda risk: (severity_rank[risk.severity], risk.confidence),
            reverse=True,
        )[:5]
        panel_results = []
        for persona in pack.personas:
            risks = [risk for risk in top_risks if persona.kind in risk.affected_personas]
            risk_titles = ", ".join(risk.title for risk in risks)
            panel_results.append(
                PersonaResult(
                    persona=persona.kind,
                    reaction=(
                        f"{risk_titles} 위험 때문에 원안 참여와 지출 의사가 약해질 수 있습니다."
                        if risks
                        else "상위 위험에서 직접적인 영향은 예상되지 않습니다."
                    ),
                    risk_ids=[risk.risk_id for risk in risks],
                    evidence_ids=persona.evidence_ids,
                    confidence=persona.confidence,
                )
            )
        decision_labels = {
            Decision.GO: "출시 가능",
            Decision.REVISE: "수정 필요",
            Decision.HOLD: "판정 보류",
        }
        visible_languages = sum(
            insight.conclusion is not None for insight in pack.language_insights
        )
        risk_summary = (
            f"우선 확인할 위험은 {', '.join(risk.title.replace('·', ', ') for risk in top_risks[:3])}입니다."
            if top_risks
            else "현재 자료에서는 우선 수정이 필요한 위험이 확인되지 않았습니다."
        )
        executive_summary = (
            f"{event.event_name}의 출시 판단은 {decision_labels[decision.decision]}입니다. "
            f"출시 전 자료를 바탕으로 이용자 유형 {len(panel_results)}개와 "
            f"결론을 공개할 수 있는 언어권 {visible_languages}개의 예상 반응을 종합했습니다. "
            f"{risk_summary} 따라서 {decision.decision_reason}"
        )
        return DecisionBrief(
            run_id=event.run_id,
            status=decision.status,
            producer=Producer.ORCHESTRATOR,
            input_refs=[event.ref, pack.ref, decision.ref],
            errors=list(decision.errors),
            decision=decision.decision,
            executive_summary=executive_summary,
            top_risks=top_risks,
            language_results=pack.language_insights,
            panel_results=panel_results,
            evidence=pack.evidence,
            revision_plan=decision.priority_revisions,
            exploratory_insights=pack.exploratory_insights,
        )
