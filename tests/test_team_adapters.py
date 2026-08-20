from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import ClaudeBudget, StructuredModelError
from contracts import ErrorCode
from evaluation.fixtures import load_demo_event, load_feedback_fixture
from orchestrator import EventPreflightOrchestrator
from res import team_adapters as adapter_module
from res.team_adapters import (
    EventJellyRedteamAdapter,
    EventJinbaeAuditAdapter,
    JellyRunner,
    JinbaeProbe,
    UpdateJellyRedteamAdapter,
    UpdateJinbaeAuditAdapter,
)
from update_review.audit import UpdateAuditAgent
from update_review.collector import UpdateCollectorAgent
from update_review.evidence import UpdateEvidenceAgent
from update_review.fixtures import load_dragunov_brief, load_update_feedback_fixture
from update_review.orchestrator import UpdateReviewOrchestrator
from update_review.redteam import UpdateRedteamAgent


def _jelly_result(
    count: int,
    *,
    trend: str = "위험",
    cause: str | None = None,
    fix: str | None = None,
):
    return {
        "rows": [
            {
                "index": index,
                "trend": trend,
                "cause": cause or f"근거 {index + 1}에서 위험 원인이 확인됩니다.",
                "fix": fix or f"근거 {index + 1}에 맞춘 수정안을 확인해야 합니다.",
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


def _risk_core(risks):
    return [
        (
            risk.risk_id,
            risk.category,
            risk.severity,
            risk.evidence_ids,
            risk.confidence,
        )
        for risk in risks
    ]


@pytest.mark.parametrize(
    "indexes",
    [
        [0, 1, 2, 3],
        [0, 1, 2, 3, "4"],
        [0, 1, 2, 3, 99],
        [0, 1, 2, 3, 3],
    ],
    ids=["missing", "invalid", "unknown", "duplicate"],
)
def test_event_jelly_requires_exact_one_to_one_index_coverage(indexes):
    event, _, pack = _event_inputs()
    result = _jelly_result(len(indexes))
    for row, index in zip(result["rows"], indexes, strict=True):
        row["index"] = index
    runner = FakeJellyRunner(result)

    with pytest.raises(StructuredModelError) as error:
        EventJellyRedteamAdapter(runner=runner, enabled=True).run(event, pack)

    assert error.value.code is ErrorCode.SCHEMA_INVALID
    assert len(runner.calls) == 1


def test_event_jelly_rejects_unknown_trend_as_schema_invalid():
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks), trend="출시"))

    with pytest.raises(StructuredModelError) as error:
        EventJellyRedteamAdapter(runner=runner, enabled=True).run(event, pack)

    assert error.value.code is ErrorCode.SCHEMA_INVALID


def test_jelly_edits_middle_dot_and_blank_fix_without_changing_code_owned_risk(
    monkeypatch,
):
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    result = _jelly_result(len(baseline.risks))
    result["rows"][0].update(
        cause="본질적으로 근거·지표를 다시 확인해야 합니다",
        fix="",
    )
    validated = []
    original_validator = adapter_module.require_native_business_korean

    def record_validator(values):
        validated.extend(values)
        original_validator(values)

    monkeypatch.setattr(adapter_module, "require_native_business_korean", record_validator)
    runner = FakeJellyRunner(result)
    actual = EventJellyRedteamAdapter(runner=runner, enabled=True).run(event, pack)

    assert adapter_module._edit_jelly_sentence(
        result["rows"][0]["cause"], baseline.risks[0].failure_path
    ) == "근거, 지표를 다시 확인해야 합니다."
    assert adapter_module._edit_jelly_sentence(
        result["rows"][0]["fix"], baseline.risks[0].revision_question
    ) == baseline.risks[0].revision_question
    assert validated[0] == "근거, 지표를 다시 확인해야 합니다."
    assert validated[1] == baseline.risks[0].revision_question
    assert actual == baseline
    assert actual.model_dump_json() == baseline.model_dump_json()


def test_jelly_english_only_prose_falls_back_safely():
    assert adapter_module._edit_jelly_sentence(
        "release immediately.", "한국어 대체 문장입니다"
    ) == "한국어 대체 문장입니다."


def test_jelly_filler_only_korean_prose_falls_back_without_error():
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    result = _jelly_result(len(baseline.risks))
    result["rows"][0]["cause"] = "궁극적으로 KPI."
    runner = FakeJellyRunner(result)

    actual = EventJellyRedteamAdapter(runner=runner, enabled=True).run(event, pack)

    assert adapter_module._edit_jelly_sentence(
        "궁극적으로 KPI.", baseline.risks[0].failure_path
    ) == baseline.risks[0].failure_path
    assert len(runner.calls) == 1
    assert actual == baseline


def test_event_jelly_is_safe_analysis_sidecar_and_cannot_persist_prose():
    event, _, pack = _event_inputs()
    baseline = EventRedteamAgent().run_deterministic(event, pack)
    cause = "출시 후 이용자가 이미 이탈했다는 외부 설명입니다."
    fix = "출시 후 지표가 하락해 즉시 롤백했다는 외부 제안입니다."
    runner = FakeJellyRunner(
        _jelly_result(len(baseline.risks), cause=cause, fix=fix)
    )
    events = []

    result = EventJellyRedteamAdapter(runner=runner, enabled=True).run(
        event,
        pack,
        on_event=lambda node, message, metrics: events.append((node, metrics)),
    )

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
    assert result == baseline
    assert cause not in result.model_dump_json()
    assert fix not in result.model_dump_json()
    assert [metrics for node, metrics in events if node == "jelly_output_checked"] == [
        {"positive": 0, "neutral": 0, "negative": 0, "risk": len(baseline.risks)}
    ]


def test_update_jelly_cannot_change_code_owned_risk_or_metrics():
    brief, _, pack = _update_inputs()
    baseline = UpdateRedteamAgent().run_deterministic(brief, pack)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks)))

    result = UpdateJellyRedteamAdapter(runner=runner, enabled=True).run(brief, pack)

    assert result == baseline


def test_teammate_adapters_are_disabled_by_default_and_preserve_artifacts():
    event, feedback, pack = _event_inputs("disabled-event")
    event_runner = FakeJellyRunner(_jelly_result(5))
    event_probe = FakeJinbaeProbe()
    event_risks = EventJellyRedteamAdapter(runner=event_runner).run(event, pack)
    event_decision = EventJinbaeAuditAdapter(probe=event_probe).run(
        feedback, pack, event_risks
    )
    assert event_risks == EventRedteamAgent().run_deterministic(event, pack)
    assert event_decision == AuditStrategyAgent().run_deterministic(
        feedback, pack, event_risks
    )

    brief, update_feedback, update_pack = _update_inputs("disabled-update")
    update_runner = FakeJellyRunner(_jelly_result(1))
    update_probe = FakeJinbaeProbe()
    update_impact = UpdateJellyRedteamAdapter(runner=update_runner).run(
        brief, update_pack
    )
    update_decision = UpdateJinbaeAuditAdapter(probe=update_probe).run(
        update_feedback, update_pack, update_impact
    )
    assert update_impact == UpdateRedteamAgent().run_deterministic(brief, update_pack)
    assert update_decision == UpdateAuditAgent().run_deterministic(
        update_feedback, update_pack, update_impact
    )
    assert event_runner.calls == event_probe.calls == []
    assert update_runner.calls == update_probe.calls == []
    shared_budget = ClaudeBudget()
    disabled_redteam = EventJellyRedteamAdapter(budget=shared_budget)
    disabled_audit = EventJinbaeAuditAdapter(budget=shared_budget)
    disabled_risks = disabled_redteam.run(event, pack)
    disabled_audit.run(feedback, pack, disabled_risks)
    assert disabled_redteam.runner.budget is disabled_audit.probe.budget is shared_budget
    assert shared_budget.requests == 0


def test_event_orchestrator_calls_each_teammate_once_and_preserves_policy_output():
    event = load_demo_event("event-team-e2e")
    baseline = EventPreflightOrchestrator().run(event)
    runner = FakeJellyRunner(_jelly_result(len(baseline.risks.risks)))
    probe = FakeJinbaeProbe(
        {
            "verdict": "not_grounded",
            "citations": [],
            "rationale": "외부 판정으로 출시를 보류하라는 의견입니다.",
            "decision": "Hold",
        }
    )

    result = EventPreflightOrchestrator(
        use_llm=True,
        evidence_rag=EvidenceRagAgent(),
        redteam=EventJellyRedteamAdapter(runner=runner, enabled=True),
        audit=EventJinbaeAuditAdapter(probe=probe, enabled=True),
    ).run(event)

    assert len(runner.calls) == 1
    assert len(probe.calls) == 1
    assert result.llm_requested is True
    assert result.brief.decision == baseline.brief.decision
    assert result.brief.decision.value == "Revise"
    assert result.risks == baseline.risks
    assert result.validated == baseline.validated
    assert _risk_core(result.risks.risks) == _risk_core(baseline.risks.risks)
    assert _risk_core(result.validated.validated_risks) == _risk_core(
        baseline.validated.validated_risks
    )
    assert _risk_core(result.brief.top_risks) == _risk_core(baseline.brief.top_risks)


def test_update_orchestrator_calls_each_teammate_once_and_preserves_policy_output():
    brief = load_dragunov_brief("update-team-e2e")
    baseline = UpdateReviewOrchestrator().run(brief)
    runner = FakeJellyRunner(_jelly_result(len(baseline.impact.risks)))
    probe = FakeJinbaeProbe(
        {
            "verdict": "grounded",
            "citations": ["invented"],
            "rationale": "외부 판정으로 즉시 출시하라는 의견입니다.",
            "decision": "Go",
        }
    )

    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(),
        evidence=UpdateEvidenceAgent(),
        redteam=UpdateJellyRedteamAdapter(runner=runner, enabled=True),
        audit=UpdateJinbaeAuditAdapter(probe=probe, enabled=True),
        use_llm=True,
    ).run(brief)

    assert len(runner.calls) == 1
    assert len(probe.calls) == 1
    assert result.llm_requested is True
    assert result.brief.decision == baseline.brief.decision
    assert result.brief.decision.value == "Test"
    assert result.impact == baseline.impact
    assert result.validated == baseline.validated
    assert _risk_core(result.impact.risks) == _risk_core(baseline.impact.risks)
    assert _risk_core(result.validated.validated_risks) == _risk_core(
        baseline.validated.validated_risks
    )
    assert _risk_core(result.brief.top_risks) == _risk_core(baseline.brief.top_risks)


def test_paid_jelly_schema_failure_retries_then_falls_back():
    event = load_demo_event("jelly-paid-failure")
    baseline = EventPreflightOrchestrator().run(event)
    runner = FakeJellyRunner(
        _jelly_result(len(baseline.risks.risks), trend="허용되지 않은 동향")
    )

    result = EventPreflightOrchestrator(
        use_llm=True,
        evidence_rag=EvidenceRagAgent(),
        redteam=EventJellyRedteamAdapter(runner=runner, enabled=True)
    ).run(event)

    assert len(runner.calls) == 2
    assert result.fallback_used is True
    assert result.risks == baseline.risks


def test_paid_update_jelly_schema_failure_retries_then_falls_back():
    brief = load_dragunov_brief("update-jelly-paid-failure")
    baseline = UpdateReviewOrchestrator().run(brief)
    runner = FakeJellyRunner(
        _jelly_result(len(baseline.impact.risks), trend="허용되지 않은 동향")
    )

    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(),
        evidence=UpdateEvidenceAgent(),
        redteam=UpdateJellyRedteamAdapter(runner=runner, enabled=True),
        use_llm=True,
    ).run(brief)

    assert len(runner.calls) == 2
    assert result.fallback_used is True
    assert result.impact == baseline.impact


def test_jelly_runner_uses_one_bounded_node_process_with_stdin_json(monkeypatch):
    rows = [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
    calls = []
    monkeypatch.delenv("CLAUDE_REDTEAM_MODEL", raising=False)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(_jelly_result(1)), "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    budget = ClaudeBudget(max_tokens=512, max_usd=100)
    assert JellyRunner(timeout_seconds=7, budget=budget).run(rows) == _jelly_result(1)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:2] == ["node", "-e"]
    assert "safe-1" not in " ".join(command)
    assert json.loads(kwargs["input"]) == rows
    assert kwargs["timeout"] == 7
    assert kwargs["cwd"] == Path(__file__).resolve().parents[1]
    assert kwargs["env"]["CLAUDE_REDTEAM_MODEL"] == "claude-haiku-4-5-20251001"
    assert kwargs["env"]["CLAUDE_MAX_OUTPUT_TOKENS"] == "512"


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


@pytest.mark.parametrize(
    "stdout",
    ["not json", json.dumps([_jelly_result(1)])],
    ids=["invalid-json", "non-dict-json"],
)
def test_jelly_runner_rejects_invalid_stdout_as_schema_invalid(monkeypatch, stdout):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout, "provider-secret")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(StructuredModelError) as error:
        JellyRunner().run(
            [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
        )

    assert error.value.code is ErrorCode.SCHEMA_INVALID
    assert "provider-secret" not in str(error.value)


def test_jelly_runner_treats_nonzero_subprocess_as_source_unavailable(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "provider-secret", "provider-secret")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(StructuredModelError) as error:
        JellyRunner().run(
            [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
        )

    assert error.value.code is ErrorCode.SOURCE_UNAVAILABLE
    assert "provider-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("configured_model", "configured_tokens", "expected_model", "expected_tokens"),
    [
        (None, None, "claude-haiku-4-5-20251001", 3000),
        ("claude-config-test", "9000", "claude-config-test", 3000),
        ("claude-config-test", "512", "claude-config-test", 512),
    ],
)
def test_jelly_node_uses_environment_key_and_bounded_config_without_network(
    configured_model, configured_tokens, expected_model, expected_tokens
):
    script = r'''
const assert = require("assert");
global.fetch = async (_url, options) => {
  const body = JSON.parse(options.body);
  assert.equal(options.headers["x-api-key"], "env-only-test-key");
  assert.equal(body.model, process.env.EXPECTED_MODEL);
  assert.equal(body.max_tokens, Number(process.env.EXPECTED_TOKENS));
  return {
    ok: true,
    json: async () => ({
      stop_reason: "end_turn",
      content: [{
        type: "text",
        text: JSON.stringify({
          rows: [{index: 0, trend: "중립", cause: "안전한 원인입니다.", fix: "안전한 개선안입니다."}],
          synthesis: [],
        }),
      }],
    }),
  };
};
const { analyzeRows } = require("./jelly/call-agent.js");
analyzeRows([{index: 0, evidenceId: "safe-1", content: "안전한 요약입니다."}])
  .then(() => process.stdout.write("ok"))
  .catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "env-only-test-key"
    env["EXPECTED_MODEL"] = expected_model
    env["EXPECTED_TOKENS"] = str(expected_tokens)
    if configured_model is None:
        env.pop("CLAUDE_REDTEAM_MODEL", None)
    else:
        env["CLAUDE_REDTEAM_MODEL"] = configured_model
    if configured_tokens is None:
        env.pop("CLAUDE_MAX_OUTPUT_TOKENS", None)
    else:
        env["CLAUDE_MAX_OUTPUT_TOKENS"] = configured_tokens

    completed = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "ok"


def test_jelly_node_provider_errors_do_not_leak_to_cli_or_analyze(tmp_path):
    secret = "provider-secret"
    preload = tmp_path / "mock-fetch.js"
    preload.write_text(
        "global.fetch = async () => ({ ok: false, status: 500, "
        "json: async () => ({ error: { message: 'provider-secret' } }) });\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "test-key"

    cli = subprocess.run(
        ["node", "-r", str(preload), "jelly/call-agent.js", "안전한 입력입니다."],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert cli.returncode == 1
    assert secret not in cli.stdout + cli.stderr
    assert "status 500" in cli.stderr

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server_env = {**env, "CALL_AGENT_PORT": str(port)}
    server = subprocess.Popen(
        ["node", "-r", str(preload), "jelly/call-agent.js", "serve"],
        cwd=Path(__file__).resolve().parents[1],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/analyze",
        data=json.dumps(
            {"rows": [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(request, timeout=1)
            except urllib.error.HTTPError as error:
                response = error
                break
            except urllib.error.URLError:
                time.sleep(0.05)
    finally:
        server.terminate()
        stdout, stderr = server.communicate(timeout=10)

    assert response is not None
    body = response.read().decode()
    assert response.code == 500
    assert secret not in body + stdout + stderr
    assert "status 500" in body


def test_jelly_node_invalid_json_does_not_leak_provider_text(tmp_path):
    secret = "provider-secret"
    preload = tmp_path / "mock-fetch.js"
    preload.write_text(
        "global.fetch = async () => ({ ok: true, status: 200, json: async () => ({ "
        "stop_reason: 'end_turn', content: [{ type: 'text', text: 'provider-secret' }] }) });\n",
        encoding="utf-8",
    )
    script = r'''
const { analyzeRows } = require("./jelly/call-agent.js");
analyzeRows([{index: 0, evidenceId: "safe-1", content: "안전한 요약입니다."}])
  .then(() => process.exitCode = 2)
  .catch((error) => { console.error(error.message); process.exitCode = 1; });
'''
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "test-key"
    completed = subprocess.run(
        ["node", "-r", str(preload), "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 1
    assert secret not in completed.stdout + completed.stderr
    assert "Jelly 응답 형식을 확인하지 못했습니다." in completed.stderr


class FakeAsyncMessages:
    def __init__(self, judge_result):
        self.judge_result = judge_result
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="tool_use", name="judge_claim", input=self.judge_result)
        return SimpleNamespace(content=[block])


def test_jelly_and_jinbae_share_exact_two_call_budget(monkeypatch):
    budget = ClaudeBudget(max_requests=2, max_input_chars=100_000, max_usd=100)
    reserve_calls = []
    real_reserve = budget.reserve

    def recording_reserve(payload_chars, **kwargs):
        reserve_calls.append((payload_chars, kwargs))
        return real_reserve(payload_chars, **kwargs)

    budget.reserve = recording_reserve
    process_calls = []
    monkeypatch.setenv("CLAUDE_REDTEAM_MODEL", "jelly-budget-model")
    monkeypatch.setenv("CLAUDE_AUDIT_MODEL", "jinbae-budget-model")

    def fake_run(command, **kwargs):
        process_calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(_jelly_result(1)), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rows = [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
    JellyRunner(timeout_seconds=7, budget=budget).run(rows)
    messages = FakeAsyncMessages(
        {
            "verdict": "grounded",
            "citations": ["safe-1"],
            "rationale": "제공된 근거로 뒷받침된다는 판단입니다.",
        }
    )
    claim = "코드 소유 위험 분류를 근거 요약으로 확인합니다."
    chunks = [{"id": "safe-1", "text": "안전한 근거 요약입니다."}]
    JinbaeProbe(client=SimpleNamespace(messages=messages), budget=budget).run(claim, chunks)

    assert budget.requests == 2
    assert len(process_calls) == len(messages.calls) == 1
    jelly_payload_chars = len(adapter_module._jelly_user_text(rows)) + len(
        json.dumps(
            adapter_module._JELLY_OUTPUT_CONFIG,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    assert reserve_calls[0] == (
        jelly_payload_chars,
        {
            "system_chars": len(
                adapter_module._JELLY_ROLE_PATH.read_text(encoding="utf-8")
            ),
            "model": "jelly-budget-model",
        },
    )
    assert reserve_calls[1] == (
        len(adapter_module._jinbae_prompt(claim, chunks))
        + len(json.dumps(adapter_module.JUDGE_TOOL, ensure_ascii=False)),
        {"model": "jinbae-budget-model"},
    )
    with pytest.raises(StructuredModelError) as error:
        JellyRunner(timeout_seconds=7, budget=budget).run(rows)
    assert error.value.code is ErrorCode.BUDGET_EXCEEDED
    assert budget.requests == 2
    assert len(process_calls) == 1


def test_jelly_budget_enforces_actual_input_cap_before_process(monkeypatch):
    process_calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: process_calls.append(args))
    rows = [{"index": 0, "evidenceId": "safe-1", "content": "안전한 요약입니다."}]
    user_and_system_chars = len(adapter_module._jelly_user_text(rows)) + len(
        adapter_module._JELLY_ROLE_PATH.read_text(encoding="utf-8")
    )
    budget = ClaudeBudget(
        max_input_chars=user_and_system_chars + 1,
        max_usd=100,
    )

    with pytest.raises(StructuredModelError) as error:
        JellyRunner(budget=budget).run(rows)

    assert error.value.code is ErrorCode.BUDGET_EXCEEDED
    assert budget.requests == 0
    assert process_calls == []


def test_jinbae_budget_rejects_output_cap_below_real_judge_request():
    messages = FakeAsyncMessages(
        {"verdict": "grounded", "citations": ["safe-1"], "rationale": "근거가 있습니다."}
    )
    budget = ClaudeBudget(max_tokens=511, max_usd=100)

    with pytest.raises(StructuredModelError) as error:
        JinbaeProbe(client=SimpleNamespace(messages=messages), budget=budget).run(
            "코드 소유 위험 분류를 확인합니다.",
            [{"id": "safe-1", "text": "안전한 근거 요약입니다."}],
        )

    assert error.value.code is ErrorCode.BUDGET_EXCEEDED
    assert budget.requests == 0
    assert messages.calls == []


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


def test_jinbae_owned_client_uses_timeout_and_closes_but_injected_client_stays_open(
    monkeypatch,
):
    judge_result = {
        "verdict": "grounded",
        "citations": ["safe-1"],
        "rationale": "제공된 근거로 뒷받침된다는 판단입니다.",
    }
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.messages = FakeAsyncMessages(judge_result)
            self.closed = 0
            created.append(self)

        async def close(self):
            self.closed += 1

    real_wait_for = asyncio.wait_for
    timeouts = []

    async def recording_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setattr(adapter_module.asyncio, "wait_for", recording_wait_for)
    claim = "코드 소유 위험 분류를 근거 요약으로 확인합니다."
    chunks = [{"id": "safe-1", "text": "안전한 근거 요약입니다."}]

    JinbaeProbe().run(claim, chunks)
    assert created[0].kwargs == {"max_retries": 0, "timeout": 30}
    assert created[0].closed == 1

    injected = FakeClient()
    JinbaeProbe(client=injected).run(claim, chunks)
    assert injected.closed == 0
    assert timeouts == [35, 35]


@pytest.mark.parametrize("owns_client", [True, False], ids=["owned", "injected"])
def test_jinbae_timeout_is_sanitized_and_closes_only_owned_client(
    monkeypatch, owns_client
):
    created = []

    class TimeoutClient:
        def __init__(self, **_kwargs):
            self.messages = FakeAsyncMessages({})
            self.closed = 0
            created.append(self)

        async def close(self):
            self.closed += 1

    async def immediate_timeout(awaitable, timeout):
        assert timeout == 35
        awaitable.close()
        raise TimeoutError("raw-timeout-detail")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", TimeoutClient)
    monkeypatch.setattr(adapter_module.asyncio, "wait_for", immediate_timeout)
    injected = None if owns_client else TimeoutClient()

    with pytest.raises(StructuredModelError) as error:
        JinbaeProbe(client=injected).run(
            "코드 소유 위험 분류를 확인합니다.",
            [{"id": "safe-1", "text": "안전한 근거 요약입니다."}],
        )

    client = created[-1]
    assert error.value.code is ErrorCode.SOURCE_UNAVAILABLE
    assert "raw-timeout-detail" not in str(error.value)
    assert client.closed == (1 if owns_client else 0)


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

    result = EventJinbaeAuditAdapter(probe=probe, enabled=True).run(
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
    checked = next(metrics for node, metrics in events if node == "jinbae_probe_checked")
    assert checked["verdict"] == "not_grounded"


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

    result = UpdateJinbaeAuditAdapter(probe=probe, enabled=True).run(
        feedback, pack, impact
    )

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
        EventJinbaeAuditAdapter(probe=probe, enabled=True).run(
            feedback, pack, assessment
        )

    assert len(probe.calls) == 1
    assert secret not in str(error.value)


def test_event_no_risk_path_skips_jelly_and_jinbae_calls():
    event, feedback, pack = _event_inputs("no-risk")
    no_issue_pack = pack.model_copy(update={"issues": []})
    runner = FakeJellyRunner(_jelly_result(0))

    assessment = EventJellyRedteamAdapter(runner=runner, enabled=True).run(
        event, no_issue_pack
    )
    probe = FakeJinbaeProbe()
    decision = EventJinbaeAuditAdapter(probe=probe, enabled=True).run(
        feedback, no_issue_pack, assessment
    )

    assert assessment.risks == []
    assert decision.validated_risks == []
    assert runner.calls == []
    assert probe.calls == []


def test_update_no_risk_path_skips_jelly_and_jinbae_calls():
    brief, feedback, pack = _update_inputs("update-no-risk")
    persona_impacts = []
    for impact in pack.persona_impacts:
        updates = {"negative_signal_ids": [], "split_signal_ids": []}
        if not impact.positive_signal_ids:
            updates.update({"evidence_ids": [], "confidence": 0})
        persona_impacts.append(impact.model_copy(update=updates))
    no_risk_pack = type(pack).model_validate(
        pack.model_copy(
            update={
                "negative_signals": [],
                "split_conditions": [],
                "persona_impacts": persona_impacts,
            }
        ).model_dump(mode="python")
    )
    runner = FakeJellyRunner(_jelly_result(0))

    impact = UpdateJellyRedteamAdapter(runner=runner, enabled=True).run(
        brief, no_risk_pack
    )
    probe = FakeJinbaeProbe()
    decision = UpdateJinbaeAuditAdapter(probe=probe, enabled=True).run(
        feedback, no_risk_pack, impact
    )

    assert impact.risks == []
    assert decision.validated_risks == []
    assert runner.calls == []
    assert probe.calls == []
