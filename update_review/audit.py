from collections.abc import Callable

from contracts import ArtifactStatus, Producer, Severity
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


class UpdateAuditAgent:
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

    def to_brief(
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
        return UpdateDecisionBrief(
            run_id=brief.run_id,
            status=decision.status,
            producer=Producer.ORCHESTRATOR,
            input_refs=[brief.ref, pack.ref, impact.ref, decision.ref],
            errors=list(decision.errors),
            decision=decision.decision,
            executive_summary=f"{brief.update_name}: {label}. {decision.decision_reason}",
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
