from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from contracts import ErrorCode


class StructuredModelError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    except Exception as exc:  # SDK exceptions differ by installed version.
        raise StructuredModelError(ErrorCode.SCHEMA_INVALID, str(exc)) from exc
    if response.output_parsed is None:
        raise StructuredModelError(ErrorCode.LLM_REFUSAL, "model returned no parsed output")
    return output_type.model_validate(response.output_parsed)
