from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from agents.structured import StructuredModelError, parse_structured
from contracts import ErrorCode


class TinyOutput(BaseModel):
    answer: str


def test_responses_parse_uses_pydantic_contract(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")
    calls = []

    class Responses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed={"answer": "ok"})

    client = SimpleNamespace(responses=Responses())
    result = parse_structured(
        model="gpt-5.6-luna",
        prompt_path=prompt,
        output_type=TinyOutput,
        payload={"input": "fixture"},
        client=client,
    )
    assert result.answer == "ok"
    assert calls[0]["text_format"] is TinyOutput
    assert calls[0]["store"] is False


def test_invalid_parsed_payload_becomes_structured_schema_error(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")

    class Responses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed={"wrong": "shape"})

    client = SimpleNamespace(responses=Responses())
    with pytest.raises(StructuredModelError) as error:
        parse_structured(
            model="gpt-5.6-luna",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=client,
        )
    assert error.value.code == ErrorCode.SCHEMA_INVALID
