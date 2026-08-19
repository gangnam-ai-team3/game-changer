import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    require_prelaunch_narrative,
)
from contracts import ArtifactStatus, ErrorCode, Producer, Severity
from update_review.contracts import (
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
            model=os.getenv("CLAUDE_UPDATE_AUDIT_MODEL", "claude-haiku-4-5"),
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
            key=lambda item: (rank[item.severity], item.confidence),
            reverse=True,
        )
        label = {
            UpdateDecision.GO: "출시 가능",
            UpdateDecision.REVISE: "일부 수정 후 출시",
            UpdateDecision.TEST: "테스트 후 출시",
            UpdateDecision.HOLD: "판정 보류",
        }[decision.decision]
        visible_languages = sum(
            insight.conclusion is not None for insight in pack.language_insights
        )
        risk_summary = (
            f"우선 확인할 위험은 {', '.join(risk.title.replace('·', ', ') for risk in top_risks[:3])}입니다."
            if top_risks
            else "현재 자료에서는 우선 수정이 필요한 위험이 확인되지 않았습니다."
        )
        executive_summary = (
            f"{brief.update_name}의 출시 판단은 {label}입니다. "
            f"출시 전 자료에서 긍정 신호 {len(impact.expected_positive)}건과 "
            f"우려 신호 {len(impact.expected_negative)}건을 확인했고, "
            f"이용자 유형 {len(pack.persona_impacts)}개와 결론을 공개할 수 있는 "
            f"언어권 {visible_languages}개의 예상 반응을 종합했습니다. "
            f"{risk_summary} 따라서 {decision.decision_reason}"
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
