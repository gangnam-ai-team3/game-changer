from __future__ import annotations

import pytest

from evaluation.fixtures import load_demo_event, load_feedback_fixture


@pytest.fixture
def event():
    return load_demo_event("test-run")


@pytest.fixture
def feedback(event):
    return load_feedback_fixture(event).model_copy(update={"input_refs": [event.ref]})
