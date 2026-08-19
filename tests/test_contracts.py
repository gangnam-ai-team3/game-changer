from datetime import timedelta

import pytest
from pydantic import ValidationError

from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from contracts import EvidenceItem, EvidencePack, FeedbackBundle, InputMode, ValidatedDecision


def test_event_dates_must_be_ordered(event):
    with pytest.raises(ValidationError, match="starts_at must be earlier"):
        event.model_copy(update={"ends_at": event.starts_at}, deep=True).__class__.model_validate(
            {**event.model_dump(), "ends_at": event.starts_at}
        )


def test_cutoff_leak_is_rejected(feedback):
    leaked = feedback.evidence[0].model_copy(update={"observed_at": feedback.cutoff_at})
    payload = feedback.model_dump()
    payload["evidence"][0] = leaked.model_dump()
    with pytest.raises(ValidationError, match="cutoff leakage"):
        FeedbackBundle.model_validate(payload)


def test_personal_data_and_extra_fields_are_rejected(feedback):
    payload = feedback.evidence[0].model_dump()
    payload["contains_personal_data"] = True
    payload["username"] = "forbidden"
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(payload)


def test_all_fixture_evidence_is_strictly_pre_cutoff(feedback):
    assert feedback.evidence
    assert all(item.observed_at < feedback.cutoff_at for item in feedback.evidence)
    assert max(item.observed_at for item in feedback.evidence) == feedback.cutoff_at - timedelta(days=1)


def test_feedback_bundle_identifies_fixture_input(feedback):
    assert feedback.input_mode == InputMode.FIXTURE


def test_evidence_pack_rejects_dangling_internal_evidence_refs(feedback):
    pack = EvidenceRagAgent().run(feedback)
    issue = pack.issues[0].model_copy(update={"evidence_ids": ["missing-id"]})
    payload = pack.model_dump()
    payload["issues"][0] = issue.model_dump()
    with pytest.raises(ValidationError, match="unknown evidence"):
        EvidencePack.model_validate(payload)


def test_evidence_pack_rejects_issue_without_matching_mechanism_tag(feedback):
    pack = EvidenceRagAgent().run(feedback)
    wrong = next(item for item in pack.evidence if pack.issues[0].category.value not in item.mechanism_tags)
    payload = pack.model_dump()
    payload["issues"][0]["evidence_ids"] = [wrong.evidence_id]
    with pytest.raises(ValidationError, match="category does not match evidence tags"):
        EvidencePack.model_validate(payload)


def test_validated_decision_rejects_revision_for_unvalidated_risk(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    risks = EventRedteamAgent().run(event, pack)
    decision = AuditStrategyAgent().run(feedback, pack, risks)
    payload = decision.model_dump()
    payload["priority_revisions"][0]["addresses_risk_ids"] = ["rejected-risk"]
    with pytest.raises(ValidationError, match="revision references unvalidated risk"):
        ValidatedDecision.model_validate(payload)
