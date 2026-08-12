from types import SimpleNamespace

import pytest

from agents.audit_strategy import AuditStrategyAgent
from agents.audit_strategy import agent as audit_module
from agents.event_redteam import EventRedteamAgent
from agents.event_redteam import agent as redteam_module
from agents.evidence_rag import EvidenceRagAgent
from agents.evidence_rag import agent as evidence_module
from agents.structured import StructuredModelError
from contracts import Decision, LanguageSample, RiskCategory

OFFICIAL_TARGETS = {
    RiskCategory.DOUBLE_GACHA,
    RiskCategory.FRAGMENTED_FLOW,
    RiskCategory.OPAQUE_PROGRESS,
    RiskCategory.RANDOM_BONUS,
}


def risk_core(assessment):
    return [
        (risk.category, risk.severity, tuple(risk.evidence_ids), tuple(risk.affected_personas))
        for risk in assessment.risks
    ]


def decision_core(decision):
    return (
        decision.decision,
        tuple(risk.risk_id for risk in decision.validated_risks),
        tuple(risk.risk_id for risk in decision.rejected_risks),
        tuple(
            (tuple(action.addresses_risk_ids), action.priority)
            for action in decision.priority_revisions
        ),
    )


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


def test_audit_llm_only_accepts_narrative_schema(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    baseline = AuditStrategyAgent().run(feedback, pack, assessment)
    narrative = audit_module.AuditNarrative(
        decision_reason="LLM은 설명만 보강합니다.", revisions=[]
    )

    def fake_parse_structured(**kwargs):
        assert kwargs["output_type"] is audit_module.AuditNarrative
        return narrative

    monkeypatch.setattr(audit_module, "parse_structured", fake_parse_structured)

    decision = AuditStrategyAgent(use_llm=True, client=object()).run(feedback, pack, assessment)

    assert decision_core(decision) == decision_core(baseline)


def test_redteam_llm_text_cannot_override_core(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    base = EventRedteamAgent().run(event, pack)
    target = base.risks[0]
    responses = iter(
        [
            redteam_module.RedteamNarrative(
                risks=[
                    redteam_module.RiskNarrative(
                        category=target.category,
                        title="첫 번째 설명",
                        failure_path="첫 번째 실패 경로",
                        revision_question="첫 번째 질문",
                        evidence_ids=target.evidence_ids[:1],
                    )
                ]
            ),
            redteam_module.RedteamNarrative(
                risks=[
                    redteam_module.RiskNarrative(
                        category=target.category,
                        title="두 번째 설명",
                        failure_path="두 번째 실패 경로",
                        revision_question="두 번째 질문",
                        evidence_ids=target.evidence_ids[-1:],
                    )
                ]
            ),
        ]
    )
    monkeypatch.setattr(redteam_module, "parse_structured", lambda **_kwargs: next(responses))
    agent = EventRedteamAgent(use_llm=True, client=object())
    first = agent.run(event, pack)
    second = agent.run(event, pack)
    assert first.risks[0].title != second.risks[0].title
    assert risk_core(first) == risk_core(second) == risk_core(base)


def test_audit_llm_text_cannot_override_decision_or_links(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    base = AuditStrategyAgent().run(feedback, pack, assessment)
    category = base.validated_risks[0].category
    responses = iter(
        [
            audit_module.AuditNarrative(
                decision_reason="첫 번째 설명",
                revisions=[
                    audit_module.RevisionNarrative(
                        category=category,
                        title="첫 수정안",
                        change="첫 변경 문장",
                        success_metric="첫 지표 문장",
                    )
                ],
            ),
            audit_module.AuditNarrative(
                decision_reason="두 번째 설명",
                revisions=[
                    audit_module.RevisionNarrative(
                        category=category,
                        title="둘째 수정안",
                        change="둘째 변경 문장",
                        success_metric="둘째 지표 문장",
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(audit_module, "parse_structured", lambda **_kwargs: next(responses))
    agent = AuditStrategyAgent(use_llm=True, client=object())
    first = agent.run(feedback, pack, assessment)
    second = agent.run(feedback, pack, assessment)
    assert first.decision_reason != second.decision_reason
    assert decision_core(first) == decision_core(second) == decision_core(base)


def test_evidence_llm_enriches_text_without_changing_core(monkeypatch, feedback):
    deterministic = EvidenceRagAgent().run(feedback)
    target = deterministic.issues[0]

    def fake_parse_structured(**_kwargs):
        return evidence_module.EvidenceNarrative(
            issues=[
                evidence_module.IssueNarrative(
                    category=target.category,
                    title="AI가 정리한 제목",
                    summary="AI가 근거 범위 안에서 정리한 설명",
                    evidence_ids=target.evidence_ids[:2],
                )
            ],
            personas=[],
            exploratory_insights=[],
        )

    monkeypatch.setattr(evidence_module, "parse_structured", fake_parse_structured)
    monkeypatch.setattr(evidence_module, "embedding_rank", lambda _q, evidence, **_k: evidence)
    enriched = EvidenceRagAgent(use_llm=True, client=SimpleNamespace()).run(feedback)

    assert enriched.issues[0].title == "AI가 정리한 제목"
    assert enriched.issues[0].category == target.category
    assert enriched.issues[0].evidence_ids == target.evidence_ids
    assert enriched.issues[0].confidence == target.confidence


def test_evidence_llm_rejects_unknown_evidence(monkeypatch, feedback):
    target = EvidenceRagAgent().run(feedback).issues[0]

    def fake_parse_structured(**_kwargs):
        return evidence_module.EvidenceNarrative(
            issues=[
                evidence_module.IssueNarrative(
                    category=target.category,
                    title="제목",
                    summary="설명",
                    evidence_ids=["invented-id"],
                )
            ],
            personas=[],
            exploratory_insights=[],
        )

    monkeypatch.setattr(evidence_module, "parse_structured", fake_parse_structured)
    monkeypatch.setattr(evidence_module, "embedding_rank", lambda _q, evidence, **_k: evidence)
    with pytest.raises(StructuredModelError, match="unknown evidence"):
        EvidenceRagAgent(use_llm=True, client=SimpleNamespace()).run(feedback)


def test_evidence_llm_rejects_evidence_outside_issue(monkeypatch, feedback):
    target = EvidenceRagAgent().run(feedback).issues[0]
    unrelated = next(
        item for item in feedback.evidence if target.category.value not in item.mechanism_tags
    )
    narrative = evidence_module.EvidenceNarrative(
        issues=[
            evidence_module.IssueNarrative(
                category=target.category,
                title="제목",
                summary="설명",
                evidence_ids=[unrelated.evidence_id],
            )
        ],
        personas=[],
        exploratory_insights=[],
    )

    monkeypatch.setattr(evidence_module, "parse_structured", lambda **_kwargs: narrative)
    monkeypatch.setattr(evidence_module, "embedding_rank", lambda _q, evidence, **_k: evidence)
    with pytest.raises(StructuredModelError, match="unknown evidence"):
        EvidenceRagAgent(use_llm=True, client=SimpleNamespace()).run(feedback)
