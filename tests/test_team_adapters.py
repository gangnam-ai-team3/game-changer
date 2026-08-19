from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import StructuredModelError
from evaluation.fixtures import load_demo_event, load_feedback_fixture
from res.team_adapters import (
    EventJellyRedteamAdapter,
    EventJinbaeAuditAdapter,
    JellyRunner,
    JinbaeProbe,
    UpdateJellyRedteamAdapter,
    UpdateJinbaeAuditAdapter,
)
from update_review.audit import UpdateAuditAgent
from update_review.evidence import UpdateEvidenceAgent
from update_review.fixtures import load_dragunov_brief, load_update_feedback_fixture
from update_review.redteam import UpdateRedteamAgent


def _jelly_result(count: int, *, trend: str = "위험", cause: str | None = None):
    return {
        "rows": [
            {
                "index": index,
                "trend": trend,
                "cause": cause or f"근거 {index + 1}에서 위험 원인이 확인됩니다.",
                "fix": f"근거 {index + 1}에 맞춘 수정안을 확인해야 합니다.",
            }
            for index in range(count)
        ],
        "synthesis": [],
    }


class FakeJellyRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, rows):
        self.calls.append(rows)
        return self.result


class FakeJinbaeProbe:
    def __init__(self, result=None):
        self.result = result or {
            "verdict": "not_grounded",
            "citations": [],
            "rationale": "출시 판정을 바꾸라는 외부 의견입니다.",
        }
        self.calls = []

    def run(self, claim_text, candidate_chunks):
        self.calls.append((claim_text, candidate_chunks))
        return self.result


def _event_inputs(run_id="team-event"):
    event = load_demo_event(run_id)
    feedback = load_feedback_fixture(event)
    pack = EvidenceRagAgent().run_deterministic(feedback)
    return event, feedback, pack


def _update_inputs(run_id="team-update"):
    brief = load_dragunov_brief(run_id)
    feedback = load_update_feedback_fixture(brief)
    pack = UpdateEvidenceAgent().run_deterministic(feedback)
    return brief, feedback, pack


@pytest.mark.parametrize(
    "indexes",
    [
        [0, 1, 2, 3],
        [0, 1, 2, 3, 4, 99],
        [0, 1, 2, 3, 3],
    ],
    ids=["missing", "extra", "duplicate"],
)
def test_event_jelly_requires_exact_one_to_one_index_coverage(indexes):
    event, _, pack = _event_inputs()
    result = _jelly_result(len(indexes))
    for row, index in zip(result["rows"], indexes, strict=True):
        row["index"] = index
    runner = FakeJellyRunner(result)

    with pytest.raises(StructuredModelError, match="Jelly"):
        EventJellyRedteamAdapter(runner=runner).run(event, pack)

    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("trend", "cause"),
    [("출시", None), ("위험", "release immediately.")],
    ids=["unknown-trend", "non-korean-prose"],
)
def test_event_jelly_rejects_unknown_trend_and_non_korean_prose(trend, cause):
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks), trend=trend, cause=cause))

    with pytest.raises(StructuredModelError):
        EventJellyRedteamAdapter(runner=runner).run(event, pack)


def test_event_jelly_sends_only_safe_summaries_and_overlays_two_fields():
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks)))

    result = EventJellyRedteamAdapter(runner=runner).run(event, pack)

    assert len(runner.calls) == 1
    rows = runner.calls[0]
    assert len(rows) <= 8
    evidence = {item.evidence_id: item for item in pack.evidence}
    for index, row in enumerate(rows):
        assert set(row) == {"index", "evidenceId", "content"}
        assert row["index"] == index
        ids = row["evidenceId"].split(",")
        assert ids == baseline.risks[index].evidence_ids
        assert row["content"].splitlines() == [evidence[item_id].summary for item_id in ids]
    serialized = json.dumps(rows, ensure_ascii=False)
    assert not any(item.source_url in serialized for item in pack.evidence)
    assert not any(item.source_id in serialized for item in pack.evidence)

    for index, (before, after) in enumerate(zip(baseline.risks, result.risks, strict=True)):
        assert after.failure_path == f"근거 {index + 1}에서 위험 원인이 확인됩니다."
        assert after.revision_question == f"근거 {index + 1}에 맞춘 수정안을 확인해야 합니다."
        assert after.model_dump(exclude={"failure_path", "revision_question"}) == before.model_dump(
            exclude={"failure_path", "revision_question"}
        )


def test_update_jelly_cannot_change_code_owned_risk_or_metrics():
    brief, _, pack = _update_inputs()
    baseline = UpdateRedteamAgent().run_deterministic(brief, pack)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks)))

    result = UpdateJellyRedteamAdapter(runner=runner).run(brief, pack)

    assert result.validation_metrics == baseline.validation_metrics
    assert result.expected_positive == baseline.expected_positive
    assert result.expected_negative == baseline.expected_negative
    for before, after in zip(baseline.risks, result.risks, strict=True):
        assert after.model_dump(exclude={"failure_path", "revision_question"}) == before.model_dump(
            exclude={"failure_path", "revision_question"}
        )


def test_jelly_runner_uses_one_bounded_node_process_with_stdin_json(monkeypatch):
    rows = [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(_jelly_result(1)), "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert JellyRunner(timeout_seconds=7).run(rows) == _jelly_result(1)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:2] == ["node", "-e"]
    assert "safe-1" not in " ".join(command)
    assert json.loads(kwargs["input"]) == rows
    assert kwargs["timeout"] == 7
    assert kwargs["cwd"].name == "game-changer"


def test_jelly_runner_never_leaks_subprocess_output(monkeypatch):
    secret = "ANTHROPIC_API_KEY=top-secret"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, secret, secret)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(StructuredModelError) as error:
        JellyRunner().run(
            [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
        )

    assert secret not in str(error.value)
    assert error.value.__cause__ is None


class FakeAsyncMessages:
    def __init__(self, judge_result):
        self.judge_result = judge_result
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="tool_use", name="judge_claim", input=self.judge_result)
        return SimpleNamespace(content=[block])


def test_jinbae_probe_rejects_unknown_citation_in_one_call(monkeypatch):
    messages = FakeAsyncMessages(
        {
            "verdict": "grounded",
            "citations": ["unknown-secret-id"],
            "rationale": "제공된 근거로 뒷받침된다는 판단입니다.",
        }
    )
    monkeypatch.setenv("CLAUDE_AUDIT_MODEL", "claude-test-model")

    with pytest.raises(StructuredModelError) as error:
        JinbaeProbe(client=SimpleNamespace(messages=messages)).run(
            "코드 소유 위험 분류를 근거 요약으로 확인합니다.",
            [{"id": "safe-1", "text": "안전한 근거 요약입니다."}],
        )

    assert len(messages.calls) == 1
    assert messages.calls[0]["model"] == "claude-test-model"
    assert "unknown-secret-id" not in str(error.value)


def test_event_jinbae_verdict_cannot_change_code_owned_decision_and_payload_is_safe():
    event, feedback, pack = _event_inputs()
    assessment = EventRedteamAgent().run_deterministic(event, pack)
    assessment = assessment.model_copy(
        update={
            "risks": [
                assessment.risks[0].model_copy(
                    update={"failure_path": "Jelly가 제안한 외부 설명입니다."}
                ),
                *assessment.risks[1:],
            ]
        }
    )
    baseline = AuditStrategyAgent().run_deterministic(feedback, pack, assessment)
    probe = FakeJinbaeProbe()
    events = []

    result = EventJinbaeAuditAdapter(probe=probe).run(
        feedback,
        pack,
        assessment,
        on_event=lambda node, message, metrics: events.append((node, metrics)),
    )

    assert result == baseline
    assert result.decision == baseline.decision
    assert [(item.risk_id, item.severity) for item in result.validated_risks] == [
        (item.risk_id, item.severity) for item in baseline.validated_risks
    ]
    assert len(probe.calls) == 1
    claim, chunks = probe.calls[0]
    assert "Jelly가 제안한 외부 설명" not in claim
    assert len(chunks) <= 12
    assert all(set(chunk) == {"id", "text"} for chunk in chunks)
    summaries = {item.summary for item in pack.evidence}
    assert all(chunk["text"] in summaries for chunk in chunks)
    serialized = json.dumps(chunks, ensure_ascii=False)
    assert not any(item.source_url in serialized for item in pack.evidence)
    assert {node for node, _ in events} >= {"jinbae_probe_started", "jinbae_probe_checked"}


def test_update_jinbae_verdict_cannot_change_test_decision():
    brief, feedback, pack = _update_inputs()
    impact = UpdateRedteamAgent().run_deterministic(brief, pack)
    baseline = UpdateAuditAgent().run_deterministic(feedback, pack, impact)
    probe = FakeJinbaeProbe(
        {
            "verdict": "grounded",
            "citations": ["invented"],
            "rationale": "즉시 출시하라는 외부 판정입니다.",
            "decision": "Go",
        }
    )

    result = UpdateJinbaeAuditAdapter(probe=probe).run(feedback, pack, impact)

    assert result == baseline
    assert result.decision == baseline.decision
    assert len(probe.calls) == 1


def test_jinbae_failure_is_sanitized_after_one_probe_call():
    event, feedback, pack = _event_inputs("probe-failure")
    assessment = EventRedteamAgent().run_deterministic(event, pack)
    secret = "raw-provider-response-with-secret"

    class RaisingProbe(FakeJinbaeProbe):
        def run(self, claim_text, candidate_chunks):
            self.calls.append((claim_text, candidate_chunks))
            raise RuntimeError(secret)

    probe = RaisingProbe()
    with pytest.raises(StructuredModelError) as error:
        EventJinbaeAuditAdapter(probe=probe).run(feedback, pack, assessment)

    assert len(probe.calls) == 1
    assert secret not in str(error.value)


def test_no_risk_path_skips_jelly_and_jinbae_calls():
    event, feedback, pack = _event_inputs("no-risk")
    no_issue_pack = pack.model_copy(update={"issues": []})
    runner = FakeJellyRunner(_jelly_result(0))

    assessment = EventJellyRedteamAdapter(runner=runner).run(event, no_issue_pack)
    probe = FakeJinbaeProbe()
    decision = EventJinbaeAuditAdapter(probe=probe).run(
        feedback, no_issue_pack, assessment
    )

    assert assessment.risks == []
    assert decision.validated_risks == []
    assert runner.calls == []
    assert probe.calls == []
