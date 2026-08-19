import pytest

from contracts import Decision, Language, LanguageSample, PersonaKind, RiskCategory, RiskItem, Severity
from policy import POLICY_VERSION, decide, expected_severity


def sample(language: Language, sufficient: bool = True) -> LanguageSample:
    return LanguageSample(
        language=language,
        general_count=100 if sufficient else 99,
        mechanism_count=15 if sufficient else 14,
    )


def risk(severity: Severity) -> RiskItem:
    return RiskItem(
        risk_id=f"risk-{severity.value.lower()}",
        category=RiskCategory.DOUBLE_GACHA,
        title="위험",
        severity=severity,
        affected_personas=[PersonaKind.VALUE_SEEKING],
        affected_languages=[Language.ENGLISH],
        evidence_ids=["evidence-1"],
        failure_path="실패 경로",
        revision_question="무엇을 바꿀 것인가?",
        confidence=0.8,
    )


@pytest.mark.parametrize(
    ("insufficient", "risks", "analysis_incomplete", "expected"),
    [
        (0, [risk(Severity.CRITICAL)], False, Decision.HOLD),
        (3, [], False, Decision.HOLD),
        (0, [risk(Severity.HIGH)], False, Decision.REVISE),
        (1, [], False, Decision.REVISE),
        (0, [], False, Decision.GO),
        (0, [], True, Decision.HOLD),
    ],
)
def test_decision_policy_table(insufficient, risks, analysis_incomplete, expected):
    samples = [sample(language, index >= insufficient) for index, language in enumerate(Language)]
    decision, reason = decide(samples, risks, analysis_incomplete=analysis_incomplete)
    assert decision == expected
    assert reason


def test_closed_policy_version_and_severity():
    assert POLICY_VERSION == "1.0"
    assert expected_severity(RiskCategory.DOUBLE_GACHA) == Severity.HIGH
    assert expected_severity(RiskCategory.EXPIRING_CURRENCY) == Severity.MEDIUM
    assert expected_severity(RiskCategory.FAIRNESS) is None
