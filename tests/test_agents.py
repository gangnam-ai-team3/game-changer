from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from contracts import Decision, LanguageSample, RiskCategory

OFFICIAL_TARGETS = {
    RiskCategory.DOUBLE_GACHA,
    RiskCategory.FRAGMENTED_FLOW,
    RiskCategory.OPAQUE_PROGRESS,
    RiskCategory.RANDOM_BONUS,
}


def test_rag_builds_four_grounded_personas(feedback):
    pack = EvidenceRagAgent().run(feedback)
    assert len(pack.personas) == 4
    assert all(len(persona.evidence_ids) >= 15 for persona in pack.personas)
    assert all(insight.conclusion for insight in pack.language_insights)


def test_redteam_detects_official_mechanism_targets(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    assert OFFICIAL_TARGETS <= {risk.category for risk in assessment.risks}
    assert all(risk.evidence_ids for risk in assessment.risks)


def test_audit_returns_revise_and_rejects_unknown_evidence(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    first = assessment.risks[0].model_copy(update={"evidence_ids": ["does-not-exist"]})
    assessment = assessment.model_copy(update={"risks": [first, *assessment.risks[1:]]})
    decision = AuditStrategyAgent().run(feedback, pack, assessment)
    assert decision.decision == Decision.REVISE
    assert decision.rejected_risks[0].risk_id == first.risk_id


def test_three_insufficient_languages_force_hold(event, feedback):
    samples = [
        LanguageSample(
            language=sample.language,
            general_count=0 if index < 3 else sample.general_count,
            mechanism_count=0 if index < 3 else sample.mechanism_count,
        )
        for index, sample in enumerate(feedback.samples)
    ]
    feedback = feedback.model_copy(update={"samples": samples})
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    decision = AuditStrategyAgent().run(feedback, pack, assessment)
    assert decision.decision == Decision.HOLD
    assert sum(insight.conclusion is None for insight in pack.language_insights) == 3
