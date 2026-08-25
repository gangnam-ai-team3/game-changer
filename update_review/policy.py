from contracts import LanguageSample, Severity
from update_review.contracts import UpdateDecision, UpdateRiskCategory, UpdateRiskItem


POLICY_VERSION = "1.0"
MIN_RISK_CONFIDENCE = 0.5

CLOSED_UPDATE_RISK_SEVERITY = {
    UpdateRiskCategory.BALANCE_REGRESSION: Severity.MEDIUM,
    UpdateRiskCategory.FAIRNESS_REGRESSION: Severity.HIGH,
    UpdateRiskCategory.INFORMATION_CLARITY: Severity.HIGH,
    UpdateRiskCategory.FLOW_DISRUPTION: Severity.HIGH,
    UpdateRiskCategory.RULE_EXCEPTION: Severity.HIGH,
    UpdateRiskCategory.LEARNING_BURDEN: Severity.MEDIUM,
}

TEST_REQUIRED = {
    UpdateRiskCategory.BALANCE_REGRESSION,
    UpdateRiskCategory.LEARNING_BURDEN,
}

UPDATE_RISK_TAGS = {
    category: category.value for category in CLOSED_UPDATE_RISK_SEVERITY
}


def expected_severity(category: UpdateRiskCategory) -> Severity:
    return CLOSED_UPDATE_RISK_SEVERITY[category]


def decide_update(
    samples: list[LanguageSample],
    risks: list[UpdateRiskItem],
    *,
    metrics_complete: bool,
    analysis_incomplete: bool = False,
) -> tuple[UpdateDecision, str]:
    if analysis_incomplete:
        return UpdateDecision.HOLD, "새 자료의 AI 해석이 완료되지 않아 판정을 보류합니다."
    if not metrics_complete:
        return UpdateDecision.HOLD, "모든 위험에 연결된 출시 후 확인 지표가 없어 판정을 보류합니다."
    if any(item.severity == Severity.CRITICAL for item in risks):
        return UpdateDecision.HOLD, "검증된 Critical 위험이 있어 출시 판정을 보류합니다."
    insufficient = sum(not sample.sufficient for sample in samples)
    if insufficient >= 3:
        return UpdateDecision.HOLD, "세 언어권 이상이 최소 표본에 미달해 판정 근거가 부족합니다."
    if any(item.severity == Severity.HIGH for item in risks):
        return UpdateDecision.REVISE, "검증된 High 위험을 수정한 뒤 출시해야 합니다."
    if insufficient or any(item.category in TEST_REQUIRED for item in risks):
        return UpdateDecision.TEST, "남은 불확실성을 테스트 서버와 제한된 공개로 확인한 뒤 출시해야 합니다."
    return UpdateDecision.GO, "필수 표본과 확인 지표를 갖추고 High 이상으로 검증된 위험이 없습니다."
