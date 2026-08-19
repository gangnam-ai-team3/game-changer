from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.structured import StructuredModelError, require_native_business_korean
from contracts import ErrorCode
from seungjinbae.app.judge import judge_claim
from update_review.audit import UpdateAuditAgent
from update_review.redteam import UpdateRedteamAgent


_ROOT = Path(__file__).resolve().parents[1]
_JELLY_TRENDS = {"긍정", "중립", "부정", "위험"}
_NODE_BRIDGE = r"""
const { analyzeRows } = require("./jelly/call-agent.js");
let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => body += chunk);
process.stdin.on("end", async () => {
  try {
    const result = await analyzeRows(JSON.parse(body));
    process.stdout.write(JSON.stringify(result));
  } catch (_) {
    process.exitCode = 1;
  }
});
""".strip()


def _jelly_schema_error() -> StructuredModelError:
    return StructuredModelError(
        ErrorCode.SCHEMA_INVALID,
        "Jelly 결과 계약을 검증하지 못했습니다.",
    )


def _team_unavailable(name: str) -> StructuredModelError:
    return StructuredModelError(
        ErrorCode.SOURCE_UNAVAILABLE,
        f"{name} 팀 에이전트를 안전하게 실행하지 못했습니다.",
    )


class JellyRunner:
    """Run Jelly's exported analyzer once without exposing a sidecar or raw errors."""

    def __init__(self, timeout_seconds: float = 45) -> None:
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise _jelly_schema_error()
        self.timeout_seconds = timeout_seconds

    def run(self, rows: list[dict]) -> dict:
        if (
            type(rows) is not list
            or not 1 <= len(rows) <= 8
            or any(
                type(row) is not dict
                or set(row) != {"index", "evidenceId", "content"}
                or type(row["index"]) is not int
                or not isinstance(row["evidenceId"], str)
                or not row["evidenceId"]
                or not isinstance(row["content"], str)
                or not row["content"].strip()
                for row in rows
            )
            or [row["index"] for row in rows] != list(range(len(rows)))
        ):
            raise _jelly_schema_error()
        try:
            completed = subprocess.run(
                ["node", "-e", _NODE_BRIDGE],
                input=json.dumps(rows, ensure_ascii=False),
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception:
            completed = None
        if completed is None or completed.returncode != 0:
            raise _team_unavailable("Jelly")
        try:
            result = json.loads(completed.stdout)
        except Exception:
            result = None
        if type(result) is not dict:
            raise _jelly_schema_error()
        return result


def _safe_jelly_rows(risks, evidence) -> list[dict]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    rows = []
    for index, risk in enumerate(risks[:8]):
        if any(item_id not in evidence_by_id for item_id in risk.evidence_ids):
            raise _jelly_schema_error()
        linked = [evidence_by_id[item_id] for item_id in risk.evidence_ids]
        if not linked:
            raise _jelly_schema_error()
        rows.append(
            {
                "index": index,
                "evidenceId": ",".join(item.evidence_id for item in linked),
                "content": "\n".join(item.summary for item in linked),
            }
        )
    return rows


def _validated_jelly_narratives(result: dict, count: int) -> dict[int, tuple[str, str]]:
    if (
        type(result) is not dict
        or set(result) != {"rows", "synthesis"}
        or type(result["rows"]) is not list
        or type(result["synthesis"]) is not list
        or len(result["rows"]) != count
    ):
        raise _jelly_schema_error()
    parsed = {}
    prose = []
    for row in result["rows"]:
        if (
            type(row) is not dict
            or set(row) != {"index", "trend", "cause", "fix"}
            or type(row["index"]) is not int
            or not isinstance(row["trend"], str)
            or row["trend"] not in _JELLY_TRENDS
            or not isinstance(row["cause"], str)
            or not row["cause"].strip()
            or not isinstance(row["fix"], str)
            or not row["fix"].strip()
        ):
            raise _jelly_schema_error()
        if row["index"] in parsed:
            raise _jelly_schema_error()
        cause, fix = row["cause"].strip(), row["fix"].strip()
        parsed[row["index"]] = (cause, fix)
        prose.extend((cause, fix))
    if set(parsed) != set(range(count)):
        raise _jelly_schema_error()
    try:
        require_native_business_korean(prose)
    except StructuredModelError:
        raise _jelly_schema_error() from None
    return parsed


def _run_jelly(base, evidence, runner, on_event):
    if not base.risks:
        return base
    notify = on_event or (lambda _node, _message, _metrics: None)
    rows = _safe_jelly_rows(base.risks, evidence)
    notify(
        "jelly_rows_sent",
        "정아현 분석기에 안전한 근거 요약을 전달합니다.",
        {"rows": len(rows)},
    )
    try:
        result = runner.run(rows)
    except StructuredModelError:
        raise
    except Exception:
        result = None
    if result is None:
        raise _team_unavailable("Jelly")
    narratives = _validated_jelly_narratives(result, len(rows))
    risks = list(base.risks)
    for index, (failure_path, revision_question) in narratives.items():
        risks[index] = risks[index].model_copy(
            update={
                "failure_path": failure_path,
                "revision_question": revision_question,
            }
        )
    notify(
        "jelly_output_checked",
        "정아현 분석기의 행 연결과 한국어 문장을 확인했습니다.",
        {"rows": len(narratives), "overlaid_fields": len(narratives) * 2},
    )
    return base.model_copy(update={"risks": risks})


class EventJellyRedteamAdapter:
    def __init__(self, *, base=None, runner=None) -> None:
        self.base = base if base is not None else EventRedteamAgent()
        self.runner = runner if runner is not None else JellyRunner()

    def run(self, event, pack, on_event=None):
        base = self.run_deterministic(event, pack, on_event=on_event)
        return _run_jelly(base, pack.evidence, self.runner, on_event)

    def run_deterministic(self, event, pack, on_event=None):
        return self.base.run_deterministic(event, pack, on_event=on_event)


class UpdateJellyRedteamAdapter:
    def __init__(self, *, base=None, runner=None) -> None:
        self.base = base if base is not None else UpdateRedteamAgent()
        self.runner = runner if runner is not None else JellyRunner()

    def run(self, brief, pack, on_event=None):
        base = self.run_deterministic(brief, pack, on_event=on_event)
        return _run_jelly(base, pack.evidence, self.runner, on_event)

    def run_deterministic(self, brief, pack, on_event=None):
        return self.base.run_deterministic(brief, pack, on_event=on_event)


def _jinbae_schema_error() -> StructuredModelError:
    return StructuredModelError(
        ErrorCode.SCHEMA_INVALID,
        "승진배 근거 판정기의 인용 계약을 검증하지 못했습니다.",
    )


class JinbaeProbe:
    """Make one call through Seungjinbae's judge and enforce local citation IDs."""

    def __init__(self, *, client=None) -> None:
        self.client = client

    async def arun(self, claim_text: str, candidate_chunks: list[dict]) -> dict:
        if (
            not isinstance(claim_text, str)
            or not claim_text.strip()
            or type(candidate_chunks) is not list
            or not 1 <= len(candidate_chunks) <= 12
            or any(
                type(chunk) is not dict
                or set(chunk) != {"id", "text"}
                or not isinstance(chunk["id"], str)
                or not chunk["id"]
                or not isinstance(chunk["text"], str)
                or not chunk["text"].strip()
                for chunk in candidate_chunks
            )
        ):
            raise _jinbae_schema_error()
        supplied_ids = [chunk["id"] for chunk in candidate_chunks]
        if len(supplied_ids) != len(set(supplied_ids)):
            raise _jinbae_schema_error()
        client = self.client
        if client is None:
            try:
                from anthropic import AsyncAnthropic

                client = AsyncAnthropic(max_retries=0)
            except Exception:
                client = None
            if client is None:
                raise _team_unavailable("승진배")
        try:
            result = await judge_claim(
                client,
                model=os.getenv("CLAUDE_AUDIT_MODEL", "claude-haiku-4-5"),
                claim_text=claim_text,
                candidate_chunks=candidate_chunks,
                max_retries=0,
            )
        except Exception:
            result = None
        if result is None:
            raise _team_unavailable("승진배")
        if (
            type(result) is not dict
            or set(result) != {"verdict", "citations", "rationale"}
            or not isinstance(result["verdict"], str)
            or result["verdict"] not in {
                "grounded",
                "not_grounded",
                "partially_grounded",
            }
            or type(result["citations"]) is not list
            or any(not isinstance(item, str) for item in result["citations"])
            or len(result["citations"]) != len(set(result["citations"]))
            or not set(result["citations"]) <= set(supplied_ids)
            or not isinstance(result["rationale"], str)
        ):
            raise _jinbae_schema_error()
        return result

    def run(self, claim_text: str, candidate_chunks: list[dict]) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(claim_text, candidate_chunks))
        raise _team_unavailable("승진배")


def _safe_audit_payload(risks, evidence) -> tuple[str, list[dict]]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    chunks = []
    seen = set()
    depth = max(len(risk.evidence_ids) for risk in risks)
    # ponytail: round-robin selection caps one paid audit at 12 summaries; raise the
    # cap only if a measured grounding gap justifies a larger teammate request.
    for offset in range(depth):
        for risk in risks:
            if offset >= len(risk.evidence_ids):
                continue
            item_id = risk.evidence_ids[offset]
            if item_id in seen:
                continue
            item = evidence_by_id.get(item_id)
            if item is None:
                raise _jinbae_schema_error()
            seen.add(item_id)
            chunks.append({"id": item.evidence_id, "text": item.summary})
            if len(chunks) == 12:
                break
        if len(chunks) == 12:
            break
    if not chunks:
        raise _jinbae_schema_error()
    claim = (
        "코드 정책이 고정한 위험 ID, 범주, 등급이 제공된 근거 요약으로 뒷받침되는지 "
        "하나의 묶음으로 판정하십시오: "
        + "; ".join(
            f"{risk.risk_id}({risk.category.value}, {risk.severity.value})"
            for risk in risks
        )
    )
    return claim, chunks


def _run_jinbae_probe(base, evidence, probe, on_event):
    if not base.validated_risks:
        return base
    claim, chunks = _safe_audit_payload(base.validated_risks, evidence)
    notify = on_event or (lambda _node, _message, _metrics: None)
    notify(
        "jinbae_probe_started",
        "승진배 근거 판정기를 한 번 실행합니다.",
        {"claims": 1, "risks": len(base.validated_risks), "chunks": len(chunks)},
    )
    try:
        probe.run(claim, chunks)
    except Exception:
        failed = True
    else:
        failed = False
    if failed:
        raise _team_unavailable("승진배")
    notify(
        "jinbae_probe_checked",
        "승진배 근거 판정기의 인용 ID를 확인하고 코드 판정을 유지했습니다.",
        {"calls": 1, "decision": base.decision.value},
    )
    return base


class EventJinbaeAuditAdapter:
    def __init__(self, *, base=None, probe=None) -> None:
        self.base = base if base is not None else AuditStrategyAgent()
        self.probe = probe if probe is not None else JinbaeProbe()

    def run(
        self,
        bundle,
        pack,
        assessment,
        *,
        analysis_incomplete: bool = False,
        on_event=None,
    ):
        base = self.run_deterministic(
            bundle,
            pack,
            assessment,
            analysis_incomplete=analysis_incomplete,
            on_event=on_event,
        )
        return _run_jinbae_probe(base, pack.evidence, self.probe, on_event)

    def run_deterministic(
        self,
        bundle,
        pack,
        assessment,
        *,
        analysis_incomplete: bool = False,
        on_event=None,
    ):
        return self.base.run_deterministic(
            bundle,
            pack,
            assessment,
            analysis_incomplete=analysis_incomplete,
            on_event=on_event,
        )

    def to_brief(self, event, pack, decision):
        return self.base.to_brief(event, pack, decision)


class UpdateJinbaeAuditAdapter:
    def __init__(self, *, base=None, probe=None) -> None:
        self.base = base if base is not None else UpdateAuditAgent()
        self.probe = probe if probe is not None else JinbaeProbe()

    def run(
        self,
        bundle,
        pack,
        assessment,
        *,
        analysis_incomplete: bool = False,
        on_event=None,
    ):
        base = self.run_deterministic(
            bundle,
            pack,
            assessment,
            analysis_incomplete=analysis_incomplete,
            on_event=on_event,
        )
        return _run_jinbae_probe(base, pack.evidence, self.probe, on_event)

    def run_deterministic(
        self,
        bundle,
        pack,
        assessment,
        *,
        analysis_incomplete: bool = False,
        on_event=None,
    ):
        return self.base.run_deterministic(
            bundle,
            pack,
            assessment,
            analysis_incomplete=analysis_incomplete,
            on_event=on_event,
        )

    def to_brief(self, brief, pack, impact, decision):
        return self.base.to_brief(brief, pack, impact, decision)
