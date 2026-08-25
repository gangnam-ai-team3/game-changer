import asyncio

VALID_VERDICTS = {"grounded", "not_grounded", "partially_grounded"}
JUDGE_MAX_TOKENS = 1024

JUDGE_TOOL = {
    "name": "judge_claim",
    "description": "Judge whether a claim is grounded in the provided source chunks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["grounded", "not_grounded", "partially_grounded"],
            },
            "citations": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "citations", "rationale"],
        "additionalProperties": False,
    },
    "strict": True,
}


class JudgeError(Exception):
    pass


def _validate_judge_result(result: dict) -> None:
    if set(result.keys()) != {"verdict", "citations", "rationale"}:
        raise JudgeError(f"unexpected keys in judge result: {sorted(result.keys())}")
    if result["verdict"] not in VALID_VERDICTS:
        raise JudgeError(f"invalid verdict: {result['verdict']!r}")
    if not isinstance(result["citations"], list):
        raise JudgeError("citations must be a list")
    if not isinstance(result["rationale"], str):
        raise JudgeError("rationale must be a str")


async def judge_claim(
    client,
    *,
    model: str,
    claim_text: str,
    candidate_chunks: list[dict],
    max_retries: int = 2,
) -> dict:
    chunks_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in candidate_chunks)
    prompt = (
        "Given the claim and candidate source chunks below, judge whether the claim is "
        "grounded in the chunks. Cite the chunk ids that support your verdict.\n\n"
        f"Claim: {claim_text}\n\nCandidate chunks:\n{chunks_block}"
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=JUDGE_MAX_TOKENS,
                thinking={"type": "disabled"},
                tools=[JUDGE_TOOL],
                tool_choice={"type": "tool", "name": "judge_claim"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in message.content:
                if block.type == "tool_use" and block.name == "judge_claim":
                    result = dict(block.input)
                    _validate_judge_result(result)
                    return result
            raise JudgeError("no tool_use block in response")
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)
    raise JudgeError(f"judge_claim failed after {max_retries + 1} attempts") from last_error
