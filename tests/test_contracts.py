from datetime import timedelta

import pytest
from pydantic import ValidationError

from contracts import EvidenceItem, FeedbackBundle


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
