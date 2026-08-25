import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    require_prelaunch_narrative,
)
from contracts import ArtifactStatus, ErrorCode, Language, PersonaKind, Producer, Severity
from update_review.contracts import (
    ExpectedImpact,
    RejectedUpdateRisk,
    UpdateBrief,
    UpdateDecision,
    UpdateDecisionBrief,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateImpactAssessment,
    UpdateRecommendation,
    UpdateValidatedDecision,
)
from update_review.policy import (
    MIN_RISK_CONFIDENCE,
    UPDATE_RISK_TAGS,
    decide_update,
    expected_severity,
)


# The visible brief is deterministic.  This is the only optional Claude
# executive wording accepted before the code-owned brief is retained.
_AUDIT_EXECUTIVE_PROSPECTIVE_TEMPLATES = (
    "결과 예측 가능성은 개선될 수 있지만 전투 지표는 테스트로 확인해야 합니다.",
)

PERSONA_LABELS = {
    PersonaKind.TIME_CONSTRAINED: "시간이 부족한 복귀 이용자",
    PersonaKind.VALUE_SEEKING: "가성비를 중시하는 이용자",
    PersonaKind.COLLECTOR: "수집을 즐기는 이용자",
    PersonaKind.CORE_GAMEPLAY: "전투 경험을 우선하는 이용자",
}

LANGUAGE_LABELS = {
    Language.ENGLISH: "영어권",
    Language.KOREAN: "한국어권",
    Language.CHINESE_SIMPLIFIED: "중국어권",
    Language.SPANISH: "스페인어권",
    Language.PORTUGUESE_BRAZIL: "포르투갈어권",
}

UPDATE_DECISION_RECOMMENDATIONS = {
    UpdateDecision.GO: "결론적으로 현재 기획안을 바탕으로 {name}의 출시를 준비할 것을 권장합니다.",
    UpdateDecision.REVISE: "결론적으로 이용자 우려를 줄이는 수정안을 반영한 뒤 {name}의 기획안을 다시 검토할 것을 권장합니다.",
    UpdateDecision.TEST: "결론적으로 제한된 테스트에서 핵심 지표를 확인한 뒤 {name}의 출시 여부를 결정할 것을 권장합니다.",
    UpdateDecision.HOLD: "결론적으로 필수 검증과 근거 확인을 마칠 때까지 {name}의 출시 판단을 보류할 것을 권장합니다.",
}


def _expected_opinion(text: str) -> str:
    quoted = text.partition("“")[2].partition("”")[0]
    return quoted or text.splitlines()[0]


def _expected_impacts_summary(
    impacts: list[ExpectedImpact], *, positive: bool
) -> str:
    label = "긍정" if positive else "부정"
    if not impacts:
        return f"현재 자료에서는 예상 {label} 반응을 뒷받침할 근거가 별도로 확인되지 않았습니다."
    ranked = sorted(
        impacts,
        key=lambda item: (
            -len(set(item.evidence_ids)),
            -item.confidence,
            item.impact_id,
        ),
    )[:2]
    response = "기대" if positive else "우려"
    grouped: dict[tuple[PersonaKind, ...], list[str]] = {}
    for item in ranked:
        grouped.setdefault(tuple(item.affected_personas), []).append(
            f"“{_expected_opinion(item.summary)}”"
        )
    summaries = []
    for affected_personas, opinions in grouped.items():
        personas = [PERSONA_LABELS[persona] for persona in affected_personas]
        audience = (
            personas[0]
            if len(personas) == 1
            else f"{', '.join(personas[:-1])}와 {personas[-1]}"
        )
        opinion = (
            opinions[0]
            if len(opinions) == 1
            else f"{', '.join(opinions[:-1])}와 {opinions[-1]}"
        )
        summaries.append(f"{audience}에게는 {opinion}라는 {response}가 두드러집니다.")
    return f"예상 {label} 반응을 취합한 결과, {' '.join(summaries)}"


def _natural_update_reason(reason: str) -> str:
    if "AI 해석" in reason:
        return "새로 수집한 자료의 해석이 끝나지 않아 현재 예상만으로 출시를 결정하기 어렵습니다."
    if "표본" in reason:
        return "여러 언어권의 표본이 부족해 예상 반응을 충분히 확인하지 못했습니다."
    if "Critical" in reason:
        return "출시를 막을 정도로 큰 위험이 확인돼 먼저 원인을 해결해야 합니다."
    if "검증 지표" in reason:
        return "실제 이용 환경에서 확인해야 할 핵심 지표가 남아 있습니다."
    if "확인 지표" in reason:
        return "위험을 판단할 확인 기준이 충분하지 않아 지금 결론을 내리기 어렵습니다."
    if "테스트 서버" in reason:
        return "실제 이용 환경에서 성능과 행동 변화를 확인해야 할 불확실성이 남아 있습니다."
    if "High" in reason:
        return "출시 전에 이용자 우려를 줄이는 수정이 필요합니다."
    return reason


def _update_reaction_balance(
    decision: UpdateDecision,
    decision_reason: str,
    *,
    has_support: bool,
    has_concern: bool,
) -> str:
    criteria = (
        "판정은 반응 수가 아니라 검증된 위험의 크기, 언어권별 자료, "
        "확인 지표의 충족 여부를 기준으로 내렸습니다."
    )
    if decision is UpdateDecision.GO:
        if has_support and has_concern:
            return (
                f"{criteria} 긍정 반응은 변경 의도와 일치하고, 부정 반응은 출시를 막을 수준의 "
                "위험으로 검증되지 않았습니다. 따라서 현재 근거에서는 기대 효과를 "
                "출시 판단에 반영하는 것이 합당합니다."
            )
        if has_support:
            return (
                f"{criteria} 긍정 반응이 변경 의도와 일치하고, 출시를 막을 만한 부정 반응이나 "
                "검증된 위험은 확인되지 않았습니다. 현재 근거로는 출시를 준비하는 것이 합당합니다."
            )
        concern = (
            "부정 반응은 있지만 출시를 막을 수준의 위험으로 검증되지 않았습니다."
            if has_concern
            else "출시를 막을 부정 반응이나 검증된 위험은 확인되지 않았습니다."
        )
        return (
            f"{criteria} 긍정 반응을 뒷받침할 근거는 확인되지 않았고, {concern} "
            "이 판정은 기대 효과가 확인됐다는 뜻이 아니라, 현재 위험 기준에서 출시를 막을 "
            "근거가 없다는 의미입니다."
        )
    if decision is UpdateDecision.REVISE:
        if not has_support:
            return (
                f"{criteria} 현재 근거에서는 긍정 반응을 뒷받침할 신호보다 부정 반응과 "
                "연결된 높은 위험이 더 뚜렷합니다. 기대 효과를 논하기 전에 검증된 우려를 "
                "먼저 줄이는 것이 합당합니다."
            )
        return (
            f"{criteria} 긍정 반응이 있더라도 부정 반응과 연결된 높은 위험이 출시 후 이용 경험을 "
            "해칠 수 있습니다. 따라서 기대 효과보다 검증된 우려를 먼저 줄이는 것이 합당합니다."
        )
    if decision is UpdateDecision.TEST:
        if has_support and has_concern:
            return (
                f"{criteria} 긍정 반응과 부정 반응이 함께 예상되지만, 어느 쪽의 영향이 더 큰지는 "
                "실제 이용 환경에서 확인되지 않았습니다. 바로 출시하기보다 제한된 테스트로 "
                "기대 효과와 우려 가능성을 비교하는 것이 합당합니다."
            )
        return (
            f"{criteria} {_natural_update_reason(decision_reason)} 현재 근거만으로 긍정 반응과 부정 반응의 "
            "영향을 비교하기 어려우므로, 제한된 테스트로 확인하는 것이 합당합니다."
        )
    if "Critical" in decision_reason:
        prefix = "긍정 반응이 있더라도" if has_support else "현재 근거에서"
        return (
            f"{criteria} {prefix} 출시를 막을 정도의 부정 위험이 확인됐습니다. "
            "기대 효과보다 이용자 피해 가능성을 우선해 해당 위험부터 해결하는 것이 합당합니다."
        )
    return (
        f"{criteria} {_natural_update_reason(decision_reason)} 현재 자료로는 긍정 반응과 부정 반응의 "
        "무게를 비교하기 어려우므로, 판단에 필요한 근거부터 보강하는 것이 합당합니다."
    )


SEVERITY_LABELS = {
    Severity.CRITICAL: "매우 높음",
    Severity.HIGH: "높음",
    Severity.MEDIUM: "보통",
    Severity.LOW: "낮음",
}


def _linked_evidence_count(items) -> int:
    return len({evidence_id for item in items for evidence_id in item.evidence_ids})


def _decision_evidence_summary(
    pack: UpdateEvidencePack,
    impact: UpdateImpactAssessment,
    decision: UpdateValidatedDecision,
    top_risks,
) -> list[str]:
    positive_count = _linked_evidence_count(impact.expected_positive)
    negative_count = _linked_evidence_count(impact.expected_negative)
    mixed_count = _linked_evidence_count(pack.split_conditions)
    visible_languages = [
        item for item in pack.language_insights if item.conclusion is not None
    ]
    linked_personas = [item for item in pack.persona_impacts if item.evidence_ids]
    evidence_basis = (
        f"판단에 사용한 자료: 비식별 근거 {len(pack.evidence)}건을 검토했습니다. "
        f"긍정 예상에는 고유 근거 {positive_count}건, 부정 예상에는 {negative_count}건, "
        f"반응이 갈릴 조건에는 {mixed_count}건이 연결됐습니다. "
        f"근거가 연결된 이용자 유형은 {len(linked_personas)}개이며, "
        f"표본 기준을 통과해 결론을 공개한 언어권은 {len(visible_languages)}개입니다."
    )
    if top_risks:
        counts = Counter(item.severity for item in top_risks)
        severity_summary = ", ".join(
            f"{SEVERITY_LABELS[severity]} {counts[severity]}개"
            for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
            if counts[severity]
        )
        lead = top_risks[0]
        covered = sum(
            any(
                risk.risk_id in metric.addresses_risk_ids
                for metric in decision.validation_metrics
            )
            for risk in top_risks
        )
        risk_basis = (
            f"위험 검증 결과: 근거와 연결된 위험 {len(top_risks)}개를 확인했으며 "
            f"위험 수준은 {severity_summary}입니다. 가장 먼저 확인할 위험은 "
            f"‘{lead.title}’이며, 근거 {len(set(lead.evidence_ids))}건과 "
            f"신뢰도 {round(lead.confidence * 100)}%로 검증됐습니다. "
            f"검증 위험 {len(top_risks)}개 중 {covered}개에 확인 지표가 연결됐습니다."
        )
    else:
        risk_basis = (
            "위험 검증 결과: 현재 자료에서는 코드 기준을 통과한 우선 위험이 없습니다. "
            "이는 긍정 효과가 입증됐다는 뜻이 아니라, 현재 근거에서 출시를 막을 위험이 "
            "검증되지 않았다는 의미입니다."
        )
    hidden_languages = [
        LANGUAGE_LABELS[item.language]
        for item in pack.language_insights
        if item.conclusion is None
    ]
    missing = (
        f"자료의 한계: {', '.join(hidden_languages)}은 표본 기준을 충족하지 않아 "
        "예상 반응을 판정 근거로 사용하지 않았습니다."
        if hidden_languages
        else "자료의 한계: 이번 검토 범위의 모든 언어권이 표본 기준을 통과했습니다."
    )
    if decision.decision is UpdateDecision.HOLD and "해석" in decision.decision_reason:
        decisive = (
            "판정의 결정적 이유: 이번 판정 보류는 업데이트의 위험이 확정됐기 때문이 아니라, "
            "필수 에이전트 검증이 완료되지 않아 적용한 안전 조치입니다. 현재 확인된 기대와 "
            "우려의 무게를 최종 비교하려면 중단된 검증을 먼저 완료해야 합니다."
        )
    else:
        decisive = f"판정의 결정적 이유: {_natural_update_reason(decision.decision_reason)}"
    if decision.decision is UpdateDecision.GO:
        condition = "출시 조건: 연결된 확인 지표를 출시 후에도 관찰하고 기준을 벗어나면 다시 검토합니다."
    elif decision.decision is UpdateDecision.REVISE:
        condition = "출시 조건: 우선 위험을 낮추는 수정안을 반영하고 연결된 확인 지표가 성공 기준을 충족한 뒤 다시 검토합니다."
    elif decision.decision is UpdateDecision.TEST:
        condition = "출시 조건: 제한된 테스트에서 연결된 확인 지표를 측정하고 기대 효과가 우려보다 크다는 근거를 확인합니다."
    else:
        condition = "출시 조건: 완료되지 않은 검증을 다시 실행하고, 위험과 확인 지표를 모두 검토한 뒤 같은 기준으로 재판정합니다."
    return [evidence_basis, risk_basis, missing, decisive, condition]


class RecommendationNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    title: str = Field(min_length=1)
    action: str = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class AuditNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=1)
    recommendations: list[RecommendationNarrative]


class UpdateAuditAgent:
    prompt_path = Path(__file__).with_name("prompts") / "audit.md"

    def __init__(
        self,
        use_llm: bool = False,
        client=None,
        budget: ClaudeBudget | None = None,
    ) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def run(
        self,
        bundle: UpdateFeedbackBundle,
        pack: UpdateEvidencePack,
        assessment: UpdateImpactAssessment,
        *,
        analysis_incomplete: bool = False,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateValidatedDecision:
        base = self.run_deterministic(
            bundle,
            pack,
            assessment,
            analysis_incomplete=analysis_incomplete,
            on_event=on_event,
        )
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify(
            "claude_narrative",
            "Claude Haiku가 고정된 판정 범위에서 출시 전 템플릿을 선택합니다.",
            {"provider": "claude"},
        )
        narrative = parse_claude_structured(
            model=os.getenv(
                "CLAUDE_UPDATE_AUDIT_MODEL", "claude-haiku-4-5-20251001"
            ),
            prompt_path=self.prompt_path,
            output_type=AuditNarrative,
            payload={
                "artifact": base.model_dump(mode="json"),
                "prospective_templates": {
                    "executive_summary": list(
                        _AUDIT_EXECUTIVE_PROSPECTIVE_TEMPLATES
                    )
                },
            },
            client=self.client,
            budget=self.budget,
        )
        require_prelaunch_narrative(
            [narrative.executive_summary]
            + [
                text
                for item in narrative.recommendations
                for text in (item.title, item.action)
            ],
            prediction_fields=[narrative.executive_summary],
            prospective_templates=_AUDIT_EXECUTIVE_PROSPECTIVE_TEMPLATES,
        )
        risks = {item.risk_id for item in base.validated_risks}
        metrics_by_risk = {
            risk_id: {
                metric.metric_id
                for metric in base.validation_metrics
                if risk_id in metric.addresses_risk_ids
            }
            for risk_id in risks
        }
        for proposal in narrative.recommendations:
            if (
                proposal.risk_id not in risks
                or not set(proposal.validation_metric_ids)
                <= metrics_by_risk[proposal.risk_id]
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude narrative references unknown audit data",
                )
        notify(
            "claude_output_checked",
            "코드 판정·권고를 유지한 채 Claude 템플릿 연결을 확인했습니다.",
            {"provider": "claude", "decision": base.decision.value},
        )
        return base

    def run_deterministic(
        self,
        bundle: UpdateFeedbackBundle,
        pack: UpdateEvidencePack,
        assessment: UpdateImpactAssessment,
        *,
        analysis_incomplete: bool = False,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateValidatedDecision:
        notify = on_event or (lambda _node, _message, _metrics: None)
        evidence_ids = {item.evidence_id for item in pack.evidence}
        validated = []
        rejected = []
        for risk in assessment.risks:
            linked = [item for item in pack.evidence if item.evidence_id in risk.evidence_ids]
            if len(linked) != len(risk.evidence_ids):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="실재 근거 ID와 연결되지 않음"))
            elif any(
                UPDATE_RISK_TAGS[risk.category] not in item.mechanism_tags
                for item in linked
            ):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="위험 범주와 연결 근거 태그가 다름"))
            elif risk.severity != expected_severity(risk.category):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="정책 위험 등급과 다름"))
            elif risk.confidence < MIN_RISK_CONFIDENCE:
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="근거 신뢰도 0.5 미만"))
            else:
                validated.append(risk)
        notify("risks_validated", "근거 ID·정책 등급·신뢰도로 위험을 검증했습니다.", {"validated": len(validated), "rejected": len(rejected)})
        metrics = [
            item
            for item in assessment.validation_metrics
            if set(item.addresses_risk_ids) <= {risk.risk_id for risk in validated}
        ]
        metrics_complete = all(
            any(risk.risk_id in item.addresses_risk_ids for item in metrics)
            for risk in validated
        )
        decision, reason = decide_update(
            bundle.samples,
            validated,
            metrics_complete=metrics_complete,
            analysis_incomplete=analysis_incomplete,
        )
        notify("sample_gate_applied", "언어권 표본과 검증 지표 충족 여부를 판정에 적용했습니다.", {"metrics_complete": metrics_complete})
        notify("decision_fixed", "코드 정책으로 출시 판정을 고정했습니다.", {"decision": decision.value})
        recommendations = [
            UpdateRecommendation(
                priority=index,
                title=f"{risk.title} 사전 테스트",
                action=risk.revision_question,
                addresses_risk_ids=[risk.risk_id],
                validation_metric_ids=[
                    item.metric_id
                    for item in metrics
                    if risk.risk_id in item.addresses_risk_ids
                ],
            )
            for index, risk in enumerate(validated, start=1)
        ]
        notify("recommendations_built", "위험과 검증 지표를 연결한 실행 권고를 만들었습니다.", {"recommendations": len(recommendations)})
        return UpdateValidatedDecision(
            run_id=assessment.run_id,
            status=ArtifactStatus.PARTIAL if assessment.errors else ArtifactStatus.COMPLETE,
            producer=Producer.AUDIT_STRATEGY,
            input_refs=[bundle.ref, pack.ref, assessment.ref],
            errors=list(assessment.errors),
            decision=decision,
            decision_reason=reason,
            validated_risks=validated,
            rejected_risks=rejected,
            recommendations=recommendations,
            validation_metrics=metrics,
        )

    def _deterministic_brief(
        self,
        brief: UpdateBrief,
        pack: UpdateEvidencePack,
        impact: UpdateImpactAssessment,
        decision: UpdateValidatedDecision,
    ) -> UpdateDecisionBrief:
        rank = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
        }
        top_risks = sorted(
            decision.validated_risks,
            key=lambda item: (
                rank[item.severity],
                len(set(item.evidence_ids)),
                item.confidence,
                item.risk_id,
            ),
            reverse=True,
        )
        reactions = [
            _expected_impacts_summary(impact.expected_positive, positive=True),
            _expected_impacts_summary(impact.expected_negative, positive=False),
        ]
        language = next(
            (item for item in pack.language_insights if item.conclusion), None
        )
        if language:
            reactions.append(
                f"{LANGUAGE_LABELS[language.language]}에서는 {language.conclusion}"
            )
        evidence_summary = _decision_evidence_summary(
            pack, impact, decision, top_risks
        )
        executive_summary = "\n\n".join(
            [
                *reactions,
                *evidence_summary[:3],
                _update_reaction_balance(
                    decision.decision,
                    decision.decision_reason,
                    has_support=bool(impact.expected_positive),
                    has_concern=bool(impact.expected_negative),
                ),
                *evidence_summary[3:],
                UPDATE_DECISION_RECOMMENDATIONS[decision.decision].format(
                    name=brief.update_name
                ),
            ]
        )
        return UpdateDecisionBrief(
            run_id=brief.run_id,
            status=decision.status,
            producer=Producer.ORCHESTRATOR,
            input_refs=[brief.ref, pack.ref, impact.ref, decision.ref],
            errors=list(decision.errors),
            decision=decision.decision,
            executive_summary=executive_summary,
            official_context=brief.official_context,
            official_context_url=brief.official_context_url,
            expected_positive=impact.expected_positive,
            expected_negative=impact.expected_negative,
            split_conditions=pack.split_conditions,
            persona_impacts=pack.persona_impacts,
            language_insights=pack.language_insights,
            top_risks=top_risks,
            validation_metrics=decision.validation_metrics,
            evidence=pack.evidence,
            recommendations=decision.recommendations,
        )

    def to_brief(
        self,
        brief: UpdateBrief,
        pack: UpdateEvidencePack,
        impact: UpdateImpactAssessment,
        decision: UpdateValidatedDecision,
    ) -> UpdateDecisionBrief:
        # The deterministic decision label and reason always own the visible brief.
        # Claude's summary is validated as untrusted input but is never persisted.
        return self._deterministic_brief(brief, pack, impact, decision)
