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
    Language,
    PersonaKind,
    PersonaResult,
    Producer,
    RejectedRisk,
    RevisionAction,
    RiskAssessment,
    Severity,
    ValidatedDecision,
    RiskCategory,
)


EVENT_PERSONA_REACTIONS = {
    (PersonaKind.VALUE_SEEKING, RiskCategory.DOUBLE_GACHA): (
        "원하는 보상을 얻기까지 얼마를 써야 하는지 알 수 없다면 결제하기 어렵습니다.",
        "최대 비용과 보장 경로가 공개될 때까지 구매를 미룰 가능성이 있습니다.",
    ),
    (PersonaKind.COLLECTOR, RiskCategory.DOUBLE_GACHA): (
        "상자를 열고 다시 확률 보상을 거쳐야 한다면 목표 아이템을 모으는 데 필요한 비용을 가늠하기 어렵습니다.",
        "수집을 시작하지 않거나 확정 보상이 있는 경로만 선택할 가능성이 있습니다.",
    ),
    (PersonaKind.TIME_CONSTRAINED, RiskCategory.FRAGMENTED_FLOW): (
        "짧게 접속했는데 구매와 제작 화면을 계속 오가야 한다면 참여를 끝내기 어려울 것 같습니다.",
        "미션을 시작하지 않거나 보상을 받기 전에 이탈할 가능성이 있습니다.",
    ),
    (PersonaKind.COLLECTOR, RiskCategory.FRAGMENTED_FLOW): (
        "보상과 재료가 여러 화면에 나뉘면 무엇을 얼마나 모았는지 놓칠 것 같습니다.",
        "진행 상황을 확인하기 어려우면 수집을 중단할 가능성이 있습니다.",
    ),
    (PersonaKind.CORE_GAMEPLAY, RiskCategory.FRAGMENTED_FLOW): (
        "전투보다 구매와 제작 화면을 확인하는 데 시간이 더 들면 이벤트에 참여하고 싶지 않습니다.",
        "핵심 보상만 확인하거나 이벤트 참여를 건너뛸 가능성이 있습니다.",
    ),
    (PersonaKind.TIME_CONSTRAINED, RiskCategory.OPAQUE_PROGRESS): (
        "몇 번 더 해야 끝나는지 보이지 않으면 제한된 시간에 참여할지 결정하기 어렵습니다.",
        "남은 횟수가 공개되지 않으면 참여를 미룰 가능성이 있습니다.",
    ),
    (PersonaKind.VALUE_SEEKING, RiskCategory.OPAQUE_PROGRESS): (
        "목표 보상까지 남은 비용을 알 수 없다면 결제하기 어렵습니다.",
        "비용 상한이 보일 때까지 구매를 보류할 가능성이 있습니다.",
    ),
    (PersonaKind.COLLECTOR, RiskCategory.OPAQUE_PROGRESS): (
        "진행도가 보이지 않으면 끝까지 모을 수 있을지 확신하기 어렵습니다.",
        "확정 마일스톤이 없다면 수집을 중단할 가능성이 있습니다.",
    ),
    (PersonaKind.VALUE_SEEKING, RiskCategory.RANDOM_BONUS): (
        "같은 금액을 써도 누군가는 더 많은 보너스를 받는다면 불공정하다고 느낄 것 같습니다.",
        "고정 보상이 마련될 때까지 구매를 줄일 가능성이 있습니다.",
    ),
    (PersonaKind.COLLECTOR, RiskCategory.RANDOM_BONUS): (
        "같이 시작해도 보너스 운에 따라 수집 속도가 달라지면 의욕이 떨어질 것 같습니다.",
        "확률 보너스보다 확정 보상이 있는 수집 경로를 선택할 가능성이 있습니다.",
    ),
    (PersonaKind.TIME_CONSTRAINED, RiskCategory.EXPIRING_CURRENCY): (
        "접속하지 못한 사이 재화가 사라질 수 있다면 처음부터 참여를 망설일 것 같습니다.",
        "만료 유예가 없다면 재화를 얻는 활동을 피할 가능성이 있습니다.",
    ),
    (PersonaKind.VALUE_SEEKING, RiskCategory.EXPIRING_CURRENCY): (
        "구매로 얻은 재화가 남아도 사라진다면 손해라고 느낄 것 같습니다.",
        "잔여 재화 보상 기준이 공개될 때까지 결제를 미룰 가능성이 있습니다.",
    ),
}

NO_EVENT_RISK_REACTIONS = {
    PersonaKind.TIME_CONSTRAINED: (
        "현재 자료에서는 짧은 이용 시간과 직접 연결된 상위 위험이 확인되지 않았습니다.",
        "실제 참여 의사와 이탈 변화는 별도 자료로 확인해야 합니다.",
    ),
    PersonaKind.VALUE_SEEKING: (
        "현재 자료에서는 비용과 보상 가치에 직접 연결된 상위 위험이 확인되지 않았습니다.",
        "실제 참여와 구매 변화는 별도 자료로 확인해야 합니다.",
    ),
    PersonaKind.COLLECTOR: (
        "현재 자료에서는 수집 목표와 진행 경로에 직접 연결된 상위 위험이 확인되지 않았습니다.",
        "실제 수집 의사와 완료율 변화는 별도 자료로 확인해야 합니다.",
    ),
    PersonaKind.CORE_GAMEPLAY: (
        "현재 자료에서는 핵심 전투 경험과 직접 연결된 상위 위험이 확인되지 않았습니다.",
        "실제 플레이와 이벤트 참여 변화는 별도 자료로 확인해야 합니다.",
    ),
}

INCONCLUSIVE_EVENT_REACTION = (
    "현재 자료만으로는 이 이용자 유형에 미칠 영향을 판단하기 어렵습니다.",
    "표본과 연결 근거를 보강한 뒤 행동 변화를 다시 예상해야 합니다.",
)

EVENT_RISK_FALLBACK = {
    RiskCategory.DOUBLE_GACHA: (
        "보상을 받기 전에 확률을 여러 번 거쳐야 한다면 비용과 결과를 믿기 어렵습니다.",
        "보장 경로가 공개될 때까지 참여나 구매를 미룰 가능성이 있습니다.",
    ),
    RiskCategory.FRAGMENTED_FLOW: (
        "참여하려고 여러 화면을 계속 오가야 한다면 과정이 번거롭게 느껴질 것 같습니다.",
        "핵심 절차를 끝내기 전에 이탈할 가능성이 있습니다.",
    ),
    RiskCategory.OPAQUE_PROGRESS: (
        "목표까지 얼마나 남았는지 보이지 않으면 계속 참여할지 결정하기 어렵습니다.",
        "남은 비용과 횟수가 공개될 때까지 참여를 보류할 가능성이 있습니다.",
    ),
    RiskCategory.RANDOM_BONUS: (
        "같은 조건인데 보너스 운에 따라 결과가 달라지면 불공정하다고 느낄 것 같습니다.",
        "확정 보상이 마련될 때까지 구매나 참여를 줄일 가능성이 있습니다.",
    ),
    RiskCategory.EXPIRING_CURRENCY: (
        "남은 재화가 보상 없이 사라진다면 손해라고 느낄 것 같습니다.",
        "재화 보호 기준이 공개될 때까지 참여를 미룰 가능성이 있습니다.",
    ),
}

EVENT_PERSONA_LABELS = {
    PersonaKind.TIME_CONSTRAINED: "시간이 부족한 복귀 이용자",
    PersonaKind.VALUE_SEEKING: "가성비를 중시하는 이용자",
    PersonaKind.COLLECTOR: "수집을 즐기는 이용자",
    PersonaKind.CORE_GAMEPLAY: "전투 경험을 우선하는 이용자",
}

EVENT_LANGUAGE_LABELS = {
    Language.ENGLISH: "영어권",
    Language.KOREAN: "한국어권",
    Language.CHINESE_SIMPLIFIED: "중국어권",
    Language.SPANISH: "스페인어권",
    Language.PORTUGUESE_BRAZIL: "포르투갈어권",
}

EVENT_DECISION_RECOMMENDATIONS = {
    Decision.GO: "결론적으로 현재 기획안을 바탕으로 {name}의 출시를 준비할 것을 권장합니다.",
    Decision.REVISE: "결론적으로 이용자 우려를 줄이는 수정안을 반영한 뒤 {name}의 기획안을 다시 검토할 것을 권장합니다.",
    Decision.HOLD: "결론적으로 근거 자료를 보강할 때까지 {name}의 출시 판단을 보류할 것을 권장합니다.",
}


def _event_decision_recommendation(
    decision: Decision, decision_reason: str, name: str
) -> str:
    if decision is Decision.REVISE and "표본" in decision_reason:
        return f"결론적으로 부족한 언어권 자료를 보강한 뒤 {name}의 출시 판단을 다시 검토할 것을 권장합니다."
    return EVENT_DECISION_RECOMMENDATIONS[decision].format(name=name)


def _event_persona_reaction(
    persona: PersonaKind, risks, *, inconclusive: bool = False
) -> str:
    if risks:
        risk = risks[0]
        quote, action = EVENT_PERSONA_REACTIONS.get(
            (persona, risk.category), EVENT_RISK_FALLBACK[risk.category]
        )
    elif inconclusive:
        quote, action = INCONCLUSIVE_EVENT_REACTION
    else:
        quote, action = NO_EVENT_RISK_REACTIONS[persona]
    return f"예상 대표 의견: “{quote}”\n예상 행동: {action}"


def _event_expected_opinion(text: str) -> str:
    quoted = text.partition("“")[2].partition("”")[0]
    return quoted or text.splitlines()[0]


def _natural_event_reason(reason: str) -> str:
    if "AI 해석" in reason:
        return "새로 수집한 자료의 해석이 끝나지 않아 현재 예상만으로 출시를 결정하기 어렵습니다."
    if "표본" in reason:
        return "언어권별 표본이 기준에 미달해 예상 반응을 충분히 확인하지 못했습니다."
    if "Critical" in reason:
        return "출시를 막을 정도로 큰 위험이 확인돼 먼저 원인을 해결해야 합니다."
    if "High" in reason:
        return "이용자가 참여나 구매를 포기할 수 있는 우려가 있어 출시 전에 수정이 필요합니다."
    return reason


def _event_reaction_balance(
    decision: Decision,
    decision_reason: str,
    *,
    has_concern: bool,
) -> str:
    criteria = (
        "판정은 반응 수가 아니라 검증된 위험의 크기와 언어권별 자료의 "
        "충분성을 기준으로 내렸습니다."
    )
    if decision is Decision.GO:
        return (
            f"{criteria} 이벤트 자료는 긍정 반응과 우려 반응을 따로 분류하지 않으므로, "
            "긍정 반응을 단정하지 않았습니다. 다만 참여나 구매를 포기하게 할 부정 반응이 높은 "
            "위험으로 검증되지 않았으므로, 현재 기준에서는 출시를 준비하는 것이 합당합니다."
        )
    if decision is Decision.REVISE:
        if has_concern:
            return (
                f"{criteria} 현재 근거에서는 긍정 반응을 뒷받침할 신호보다 참여 포기나 구매 보류로 "
                "이어질 수 있는 부정 반응이 더 뚜렷합니다. 이 우려가 높은 위험으로 검증됐으므로 "
                "수정을 먼저 반영하는 것이 합당합니다."
            )
        return (
            f"{criteria} {_natural_event_reason(decision_reason)} 부정 반응과 연결된 높은 위험은 "
            "확인되지 않았으므로 기획을 수정할 근거는 아닙니다. 부족한 언어권 자료부터 "
            "보강하는 것이 합당합니다."
        )
    if "Critical" in decision_reason:
        return (
            f"{criteria} 현재 근거에서 출시를 막을 정도의 부정 위험이 확인됐습니다. "
            "기대 효과보다 이용자 피해 가능성을 우선해 해당 위험부터 해결하는 것이 합당합니다."
        )
    return (
        f"{criteria} {_natural_event_reason(decision_reason)} 현재 자료로는 긍정 반응과 부정 반응의 "
        "무게를 비교하기 어려우므로, 판단에 필요한 근거부터 보강하는 것이 합당합니다."
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
            panel_results.append(
                PersonaResult(
                    persona=persona.kind,
                    reaction=_event_persona_reaction(
                        persona.kind,
                        risks,
                        inconclusive=decision.decision is Decision.HOLD,
                    ),
                    risk_ids=[risk.risk_id for risk in risks],
                    evidence_ids=persona.evidence_ids,
                    confidence=persona.confidence,
                )
            )
        no_direct_risk_panels = (
            []
            if decision.decision is Decision.HOLD
            else [item for item in panel_results if not item.risk_ids]
        )
        concern_panels = [item for item in panel_results if item.risk_ids]
        reactions = []
        if no_direct_risk_panels:
            labels = [
                EVENT_PERSONA_LABELS[item.persona]
                for item in no_direct_risk_panels[:2]
            ]
            audience = labels[0] if len(labels) == 1 else f"{labels[0]}와 {labels[1]}"
            reactions.append(
                f"현재 자료에서 {audience}에게 직접 연결된 상위 위험은 확인되지 않았습니다. "
                "다만 이를 긍정 반응으로 간주하지 않았습니다."
            )
        for index, item in enumerate(concern_panels[:2]):
            if index == 0:
                subject = (
                    f"반면 {EVENT_PERSONA_LABELS[item.persona]}는"
                    if reactions
                    else f"부정 반응으로는 {EVENT_PERSONA_LABELS[item.persona]}가"
                )
            else:
                subject = f"또한 {EVENT_PERSONA_LABELS[item.persona]}는"
            reactions.append(
                f"{subject} "
                f"“{_event_expected_opinion(item.reaction)}”라고 반응할 가능성이 있습니다."
            )
        language = next(
            (item for item in pack.language_insights if item.conclusion), None
        )
        if language:
            reactions.append(
                f"{EVENT_LANGUAGE_LABELS[language.language]}의 대표 예상 반응은 다음과 같습니다. {language.conclusion}"
            )
        executive_summary = "\n\n".join(
            [
                *reactions,
                _event_reaction_balance(
                    decision.decision,
                    decision.decision_reason,
                    has_concern=bool(concern_panels),
                ),
                _event_decision_recommendation(
                    decision.decision, decision.decision_reason, event.event_name
                ),
            ]
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
