import asyncio

EXTRACT_TOOL = {
    "name": "extract_claims",
    "description": "Extract discrete factual claims from the response text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of individual factual claims found in the text.",
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    },
    "strict": True,
}


class ExtractionError(Exception):
    pass


async def extract_claims(
    client, *, model: str, response_text: str, max_retries: int = 2
) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=8000,
                tools=[EXTRACT_TOOL],
                tool_choice={"type": "tool", "name": "extract_claims"},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Break the following response into a list of discrete, "
                            "independently checkable factual claims. Do not include "
                            f"greetings or filler.\n\nResponse:\n{response_text}"
                        ),
                    }
                ],
            )
            if message.stop_reason == "max_tokens":
                raise ExtractionError("claim extraction response was truncated (max_tokens)")
            for block in message.content:
                if block.type == "tool_use" and block.name == "extract_claims":
                    return list(block.input.get("claims", []))
            return []
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)
    raise ExtractionError(
        f"extract_claims failed after {max_retries + 1} attempts"
    ) from last_error
