from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    require_native_business_korean,
)
from contracts import ErrorCode
from seungjinbae.app.judge import JUDGE_TOOL, judge_claim
from update_review.audit import UpdateAuditAgent
from update_review.redteam import UpdateRedteamAgent


_ROOT = Path(__file__).resolve().parents[1]
_JELLY_ROLE_PATH = _ROOT / ".claude" / "agents" / "jelly.md"
_JELLY_TRENDS = {"긍정", "중립", "부정", "위험"}
_JELLY_TREND_METRICS = {
    "긍정": "positive",
    "중립": "neutral",
    "부정": "negative",
    "위험": "risk",
}
_JELLY_USER_PREFIX = (
    "아래는 화면의 [정보 입력] 표에서 넘어온 근거 행 목록입니다(JSON 배열). 각 행은 index로 구분됩니다.\n"
    "각 행마다 근거 내용(content)을 보고 동향(긍정/중립/부정/위험 중 하나), 원인(한 문장), "
    "개선 방향(한 문장)을 정하세요. "
    "원인과 개선 방향은 비어 있지 않은 완전한 한국어 문장으로 쓰고 반드시 마침표(.)로 끝내세요. "
    "가운뎃점 기호 대신 쉼표나 자연스러운 연결어를 사용하세요.\n"
    "그리고 전체 행을 종합한 개선 방향(synthesis)을 하나의 긴 문단이 아니라, "
    "가장 근거가 많고 시급한 것부터 순서대로 2~4개의 항목으로 나눠 작성하세요. "
    "각 항목은 title(5~15자 정도의 짧은 테마명, 마침표 없이)과 description(1~2문장, 마침표로 끝냄)으로 구성합니다.\n\n"
)
_JELLY_OUTPUT_CONFIG = {
    "format": {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "trend": {
                                "type": "string",
                                "enum": ["긍정", "중립", "부정", "위험"],
                            },
                            "cause": {"type": "string"},
                            "fix": {"type": "string"},
                        },
                        "required": ["index", "trend", "cause", "fix"],
                        "additionalProperties": False,
                    },
                },
                "synthesis": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["title", "description"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["rows", "synthesis"],
            "additionalProperties": False,
        },
    }
}
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


def _model_from_env(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _jelly_user_text(rows: list[dict]) -> str:
    return _JELLY_USER_PREFIX + json.dumps(rows, ensure_ascii=False, indent=2)


def _jinbae_prompt(claim_text: str, candidate_chunks: list[dict]) -> str:
    chunks_block = "\n\n".join(
        f"[{chunk['id']}] {chunk['text']}" for chunk in candidate_chunks
    )
    return (
        "Given the claim and candidate source chunks below, judge whether the claim is "
        "grounded in the chunks. Cite the chunk ids that support your verdict.\n\n"
        f"Claim: {claim_text}\n\nCandidate chunks:\n{chunks_block}"
    )


class JellyRunner:
    """Run Jelly's exported analyzer once without exposing a sidecar or raw errors."""

    def __init__(
        self,
        timeout_seconds: float = 45,
        *,
        budget: ClaudeBudget | None = None,
    ) -> None:
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise _jelly_schema_error()
        self.timeout_seconds = timeout_seconds
        self.budget = budget if budget is not None else ClaudeBudget()

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
        serialized = json.dumps(rows, ensure_ascii=False)
        try:
            system_chars = len(_JELLY_ROLE_PATH.read_text(encoding="utf-8"))
        except OSError:
            raise _team_unavailable("Jelly") from None
        if self.budget.max_tokens < 1:
            raise StructuredModelError(
                ErrorCode.BUDGET_EXCEEDED,
                "Jelly 출력 토큰 예산이 부족합니다.",
            )
        model = _model_from_env(
            "CLAUDE_REDTEAM_MODEL", "claude-haiku-4-5-20251001"
        )
        self.budget.reserve(
            len(_jelly_user_text(rows))
            + len(
                json.dumps(
                    _JELLY_OUTPUT_CONFIG,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
            system_chars=system_chars,
            model=model,
        )
        try:
            completed = subprocess.run(
                ["node", "-e", _NODE_BRIDGE],
                input=serialized,
                cwd=_ROOT,
                env={
                    **os.environ,
                    "CLAUDE_REDTEAM_MODEL": model,
                    "CLAUDE_MAX_OUTPUT_TOKENS": str(
                        max(1, min(self.budget.max_tokens, 3000))
                    ),
                },
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


def _edit_jelly_sentence(value: str, fallback: str) -> str:
    """Normalize one disposable Jelly sentence before Korean-style validation."""

    text = value if value.strip() and re.search(r"[가-힣]", value) else fallback
    text = text.replace("·", ", ")
    for phrase in ("본질적으로", "궁극적으로", "실질적으로"):
        text = text.replace(phrase, "")
    text = text.replace("이유는 명확", "근거를 보면").replace(
        "혁신적인 변화", "주요 변화"
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"^[,\s]+|[,\s]+$", "", text)
    return text if re.search(r"[.!?]$", text) else f"{text}."


def _validated_jelly_trends(result: dict, risks) -> dict[str, int]:
    count = len(risks)
    if (
        type(result) is not dict
        or set(result) != {"rows", "synthesis"}
        or type(result["rows"]) is not list
        or type(result["synthesis"]) is not list
        or len(result["rows"]) != count
    ):
        raise _jelly_schema_error()
    indexes = set()
    trend_counts = {metric: 0 for metric in _JELLY_TREND_METRICS.values()}
    prose = []
    for row in result["rows"]:
        if (
            type(row) is not dict
            or set(row) != {"index", "trend", "cause", "fix"}
            or type(row["index"]) is not int
            or not isinstance(row["trend"], str)
            or row["trend"] not in _JELLY_TRENDS
            or not isinstance(row["cause"], str)
            or not isinstance(row["fix"], str)
        ):
            raise _jelly_schema_error()
        if row["index"] in indexes or row["index"] not in range(count):
            raise _jelly_schema_error()
        indexes.add(row["index"])
        trend_counts[_JELLY_TREND_METRICS[row["trend"]]] += 1
        risk = risks[row["index"]]
        prose.extend(
            (
                _edit_jelly_sentence(row["cause"], risk.failure_path),
                _edit_jelly_sentence(row["fix"], risk.revision_question),
            )
        )
    if indexes != set(range(count)):
        raise _jelly_schema_error()
    try:
        require_native_business_korean(prose)
    except StructuredModelError:
        raise _jelly_schema_error() from None
    return trend_counts


def _run_jelly(base, evidence, runner, on_event):
    if not base.risks:
        return base
    notify = on_event or (lambda _node, _message, _metrics: None)
    rows = _safe_jelly_rows(base.risks, evidence)
    notify(
        "jelly_sidecar_started",
        "정아현 분석기에 안전한 근거 요약을 전달합니다.",
        {},
    )
    try:
        result = runner.run(rows)
    except StructuredModelError:
        raise
    except Exception:
        result = None
    if result is None:
        raise _team_unavailable("Jelly")
    trend_counts = _validated_jelly_trends(result, base.risks[: len(rows)])
    notify(
        "jelly_output_checked",
        "정아현 분석기의 행 연결과 한국어 문장을 확인하고 코드 결과를 유지했습니다.",
        trend_counts,
    )
    return base


class EventJellyRedteamAdapter:
    def __init__(
        self,
        *,
        base=None,
        runner=None,
        budget: ClaudeBudget | None = None,
        enabled: bool = False,
    ) -> None:
        self.base = base if base is not None else EventRedteamAgent()
        self.runner = runner if runner is not None else JellyRunner(budget=budget)
        self.enabled = enabled

    def run(self, event, pack, on_event=None):
        base = self.run_deterministic(event, pack, on_event=on_event)
        if not self.enabled:
            return base
        return _run_jelly(base, pack.evidence, self.runner, on_event)

    def run_deterministic(self, event, pack, on_event=None):
        return self.base.run_deterministic(event, pack, on_event=on_event)


class UpdateJellyRedteamAdapter:
    def __init__(
        self,
        *,
        base=None,
        runner=None,
        budget: ClaudeBudget | None = None,
        enabled: bool = False,
    ) -> None:
        self.base = base if base is not None else UpdateRedteamAgent()
        self.runner = runner if runner is not None else JellyRunner(budget=budget)
        self.enabled = enabled

    def run(self, brief, pack, on_event=None):
        base = self.run_deterministic(brief, pack, on_event=on_event)
        if not self.enabled:
            return base
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

    def __init__(self, *, client=None, budget: ClaudeBudget | None = None) -> None:
        self.client = client
        self.budget = budget if budget is not None else ClaudeBudget()

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
        if self.budget.max_tokens < 512:
            raise StructuredModelError(
                ErrorCode.BUDGET_EXCEEDED,
                "승진배 근거 판정기 출력 토큰 예산이 부족합니다.",
            )
        model = _model_from_env(
            "CLAUDE_AUDIT_MODEL", "claude-haiku-4-5-20251001"
        )
        self.budget.reserve(
            len(_jinbae_prompt(claim_text, candidate_chunks))
            + len(json.dumps(JUDGE_TOOL, ensure_ascii=False)),
            model=model,
        )
        client = self.client
        owns_client = client is None
        if client is None:
            try:
                from anthropic import AsyncAnthropic

                client = AsyncAnthropic(max_retries=0, timeout=30)
            except Exception:
                client = None
            if client is None:
                raise _team_unavailable("승진배")
        try:
            result = await asyncio.wait_for(
                judge_claim(
                    client,
                    model=model,
                    claim_text=claim_text,
                    candidate_chunks=candidate_chunks,
                    max_retries=0,
                ),
                timeout=35,
            )
        except Exception:
            result = None
        finally:
            if owns_client:
                try:
                    await client.close()
                except Exception:
                    pass
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
        result = probe.run(claim, chunks)
    except StructuredModelError as exc:
        if exc.code is ErrorCode.BUDGET_EXCEEDED:
            raise
        failed = True
    except Exception:
        failed = True
    else:
        failed = (
            not isinstance(result, dict)
            or result.get("verdict")
            not in {"grounded", "partially_grounded", "not_grounded"}
        )
    if failed:
        raise _team_unavailable("승진배")
    notify(
        "jinbae_probe_checked",
        "승진배 근거 판정기의 인용 ID를 확인하고 코드 판정을 유지했습니다.",
        {
            "calls": 1,
            "verdict": result["verdict"],
            "decision": base.decision.value,
        },
    )
    return base


class EventJinbaeAuditAdapter:
    def __init__(
        self,
        *,
        base=None,
        probe=None,
        budget: ClaudeBudget | None = None,
        enabled: bool = False,
    ) -> None:
        self.base = base if base is not None else AuditStrategyAgent()
        self.probe = probe if probe is not None else JinbaeProbe(budget=budget)
        self.enabled = enabled

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
        if not self.enabled:
            return base
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
    def __init__(
        self,
        *,
        base=None,
        probe=None,
        budget: ClaudeBudget | None = None,
        enabled: bool = False,
    ) -> None:
        self.base = base if base is not None else UpdateAuditAgent()
        self.probe = probe if probe is not None else JinbaeProbe(budget=budget)
        self.enabled = enabled

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
        if not self.enabled:
            return base
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
