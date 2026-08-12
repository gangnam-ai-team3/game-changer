from __future__ import annotations

import os
from pathlib import Path

from agents.structured import parse_structured
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
    RiskCategory,
    Severity,
    ValidatedDecision,
)

REVISION_SPECS = {
    RiskCategory.DOUBLE_GACHA: (
        "2단계 확률 제거",
        "Loot Cache와 Prime Parcel을 단일 Cargo 직접 보상 구조로 통합한다.",
        "모든 목표 보상의 단일 단계 확률과 최대 획득 비용을 화면에서 확인 가능",
    ),
    RiskCategory.FRAGMENTED_FLOW: (
        "이벤트 허브 통합",
        "구매, 개봉, 획득 보상, 토큰, 제작 진행을 한 Supply Bay 화면에 모은다.",
        "목표 보상 제작까지 필요한 핵심 동작을 한 화면에서 완료",
    ),
    RiskCategory.OPAQUE_PROGRESS: (
        "확정 마일스톤 추가",
        "개봉 횟수별 토큰·재료·최종 보상 마일스톤을 사전에 공개한다.",
        "모든 유료 경로에 보이는 진행도와 고정 상한 존재",
    ),
    RiskCategory.RANDOM_BONUS: (
        "보너스 결정성 강화",
        "확률형 보너스 일부를 개봉당 고정 토큰과 누적 마일스톤으로 교체한다.",
        "동일 지출의 최소 진행량 편차 0",
    ),
    RiskCategory.EXPIRING_CURRENCY: (
        "잔여 재화 보호",
        "종료 후 유예 기간과 잔여 토큰의 상시 재화 자동 전환을 제공한다.",
        "미사용 유료 기원 재화의 무보상 삭제 0건",
    ),
}


class AuditStrategyAgent:
    model = os.getenv("OPENAI_AUDIT_MODEL", "gpt-5.6-terra")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, use_llm: bool = False, client=None) -> None:
        self.use_llm = use_llm
        self.client = client

    def run(
        self,
        bundle: FeedbackBundle,
        pack: EvidencePack,
        assessment: RiskAssessment,
    ) -> ValidatedDecision:
        if self.use_llm:
            return parse_structured(
                model=self.model,
                prompt_path=self.prompt_path,
                output_type=ValidatedDecision,
                payload={
                    "samples": [sample.model_dump(mode="json") for sample in bundle.samples],
                    "evidence_ids": [item.evidence_id for item in pack.evidence],
                    "risk_assessment": assessment.model_dump(mode="json"),
                },
                client=self.client,
            )

        evidence_ids = {item.evidence_id for item in pack.evidence}
        validated = []
        rejected = []
        for risk in assessment.risks:
            unknown = set(risk.evidence_ids) - evidence_ids
            if unknown:
                rejected.append(
                    RejectedRisk(
                        risk_id=risk.risk_id,
                        reason=f"존재하지 않는 근거 ID 참조: {', '.join(sorted(unknown))}",
                    )
                )
            elif risk.confidence < 0.5:
                rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="근거 신뢰도 0.5 미만"))
            else:
                validated.append(risk)

        insufficient = sum(not sample.sufficient for sample in bundle.samples)
        has_critical = any(risk.severity == Severity.CRITICAL for risk in validated)
        has_high = any(risk.severity == Severity.HIGH for risk in validated)
        if has_critical:
            decision = Decision.HOLD
            reason = "검증된 Critical 위험이 있어 출시 판단을 보류한다."
        elif insufficient >= 3:
            decision = Decision.HOLD
            reason = "세 언어권 이상이 최소 표본에 미달해 판단 근거가 부족하다."
        elif has_high:
            decision = Decision.REVISE
            reason = "검증된 High 위험을 수정한 뒤 재검토해야 한다."
        elif insufficient:
            decision = Decision.REVISE
            reason = "일부 언어권 표본을 보강한 뒤 출시 판단을 갱신해야 한다."
        else:
            decision = Decision.GO
            reason = "필수 표본을 충족했고 High 이상 검증 위험이 없다."

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
        return ValidatedDecision(
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
            panel_results.append(
                PersonaResult(
                    persona=persona.kind,
                    reaction=(
                        f"{len(risks)}개 우선 위험 때문에 원안 참여·지출 의사가 약해질 수 있음."
                        if risks
                        else "상위 위험에서 직접 영향이 확인되지 않음."
                    ),
                    risk_ids=[risk.risk_id for risk in risks],
                    evidence_ids=persona.evidence_ids,
                    confidence=persona.confidence,
                )
            )
        return DecisionBrief(
            run_id=event.run_id,
            status=decision.status,
            producer=Producer.ORCHESTRATOR,
            input_refs=[event.ref, pack.ref, decision.ref],
            errors=list(decision.errors),
            decision=decision.decision,
            executive_summary=f"{event.event_name}: {decision.decision.value}. {decision.decision_reason}",
            top_risks=top_risks,
            language_results=pack.language_insights,
            panel_results=panel_results,
            evidence=pack.evidence,
            revision_plan=decision.priority_revisions,
        )
