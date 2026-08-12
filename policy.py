from __future__ import annotations

from contracts import Decision, LanguageSample, PersonaKind, RiskCategory, RiskItem, Severity

POLICY_VERSION = "1.0"
MIN_GENERAL_SAMPLE = 100
MIN_MECHANISM_SAMPLE = 15
MIN_PERSONA_EVIDENCE = 15
MIN_RISK_CONFIDENCE = 0.5

CLOSED_RISK_SEVERITY = {
    RiskCategory.DOUBLE_GACHA: Severity.HIGH,
    RiskCategory.FRAGMENTED_FLOW: Severity.HIGH,
    RiskCategory.OPAQUE_PROGRESS: Severity.HIGH,
    RiskCategory.RANDOM_BONUS: Severity.HIGH,
    RiskCategory.EXPIRING_CURRENCY: Severity.MEDIUM,
}

RISK_SPECS = {
    RiskCategory.DOUBLE_GACHA: (
        "중첩 확률로 최종 가치 판단 불가",
        Severity.HIGH,
        [PersonaKind.VALUE_SEEKING, PersonaKind.COLLECTOR],
        "1차 상자 결과 뒤 2차 확률 보상까지 거치며 목표 보상의 실질 확률과 비용 상한이 흐려진다.",
        "Loot Cache와 Prime Parcel을 단일 직접 보상 구조로 합칠 수 있는가?",
    ),
    RiskCategory.FRAGMENTED_FLOW: (
        "구매·개봉·제작 흐름 분절",
        Severity.HIGH,
        [PersonaKind.TIME_CONSTRAINED, PersonaKind.COLLECTOR, PersonaKind.CORE_GAMEPLAY],
        "여러 화면을 오가며 재화와 진행 상태를 추적해야 해 참여 오류와 이탈이 늘어난다.",
        "구매, 보상 확인, 제작, 진행 추적을 한 화면에 통합할 수 있는가?",
    ),
    RiskCategory.OPAQUE_PROGRESS: (
        "목표 보상까지 확정 진행 경로 부재",
        Severity.HIGH,
        [PersonaKind.TIME_CONSTRAINED, PersonaKind.VALUE_SEEKING, PersonaKind.COLLECTOR],
        "지출·플레이를 반복해도 남은 비용과 횟수를 알 수 없어 통제감을 잃는다.",
        "개봉 횟수별 마일스톤과 최종 보장 상한을 공개할 수 있는가?",
    ),
    RiskCategory.RANDOM_BONUS: (
        "같은 지출의 보너스 편차",
        Severity.HIGH,
        [PersonaKind.VALUE_SEEKING, PersonaKind.COLLECTOR],
        "확률형 보너스가 같은 지출의 진행량을 갈라 공정성 반발을 만든다.",
        "확률형 보너스를 고정 토큰 또는 마일스톤 보상으로 바꿀 수 있는가?",
    ),
    RiskCategory.EXPIRING_CURRENCY: (
        "이벤트 재화 만료에 따른 손실 압박",
        Severity.MEDIUM,
        [PersonaKind.TIME_CONSTRAINED, PersonaKind.VALUE_SEEKING],
        "남은 재화가 환불·전환 없이 삭제되어 일정이 불규칙한 이용자가 손실을 떠안는다.",
        "만료 유예 기간이나 잔여 재화 자동 전환을 제공할 수 있는가?",
    ),
}

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


def expected_severity(category: RiskCategory) -> Severity | None:
    return CLOSED_RISK_SEVERITY.get(category)


def decide(
    samples: list[LanguageSample],
    risks: list[RiskItem],
    *,
    analysis_incomplete: bool = False,
) -> tuple[Decision, str]:
    if analysis_incomplete:
        return Decision.HOLD, "새 자료의 AI 해석이 완료되지 않아 판단을 보류한다."
    if any(risk.severity == Severity.CRITICAL for risk in risks):
        return Decision.HOLD, "검증된 Critical 위험이 있어 출시 판단을 보류한다."
    insufficient = sum(not sample.sufficient for sample in samples)
    if insufficient >= 3:
        return Decision.HOLD, "세 언어권 이상이 최소 표본에 미달해 판단 근거가 부족하다."
    if any(risk.severity == Severity.HIGH for risk in risks):
        return Decision.REVISE, "검증된 High 위험을 수정한 뒤 재검토해야 한다."
    if insufficient:
        return Decision.REVISE, "일부 언어권 표본을 보강한 뒤 출시 판단을 갱신해야 한다."
    return Decision.GO, "필수 표본을 충족했고 High 이상 검증 위험이 없다."
