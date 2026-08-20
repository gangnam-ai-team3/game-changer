from __future__ import annotations

import pytest

from agents.evidence_rag import EvidenceRagAgent
from agents.structured import ClaudeBudget, StructuredModelError
import backend.app.main as api_main
from backend.app.schemas import PipelineRunRequest, UpdateRunRequest
from contracts import ErrorCode, InputMode
from evaluation.fixtures import load_feedback_fixture
from orchestrator import EventPreflightOrchestrator
from res.team_adapters import (
    EventJellyRedteamAdapter,
    EventJinbaeAuditAdapter,
    UpdateJellyRedteamAdapter,
    UpdateJinbaeAuditAdapter,
)
from tests.test_api import request_payload
from tests.test_update_api import payload as update_payload
from update_review.evidence import UpdateEvidenceAgent
from update_review.fixtures import load_update_feedback_fixture
from update_review.orchestrator import UpdateReviewOrchestrator


def _request(pipeline: str, *, source_mode: str = "corpus", use_llm: bool):
    model, payload = (
        (PipelineRunRequest, request_payload())
        if pipeline == "event"
        else (UpdateRunRequest, update_payload())
    )
    overrides = {"source_mode": source_mode, "use_llm": use_llm}
    if pipeline == "event":
        overrides["llm_provider"] = "openai"
    return model.model_validate(payload | overrides)


class _FixtureCorpusCollector:
    instances = []

    def __init__(self, db_path):
        self.db_path = db_path
        self.instances.append(self)

    def run(self, artifact, _options=None, on_event=None):
        if hasattr(artifact, "event_name"):
            return load_feedback_fixture(artifact).model_copy(
                update={"input_refs": [artifact.ref], "input_mode": InputMode.CORPUS}
            )
        return load_update_feedback_fixture(artifact).model_copy(
            update={"input_mode": InputMode.CORPUS}
        )


def _install_team_fakes(monkeypatch):
    budgets, runners, probes = [], [], []

    def make_budget(**kwargs):
        budget = ClaudeBudget(**kwargs)
        budgets.append(budget)
        return budget

    class FakeJellyRunner:
        def __init__(self, *, budget):
            self.budget, self.calls = budget, []
            runners.append(self)

        def run(self, rows):
            self.calls.append(rows)
            return {
                "rows": [
                    {
                        "index": index,
                        "trend": "위험",
                        "cause": "근거에서 위험 원인이 확인됩니다.",
                        "fix": "근거에 맞춰 수정안을 확인해야 합니다.",
                    }
                    for index in range(len(rows))
                ],
                "synthesis": [],
            }

    class FakeJinbaeProbe:
        def __init__(self, *, budget):
            self.budget, self.calls = budget, []
            probes.append(self)

        def run(self, claim_text, candidate_chunks):
            self.calls.append((claim_text, candidate_chunks))
            return {
                "verdict": "grounded",
                "citations": [],
                "rationale": "제공된 근거로 뒷받침됩니다.",
            }

    monkeypatch.setattr(api_main, "ClaudeBudget", make_budget)
    monkeypatch.setattr(api_main, "JellyRunner", FakeJellyRunner)
    monkeypatch.setattr(api_main, "JinbaeProbe", FakeJinbaeProbe)
    return budgets, runners, probes


@pytest.mark.parametrize(
    ("pipeline", "use_llm"),
    [("event", True), ("event", False), ("update", True), ("update", False)],
    ids=["event-team", "event-opt-out", "update-team", "update-opt-out"],
)
def test_corpus_team_wiring(monkeypatch, tmp_path, pipeline, use_llm):
    captured = []
    original = (
        EventPreflightOrchestrator
        if pipeline == "event"
        else UpdateReviewOrchestrator
    )

    class SpyOrchestrator:
        def __init__(self, **kwargs):
            captured.append(kwargs)
            self.delegate = original(**kwargs)

        def run(self, *args, **kwargs):
            return self.delegate.run(*args, **kwargs)

    _FixtureCorpusCollector.instances = []
    budgets, runners, probes = _install_team_fakes(monkeypatch)
    monkeypatch.setattr(api_main, "ROOT", tmp_path)
    monkeypatch.setattr(
        api_main,
        "EventCorpusCollector" if pipeline == "event" else "UpdateCorpusCollector",
        _FixtureCorpusCollector,
    )
    monkeypatch.setattr(
        api_main,
        "EventPreflightOrchestrator" if pipeline == "event" else "UpdateReviewOrchestrator",
        SpyOrchestrator,
    )

    result = (
        api_main._run(_request(pipeline, use_llm=use_llm), "team-event")
        if pipeline == "event"
        else api_main._run_update(_request(pipeline, use_llm=use_llm), "team-update")
    )
    kwargs = captured[0]
    provider = result["llm_provider"] if pipeline == "event" else result.llm_provider
    requested = result["llm_requested"] if pipeline == "event" else result.llm_requested

    assert kwargs["collector"] is _FixtureCorpusCollector.instances[0]
    if not use_llm:
        assert not budgets and not runners and not probes
        assert set(kwargs) == (
            {"use_llm", "llm_provider", "collector"}
            if pipeline == "event"
            else {"use_llm", "collector"}
        )
        assert (requested, provider) == (False, "deterministic")
        return

    evidence = kwargs["evidence_rag" if pipeline == "event" else "evidence"]
    assert isinstance(
        evidence, EvidenceRagAgent if pipeline == "event" else UpdateEvidenceAgent
    )
    assert evidence.use_llm is False
    if pipeline == "update":
        assert kwargs["budget"] is budgets[0]
        assert evidence.rewrite_personas is True
        assert evidence.budget is budgets[0]
    assert isinstance(
        kwargs["redteam"],
        EventJellyRedteamAdapter if pipeline == "event" else UpdateJellyRedteamAdapter,
    )
    assert isinstance(
        kwargs["audit"],
        EventJinbaeAuditAdapter if pipeline == "event" else UpdateJinbaeAuditAdapter,
    )
    assert kwargs["redteam"].enabled is kwargs["audit"].enabled is True
    assert len(budgets) == len(runners) == len(probes) == 1
    assert runners[0].budget is probes[0].budget is budgets[0]
    assert budgets[0].max_requests == 3
    assert len(runners[0].calls) == len(probes[0].calls) == 1
    assert (requested, provider) == (True, "claude")


@pytest.mark.parametrize("pipeline", ["event", "update"])
def test_non_corpus_llm_requests_do_not_construct_team_sidecars(monkeypatch, pipeline):
    captured = []
    budgets, runners, probes = _install_team_fakes(monkeypatch)

    class StopAfterWiring(RuntimeError):
        pass

    class StopOrchestrator:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def run(self, *args, **kwargs):
            raise StopAfterWiring

    monkeypatch.setattr(
        api_main,
        "EventPreflightOrchestrator" if pipeline == "event" else "UpdateReviewOrchestrator",
        StopOrchestrator,
    )
    if pipeline == "event":
        call = lambda: api_main._run(
            _request(pipeline, source_mode="fixture", use_llm=True), "regular-event"
        )
    else:
        call = lambda: api_main._run_update(
            _request(pipeline, source_mode="fixture", use_llm=True), "regular-update"
        )

    with pytest.raises(StopAfterWiring):
        call()

    assert not budgets and not runners and not probes
    if pipeline == "event":
        assert captured[0]["llm_provider"] == "openai"
    assert set(captured[0]) == (
        {"use_llm", "llm_provider", "collector"}
        if pipeline == "event"
        else {"use_llm", "collector"}
    )


def test_update_corpus_jelly_failure_falls_back_and_continues_jinbae(
    monkeypatch, tmp_path
):
    jelly_calls, probe_calls = [], []

    class UnavailableJellyRunner:
        def __init__(self, *, budget):
            pass

        def run(self, rows):
            jelly_calls.append(rows)
            raise StructuredModelError(ErrorCode.SOURCE_UNAVAILABLE, "safe")

    class GroundedJinbaeProbe:
        def __init__(self, *, budget):
            pass

        def run(self, claim_text, candidate_chunks):
            probe_calls.append((claim_text, candidate_chunks))
            return {
                "verdict": "grounded",
                "citations": [candidate_chunks[0]["id"]],
                "rationale": "제공된 근거로 뒷받침됩니다.",
            }

    _FixtureCorpusCollector.instances = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(api_main, "ROOT", tmp_path)
    monkeypatch.setattr(api_main, "UpdateCorpusCollector", _FixtureCorpusCollector)
    monkeypatch.setattr(api_main, "JellyRunner", UnavailableJellyRunner)
    monkeypatch.setattr(api_main, "JinbaeProbe", GroundedJinbaeProbe)

    baseline = api_main._run_update(
        _request("update", use_llm=False), "update-complete-baseline"
    )

    result = api_main._run_update(
        _request("update", use_llm=True), "update-jelly-failure"
    )

    assert len(jelly_calls) == 1
    assert len(probe_calls) == 1
    assert result.fallback_used is True
    assert result.analysis_incomplete is False
    assert result.brief.decision == baseline.brief.decision
    assert [
        (
            risk.risk_id,
            risk.category,
            risk.severity,
            risk.evidence_ids,
            risk.confidence,
        )
        for risk in result.impact.risks
    ] == [
        (
            risk.risk_id,
            risk.category,
            risk.severity,
            risk.evidence_ids,
            risk.confidence,
        )
        for risk in baseline.impact.risks
    ]
    event_nodes = [(event.agent, event.node) for event in result.events]
    assert ("event_redteam", "fallback") in event_nodes
    assert ("audit_strategy", "jinbae_probe_started") in event_nodes
    assert ("audit_strategy", "jinbae_probe_checked") in event_nodes
    assert "safe" not in " ".join(event.message for event in result.events)
    assert (result.llm_requested, result.llm_provider) == (True, "claude")
