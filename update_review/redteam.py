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
from contracts import ArtifactStatus, ErrorCode, PersonaKind, Producer
from update_review.contracts import (
    ExpectedImpact,
    UpdateBrief,
    UpdateEvidencePack,
    UpdateImpactAssessment,
    UpdateRiskCategory,
    UpdateRiskItem,
    ValidationMetric,
)
from update_review.policy import expected_severity


RISK_BY_TAG = {
    "balance_regression": UpdateRiskCategory.BALANCE_REGRESSION,
    "fairness_regression": UpdateRiskCategory.FAIRNESS_REGRESSION,
    "information_clarity": UpdateRiskCategory.INFORMATION_CLARITY,
    "flow_disruption": UpdateRiskCategory.FLOW_DISRUPTION,
    "rule_exception": UpdateRiskCategory.RULE_EXCEPTION,
    "learning_burden": UpdateRiskCategory.LEARNING_BURDEN,
}

RISK_COPY = {
    UpdateRiskCategory.BALANCE_REGRESSION: ("실제 전투 성능 역전", "고정 피해와 반동·연사력의 조합으로 사용률이 쏠릴 가능성이 있음.", "테스트 서버에서 사용률·승률·평균 피해를 확인할 수 있는가?"),
    UpdateRiskCategory.FAIRNESS_REGRESSION: ("공정성 인식 역전", "변경 결과가 특정 이용자에게만 유리하게 체감될 가능성이 있음.", "숙련도별 성과 편차를 비교할 수 있는가?"),
    UpdateRiskCategory.INFORMATION_CLARITY: ("변경 정보 이해 부족", "변경 전·후 차이를 알지 못해 잘못된 행동을 할 가능성이 있음.", "한 화면에서 변경 전·후를 설명할 수 있는가?"),
    UpdateRiskCategory.FLOW_DISRUPTION: ("사용 동선 분절", "새 화면과 절차가 작업 흐름을 끊을 가능성이 있음.", "핵심 작업을 기존 단계 안에서 끝낼 수 있는가?"),
    UpdateRiskCategory.RULE_EXCEPTION: ("예외 규칙 누락", "기존 이용자와 경계 상황에서 다른 결과가 나올 가능성이 있음.", "경계값·기존 상태·예외 사용자를 모두 테스트했는가?"),
    UpdateRiskCategory.LEARNING_BURDEN: ("새 규칙 학습 부담", "기존 습관을 다시 배워야 해 이탈할 가능성이 있음.", "첫 사용에서 별도 설명 없이 완료할 수 있는가?"),
}

# Claude chooses from code-owned prospective wording; it never supplies stored
# failure-path prose itself.
_RISK_PROSPECTIVE_ALTERNATIVES = {
    UpdateRiskCategory.BALANCE_REGRESSION: (
        "실제 특성 조합에서 메타가 쏠릴 가능성이 있음.",
    ),
}


def _risk_prospective_templates(risk: UpdateRiskItem) -> tuple[str, ...]:
    return (
        risk.failure_path,
        *_RISK_PROSPECTIVE_ALTERNATIVES.get(risk.category, ()),
    )


class RiskNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    title: str = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class RedteamNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[RiskNarrative]


class UpdateRedteamAgent:
    prompt_path = Path(__file__).with_name("prompts") / "redteam.md"

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
        brief: UpdateBrief,
        pack: UpdateEvidencePack,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateImpactAssessment:
        base = self.run_deterministic(brief, pack, on_event=on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify(
            "claude_narrative",
            "Claude Haiku가 고정된 위험 범위에서 출시 전 템플릿을 선택합니다.",
            {"provider": "claude"},
        )
        risks = {item.risk_id: item for item in base.risks}
        metrics_by_risk = {
            risk.risk_id: {
                metric.metric_id
                for metric in base.validation_metrics
                if risk.risk_id in metric.addresses_risk_ids
            }
            for risk in base.risks
        }
        narrative = parse_claude_structured(
            model=os.getenv("CLAUDE_UPDATE_REDTEAM_MODEL", "claude-haiku-4-5"),
            prompt_path=self.prompt_path,
            output_type=RedteamNarrative,
            payload={
                "artifact": base.model_dump(mode="json"),
                "prospective_templates": {
                    "failure_path_by_risk_id": {
                        risk_id: list(_risk_prospective_templates(risk))
                        for risk_id, risk in risks.items()
                    }
                },
            },
            client=self.client,
            budget=self.budget,
        )
        for proposal in narrative.risks:
            official = risks.get(proposal.risk_id)
            if (
                official is None
                or not set(proposal.evidence_ids) <= set(official.evidence_ids)
                or not set(proposal.validation_metric_ids)
                <= metrics_by_risk[proposal.risk_id]
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude narrative references unknown risk data",
                )
            require_prelaunch_narrative(
                [proposal.title, proposal.failure_path, proposal.revision_question],
                prediction_fields=[proposal.failure_path],
                prospective_templates=_risk_prospective_templates(official),
            )
        notify(
            "claude_output_checked",
            "Claude 템플릿 선택의 위험·근거·지표 ID를 확인했고 코드 소유 문장을 유지했습니다.",
            {"provider": "claude"},
        )
        return base

    def run_deterministic(
        self,
        brief: UpdateBrief,
        pack: UpdateEvidencePack,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateImpactAssessment:
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify("change_reviewed", "현재 상태와 변경안의 차이를 확인했습니다.", {"update_type": brief.update_type.value})
        positives = [
            ExpectedImpact(
                impact_id=f"impact-{item.signal_id}",
                title=item.title,
                summary=item.summary,
                affected_personas=[impact.persona for impact in pack.persona_impacts if item.signal_id in impact.positive_signal_ids] or [PersonaKind.CORE_GAMEPLAY],
                evidence_ids=item.evidence_ids,
                confidence=item.confidence,
            )
            for item in pack.positive_signals
        ]
        negatives = [
            ExpectedImpact(
                impact_id=f"impact-{item.signal_id}",
                title=item.title,
                summary=item.summary,
                affected_personas=[impact.persona for impact in pack.persona_impacts if item.signal_id in impact.negative_signal_ids] or [PersonaKind.CORE_GAMEPLAY],
                evidence_ids=item.evidence_ids,
                confidence=item.confidence,
            )
            for item in pack.negative_signals
        ]
        grouped_signals = {}
        for item in [*pack.negative_signals, *pack.split_conditions]:
            tag = item.signal_id.split("-", 1)[1]
            category = RISK_BY_TAG.get(tag)
            if category is not None:
                grouped_signals.setdefault(category, []).append(item)

        risks = []
        for category in sorted(grouped_signals, key=lambda item: item.value):
            items = grouped_signals[category]
            title, failure_path, question = RISK_COPY[category]
            linked_signal_ids = {item.signal_id for item in items}
            affected_personas = sorted(
                {
                    impact.persona
                    for impact in pack.persona_impacts
                    if linked_signal_ids
                    & set(
                        impact.positive_signal_ids
                        + impact.negative_signal_ids
                        + impact.split_signal_ids
                    )
                },
                key=lambda item: item.value,
            ) or [PersonaKind.CORE_GAMEPLAY]
            evidence_ids = sorted(
                {evidence_id for item in items for evidence_id in item.evidence_ids}
            )
            risks.append(
                UpdateRiskItem(
                    risk_id=f"risk-{category.value}",
                    category=category,
                    title=title,
                    severity=expected_severity(category),
                    affected_personas=affected_personas,
                    evidence_ids=evidence_ids,
                    failure_path=failure_path,
                    revision_question=question,
                    confidence=sum(item.confidence for item in items) / len(items),
                )
            )
        notify("failure_paths_built", "부정·혼합 신호에서 실패 경로를 만들었습니다.", {"risks": len(risks)})
        metrics = [
            ValidationMetric(
                metric_id=f"metric-{risk.category.value}",
                title=f"{risk.title} 확인 지표",
                measurement="업데이트 직접 언급 의견의 감정 비율과 관련 행동 지표를 비교",
                success_condition="부정 반응이 사전 경계값을 넘지 않고 행동 지표의 악화가 없음",
                addresses_risk_ids=[risk.risk_id],
            )
            for risk in risks
        ]
        notify("metrics_linked", "각 위험에 출시 후 확인 지표를 연결했습니다.", {"metrics": len(metrics)})
        result = UpdateImpactAssessment(
            run_id=brief.run_id,
            status=ArtifactStatus.PARTIAL if pack.errors else ArtifactStatus.COMPLETE,
            producer=Producer.EVENT_REDTEAM,
            input_refs=[brief.ref, pack.ref],
            errors=list(pack.errors),
            expected_positive=positives,
            expected_negative=negatives,
            risks=risks,
            validation_metrics=metrics,
        )
        notify("assessment_ready", "UpdateImpactAssessment 계약 검증을 통과했습니다.", {"risks": len(risks)})
        return result
