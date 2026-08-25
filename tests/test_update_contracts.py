from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from contracts import (
    ArtifactStatus,
    ErrorCode,
    Language,
    LanguageSample,
    PersonaKind,
    PipelineError,
    Producer,
    Severity,
    SourceType,
)
from update_review.contracts import (
    EvidencePeriod,
    ReactionSignal,
    Sentiment,
    SystemRulesDetails,
    UpdateBrief,
    UpdateDecision,
    UpdateDecisionBrief,
    UpdateEvidenceItem,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateImpactAssessment,
    UpdateRiskCategory,
    UpdateRiskItem,
    UpdateType,
    UiUxDetails,
    WeaponBalanceDetails,
)
from update_review.policy import decide_update


NOW = datetime(2026, 8, 13, tzinfo=UTC)


def weapon_brief(**updates) -> UpdateBrief:
    values = {
        "run_id": "update-run",
        "status": ArtifactStatus.COMPLETE,
        "producer": Producer.USER,
        "game": "PUBG: BATTLEGROUNDS",
        "update_name": "Dragunov 확률 피해 제거",
        "update_type": UpdateType.WEAPON_BALANCE,
        "current_state": "기본 58, 최대 73의 확률형 피해",
        "change_summary": "피해를 60으로 고정",
        "goal": "결과 예측 가능성을 높인다.",
        "expected_benefits": ["공정성 인식 개선"],
        "concerns": ["실제 전투 성능은 확인 필요"],
        "scope": "일반 매칭",
        "planned_at": NOW + timedelta(days=7),
        "cutoff_at": NOW,
        "official_context": (
            "PUBG Update 25.2에서 이용자 피드백을 바탕으로 "
            "확률형 피해를 제거했다는 공식 변경 맥락"
        ),
        "official_context_url": "https://pubg.com/en/news/6616",
        "details": WeaponBalanceDetails(
            target_weapon="Dragunov",
            damage="58~73 확률 → 60 고정",
            recoil="현행 유지",
            rate_of_fire="해당 없음",
            ammunition="7.62mm",
            spawn_and_modes="일반 매칭",
        ),
    }
    values.update(updates)
    return UpdateBrief(**values)


def evidence(evidence_id: str = "fx-dragunov-ko-001", **updates) -> UpdateEvidenceItem:
    values = {
        "evidence_id": evidence_id,
        "source": SourceType.SYNTHETIC,
        "source_url": "https://pubg.com/en/news/6616",
        "source_id": f"synthetic-{evidence_id}",
        "language": Language.KOREAN,
        "observed_at": NOW - timedelta(days=1),
        "period": EvidencePeriod.COMPARABLE_REFERENCE,
        "sentiment": Sentiment.POSITIVE,
        "summary": "합성 관점에서 고정 피해가 결과 예측 가능성을 높일 가능성이 있음.",
        "mechanism_tags": ["predictability"],
        "relevance": 0.9,
        "synthetic": True,
    }
    values.update(updates)
    return UpdateEvidenceItem(**values)


def samples(insufficient: int = 0) -> list[LanguageSample]:
    languages = list(Language)
    return [
        LanguageSample(
            language=language,
            general_count=0 if index < insufficient else 100,
            mechanism_count=0 if index < insufficient else 15,
        )
        for index, language in enumerate(languages)
    ]


def risk(
    category: UpdateRiskCategory = UpdateRiskCategory.BALANCE_REGRESSION,
    severity: Severity = Severity.MEDIUM,
) -> UpdateRiskItem:
    return UpdateRiskItem(
        risk_id=f"risk-{category.value}",
        category=category,
        title="성능 역전 가능성",
        severity=severity,
        affected_personas=[PersonaKind.CORE_GAMEPLAY],
        evidence_ids=["fx-dragunov-ko-001"],
        failure_path="고정 피해와 반동의 조합으로 메타가 쏠릴 가능성이 있음.",
        revision_question="테스트 서버에서 승률과 평균 피해를 확인할 수 있는가?",
        confidence=0.8,
    )


def test_weapon_details_accept_explicit_not_applicable():
    assert weapon_brief().details.rate_of_fire == "해당 없음"


def test_update_type_must_match_discriminated_details():
    with pytest.raises(ValidationError, match="details kind must match update_type"):
        weapon_brief(update_type=UpdateType.UI_UX)


def test_ui_ux_requires_every_type_specific_field_but_accepts_not_applicable():
    with pytest.raises(ValidationError, match="possible_errors"):
        UiUxDetails(
            changed_screen="상점",
            user_journey="상품 선택 → 결제",
            exposed_information="확률",
            possible_errors="",
        )
    assert UiUxDetails(
        changed_screen="상점",
        user_journey="상품 선택 → 결제",
        exposed_information="확률",
        possible_errors="해당 없음",
    ).possible_errors == "해당 없음"


def test_system_rules_requires_existing_user_impact():
    with pytest.raises(ValidationError, match="existing_user_impact"):
        SystemRulesDetails(
            participation_conditions="레벨 10 이상",
            rewards="BP",
            restrictions="주 1회",
            exception_rules="해당 없음",
            existing_user_impact="",
        )


def test_feedback_rejects_cutoff_leakage():
    brief = weapon_brief()
    with pytest.raises(ValidationError, match="cutoff leakage"):
        UpdateFeedbackBundle(
            run_id=brief.run_id,
            producer=Producer.COLLECTOR,
            input_refs=[brief.ref],
            input_mode="fixture",
            cutoff_at=brief.cutoff_at,
            search_log=[],
            samples=[],
            evidence=[evidence(observed_at=brief.cutoff_at)],
        )


def test_comparable_reference_is_not_actual_after_reaction():
    item = evidence()
    assert item.period is EvidencePeriod.COMPARABLE_REFERENCE
    assert item.period is not EvidencePeriod.AFTER


def test_reaction_signal_rejects_unknown_evidence_reference():
    with pytest.raises(ValueError, match="unknown evidence"):
        ReactionSignal(
            signal_id="positive-predictability",
            title="예측 가능성 상승",
            summary="고정 피해가 공정성 인식을 높일 가능성이 있음.",
            sentiment=Sentiment.POSITIVE,
            evidence_ids=["missing-id"],
            confidence=0.8,
        ).validate_refs({"known-id"})


def test_evidence_pack_rejects_sentiment_label_mismatch():
    with pytest.raises(ValidationError, match="positive signal references non-positive evidence"):
        UpdateEvidencePack(
            run_id="update-run",
            producer=Producer.EVIDENCE_RAG,
            input_refs=["collector:update-run"],
            positive_signals=[
                ReactionSignal(
                    signal_id="positive-predictability",
                    title="예측 가능성 상승",
                    summary="결과를 예측하기 쉬워질 가능성이 있음.",
                    sentiment=Sentiment.POSITIVE,
                    evidence_ids=["fx-negative"],
                    confidence=0.8,
                )
            ],
            negative_signals=[],
            split_conditions=[],
            persona_impacts=[],
            language_insights=[],
            evidence=[evidence("fx-negative", sentiment=Sentiment.NEGATIVE)],
        )


def test_external_incomplete_impact_is_representable_with_errors():
    assessment = UpdateImpactAssessment(
        run_id="update-run",
        status=ArtifactStatus.PARTIAL,
        producer=Producer.EVENT_REDTEAM,
        input_refs=["evidence_rag:update-run"],
        errors=[
            PipelineError(
                code=ErrorCode.INSUFFICIENT_EVIDENCE,
                message="외부 근거가 부족해 영향 분석을 완료하지 못함",
            )
        ],
        expected_positive=[],
        expected_negative=[],
        risks=[],
        validation_metrics=[],
    )
    assert assessment.errors[0].code is ErrorCode.INSUFFICIENT_EVIDENCE


def test_decision_brief_carries_official_context():
    brief = weapon_brief()
    decision_brief = UpdateDecisionBrief(
        run_id=brief.run_id,
        producer=Producer.ORCHESTRATOR,
        input_refs=[brief.ref],
        decision=UpdateDecision.TEST,
        executive_summary="실전 지표를 확인한 뒤 출시한다.",
        official_context=brief.official_context,
        official_context_url=brief.official_context_url,
        expected_positive=[],
        expected_negative=[],
        split_conditions=[],
        persona_impacts=[],
        language_insights=[],
        top_risks=[],
        validation_metrics=[],
        evidence=[],
        recommendations=[],
    )
    assert decision_brief.official_context == brief.official_context
    assert decision_brief.official_context_url == brief.official_context_url


@pytest.mark.parametrize(
    ("risks", "insufficient", "metrics_complete", "analysis_incomplete", "expected"),
    [
        ([], 0, True, False, UpdateDecision.GO),
        ([risk()], 0, True, False, UpdateDecision.TEST),
        (
            [risk(UpdateRiskCategory.FAIRNESS_REGRESSION, Severity.HIGH)],
            0,
            True,
            False,
            UpdateDecision.REVISE,
        ),
        ([], 3, True, False, UpdateDecision.HOLD),
        ([], 0, False, False, UpdateDecision.HOLD),
        ([], 0, True, True, UpdateDecision.HOLD),
    ],
)
def test_update_decision_policy(
    risks,
    insufficient,
    metrics_complete,
    analysis_incomplete,
    expected,
):
    decision, reason = decide_update(
        samples(insufficient),
        risks,
        metrics_complete=metrics_complete,
        analysis_incomplete=analysis_incomplete,
    )
    assert decision is expected
    assert reason
