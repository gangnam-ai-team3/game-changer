from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from contracts import ErrorCode


class StructuredModelError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def require_korean_text(values: list[str]) -> None:
    """Reject an all-English narrative while allowing product names and IDs."""

    if any(value.strip() and not re.search(r"[가-힣]", value) for value in values):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Claude 자연어 결과에 한국어 문장이 필요합니다.",
        )


def _normalized_template(value: str) -> str:
    return " ".join(value.split())


def require_prelaunch_narrative(
    values: list[str],
    *,
    prediction_fields: list[str] | None = None,
    prospective_templates: list[str] | tuple[str, ...] | set[str] = (),
) -> None:
    """Require semantic prose to select an approved pre-launch template exactly."""

    require_korean_text(values)
    required = values if prediction_fields is None else prediction_fields
    require_korean_text(required)
    allowed = {_normalized_template(value) for value in prospective_templates}
    if any(_normalized_template(value) not in allowed for value in required):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Claude 의미 문장은 코드 소유 출시 전 템플릿과 일치해야 합니다.",
        )


@dataclass
class ClaudeBudget:
    """Conservative process-local guard for the academy's capped API key."""

    max_usd: float = float(os.getenv("CLAUDE_MAX_USD", "5"))
    max_requests: int = int(os.getenv("CLAUDE_MAX_REQUESTS", "3"))
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None
    max_tokens: int = int(os.getenv("CLAUDE_MAX_OUTPUT_TOKENS", "3000"))
    max_input_chars: int = int(os.getenv("CLAUDE_MAX_INPUT_CHARS", "50000"))
    requests: int = 0
    reserved_usd: float = 0

    def reserve(
        self,
        payload_chars: int,
        *,
        system_chars: int = 0,
        model: str = "claude-haiku-4-5",
    ) -> None:
        if self.requests >= self.max_requests:
            raise StructuredModelError(ErrorCode.BUDGET_EXCEEDED, "Claude 요청 한도에 도달했습니다.")
        input_chars = payload_chars + system_chars
        if input_chars > self.max_input_chars:
            raise StructuredModelError(ErrorCode.BUDGET_EXCEEDED, "Claude 입력 한도에 도달했습니다.")
        # One character per token deliberately over-reserves Korean and tool-schema input.
        estimated_input_tokens = max(input_chars, 1)
        sonnet = "sonnet" in model.lower()
        input_rate = self.input_usd_per_million
        output_rate = self.output_usd_per_million
        if input_rate is None:
            input_rate = float(os.getenv("CLAUDE_INPUT_USD_PER_MILLION", "3" if sonnet else "1"))
        if output_rate is None:
            output_rate = float(os.getenv("CLAUDE_OUTPUT_USD_PER_MILLION", "15" if sonnet else "5"))
        estimate = estimated_input_tokens / 1_000_000 * input_rate + self.max_tokens / 1_000_000 * output_rate
        if self.reserved_usd + estimate > self.max_usd:
            raise StructuredModelError(ErrorCode.BUDGET_EXCEEDED, "Claude 사용 예산 한도에 도달했습니다.")
        self.requests += 1
        self.reserved_usd += estimate


def _claude_error_code(exc: Exception) -> ErrorCode:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if str(status) in {"401", "403"} or type(exc).__name__ in {
        "AuthenticationError",
        "PermissionDeniedError",
    }:
        return ErrorCode.AUTH_FAILED
    return ErrorCode.SCHEMA_INVALID


def parse_structured[T: BaseModel](
    *,
    model: str,
    prompt_path: Path,
    output_type: type[T],
    payload: BaseModel | dict,
    client=None,
) -> T:
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise StructuredModelError(ErrorCode.AUTH_FAILED, "OPENAI_API_KEY is missing")
        from openai import OpenAI

        client = OpenAI()

    body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": prompt_path.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ],
            text_format=output_type,
            reasoning={"effort": "low"},
            store=False,
        )
        if response.output_parsed is None:
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "model returned no parsed output")
        return output_type.model_validate(response.output_parsed)
    except StructuredModelError:
        raise
    except Exception as exc:  # SDK and Pydantic exceptions differ by installed version.
        raise StructuredModelError(ErrorCode.SCHEMA_INVALID, str(exc)) from exc


def parse_claude_structured[T: BaseModel](
    *,
    model: str,
    prompt_path: Path,
    output_type: type[T],
    payload: BaseModel | dict,
    client=None,
    budget: ClaudeBudget | None = None,
) -> T:
    if client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise StructuredModelError(ErrorCode.AUTH_FAILED, "ANTHROPIC_API_KEY is missing")
        from anthropic import Anthropic

        client = Anthropic(max_retries=0)

    body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    encoded = json.dumps(body, ensure_ascii=False)
    system_prompt = (
        prompt_path.read_text(encoding="utf-8")
        + "\nReturn the result only through the required structured_output tool."
    )
    tool_schema = output_type.model_json_schema()
    active_budget = budget or ClaudeBudget()
    active_budget.reserve(
        len(encoded) + len(json.dumps(tool_schema, ensure_ascii=False)),
        system_chars=len(system_prompt),
        model=model,
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=active_budget.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": encoded}],
            tools=[
                {
                    "name": "structured_output",
                    "description": "Return data that exactly matches the supplied schema.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "structured_output"},
        )
        for block in response.content:
            block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if block_type != "tool_use":
                continue
            value = block.get("input") if isinstance(block, dict) else getattr(block, "input", None)
            if value is not None:
                return output_type.model_validate(value)
        raise StructuredModelError(ErrorCode.LLM_REFUSAL, "Claude가 구조화된 결과를 반환하지 않았습니다.")
    except StructuredModelError:
        raise
    except Exception as exc:  # SDK and Pydantic exceptions differ by installed version.
        code = _claude_error_code(exc)
        message = (
            "Claude 인증 또는 권한 확인에 실패했습니다."
            if code is ErrorCode.AUTH_FAILED
            else "Claude 구조화 결과를 검증하지 못했습니다."
        )
        raise StructuredModelError(code, message) from None
