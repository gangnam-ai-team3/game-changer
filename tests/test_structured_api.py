from types import SimpleNamespace

import anthropic
import pytest
from pydantic import BaseModel

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    parse_structured,
    require_korean_text,
    require_prelaunch_narrative,
)
from contracts import ErrorCode


class TinyOutput(BaseModel):
    answer: str


def test_korean_narrative_guard_rejects_all_english_text():
    with pytest.raises(StructuredModelError) as error:
        require_korean_text(["High risk requires revision"])
    assert error.value.code == ErrorCode.SCHEMA_INVALID


def test_prelaunch_narrative_guard_rejects_postlaunch_claim():
    with pytest.raises(StructuredModelError) as error:
        require_prelaunch_narrative(["출시 후 사용자들이 좋아했다는 실제 반응일 가능성이 있음."])
    assert error.value.code is ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    "values",
    [
        ["예상", "이 기능은 항상 성공한다."],
        ["가능성", "업데이트 직후 인기가 치솟았다."],
    ],
)
def test_prelaunch_narrative_guard_requires_marker_for_each_field(values):
    with pytest.raises(StructuredModelError) as error:
        require_prelaunch_narrative(values)
    assert error.value.code is ErrorCode.SCHEMA_INVALID


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


def test_claude_budget_counts_system_prompt_and_hard_input_cap(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("안전 지침 " * 500, encoding="utf-8")
    calls = []

    class Messages:
        def create(self, **_kwargs):
            calls.append(True)

    with pytest.raises(StructuredModelError) as error:
        parse_claude_structured(
            model="claude-haiku-4-5",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=SimpleNamespace(messages=Messages()),
            budget=ClaudeBudget(max_requests=1, max_input_chars=300),
        )

    assert error.value.code is ErrorCode.BUDGET_EXCEEDED
    assert calls == []


def test_default_claude_client_disables_sdk_retries(tmp_path, monkeypatch):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")
    created = []

    class Messages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input={"answer": "ok"})]
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.messages = Messages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    result = parse_claude_structured(
        model="claude-haiku-4-5",
        prompt_path=prompt,
        output_type=TinyOutput,
        payload={"input": "fixture"},
        budget=ClaudeBudget(max_requests=1),
    )

    assert result.answer == "ok"
    assert created == [{"max_retries": 0}]


class AuthenticationError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@pytest.mark.parametrize(
    "failure",
    [
        AuthenticationError("key=test-key"),
        PermissionDeniedError("key=test-key"),
        StatusError(401),
        StatusError(403),
    ],
)
def test_claude_auth_failures_map_without_exposing_exception_text(tmp_path, failure):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")

    class Messages:
        def create(self, **_kwargs):
            raise failure

    with pytest.raises(StructuredModelError) as error:
        parse_claude_structured(
            model="claude-haiku-4-5",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=SimpleNamespace(messages=Messages()),
            budget=ClaudeBudget(max_requests=1),
        )

    assert error.value.code is ErrorCode.AUTH_FAILED
    assert "test-key" not in str(error.value)
