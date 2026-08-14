from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from agents.structured import ClaudeBudget, StructuredModelError, parse_claude_structured, parse_structured, require_korean_text
from contracts import ErrorCode


class TinyOutput(BaseModel):
    answer: str


def test_korean_narrative_guard_rejects_all_english_text():
    with pytest.raises(StructuredModelError) as error:
        require_korean_text(["High risk requires revision"])
    assert error.value.code == ErrorCode.SCHEMA_INVALID


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


def test_claude_tool_output_uses_pydantic_schema(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input={"answer": "ok"})]
            )

    result = parse_claude_structured(
        model="claude-haiku-4-5",
        prompt_path=prompt,
        output_type=TinyOutput,
        payload={"input": "fixture"},
        client=SimpleNamespace(messages=Messages()),
        budget=ClaudeBudget(max_requests=1),
    )

    assert result.answer == "ok"
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "structured_output"}
    assert calls[0]["tools"][0]["input_schema"] == TinyOutput.model_json_schema()


def test_claude_missing_tool_output_becomes_refusal(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")

    class Messages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="cannot comply")]
            )

    with pytest.raises(StructuredModelError) as error:
        parse_claude_structured(
            model="claude-haiku-4-5",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=SimpleNamespace(messages=Messages()),
            budget=ClaudeBudget(max_requests=1),
        )
    assert error.value.code is ErrorCode.LLM_REFUSAL


def test_claude_budget_stops_before_an_extra_request(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")
    budget = ClaudeBudget(max_requests=0)

    with pytest.raises(StructuredModelError) as error:
        parse_claude_structured(
            model="claude-haiku-4-5",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=SimpleNamespace(),
            budget=budget,
        )

    assert error.value.code == ErrorCode.BUDGET_EXCEEDED
