from types import SimpleNamespace

from pydantic import BaseModel

from agents.structured import parse_structured


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
