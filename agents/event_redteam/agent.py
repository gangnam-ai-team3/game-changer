from __future__ import annotations

import os
from pathlib import Path

from agents.structured import parse_structured
from contracts import (
    ArtifactStatus,
    EventBrief,
    EvidencePack,
    PersonaKind,
    Producer,
    RiskAssessment,
    RiskCategory,
    RiskItem,
    Severity,
)

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
