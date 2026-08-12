from agents.audit_strategy import AuditStrategyAgent
from agents.audit_strategy import agent as audit_module
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


def test_audit_rejects_existing_but_semantically_unrelated_evidence(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    target = assessment.risks[0]
    unrelated = next(
        item for item in pack.evidence if target.category.value not in item.mechanism_tags
    )
    changed = target.model_copy(update={"evidence_ids": [unrelated.evidence_id]})
    decision = AuditStrategyAgent().run(
        feedback,
        pack,
        assessment.model_copy(update={"risks": [changed, *assessment.risks[1:]]}),
    )
    assert changed.risk_id in {item.risk_id for item in decision.rejected_risks}


def test_audit_rejects_risk_outside_closed_policy(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    unsupported = assessment.risks[0].model_copy(
        update={"risk_id": "risk-fairness", "category": RiskCategory.FAIRNESS}
    )
    decision = AuditStrategyAgent().run(
        feedback,
        pack,
        assessment.model_copy(update={"risks": [unsupported]}),
    )
    assert decision.validated_risks == []
    assert decision.rejected_risks[0].risk_id == "risk-fairness"


def test_audit_llm_rechecks_semantic_and_closed_policy_risks(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    baseline = AuditStrategyAgent().run(feedback, pack, assessment)
    target = assessment.risks[0]
    unrelated = next(item for item in pack.evidence if target.category.value not in item.mechanism_tags)
    wrong_tag = target.model_copy(update={"risk_id": "risk-wrong-tag", "evidence_ids": [unrelated.evidence_id]})
    unknown_policy = target.model_copy(
        update={"risk_id": "risk-fairness", "category": RiskCategory.FAIRNESS}
    )
    payload = baseline.model_dump()
    payload["validated_risks"] = [wrong_tag.model_dump(), unknown_policy.model_dump()]
    payload["rejected_risks"] = []
    payload["priority_revisions"] = [
        {
            **payload["priority_revisions"][0],
            "addresses_risk_ids": [wrong_tag.risk_id],
        },
        {
            **payload["priority_revisions"][1],
            "addresses_risk_ids": [unknown_policy.risk_id],
        },
    ]
    proposal = baseline.__class__.model_validate(payload)
    monkeypatch.setattr(audit_module, "parse_structured", lambda **_kwargs: proposal)

    decision = AuditStrategyAgent(use_llm=True, client=object()).run(feedback, pack, assessment)

    assert decision.validated_risks == []
    assert {item.risk_id for item in decision.rejected_risks} == {
        wrong_tag.risk_id,
        unknown_policy.risk_id,
    }
    assert decision.priority_revisions == []
