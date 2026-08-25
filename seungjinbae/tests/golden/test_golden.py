import json
import os
from pathlib import Path

import pytest
import voyageai
from anthropic import AsyncAnthropic

from app import pipeline
from app.config import get_settings

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())

pytestmark = pytest.mark.golden


def _has_real_keys() -> bool:
    return (
        os.environ.get("ANTHROPIC_API_KEY", "test-key") != "test-key"
        and os.environ.get("VOYAGE_API_KEY", "test-key") != "test-key"
    )


@pytest.mark.skipif(
    not _has_real_keys(), reason="set real ANTHROPIC_API_KEY/VOYAGE_API_KEY to run the golden suite"
)
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_golden_case_matches_expected_verdicts(case):
    settings = get_settings()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    voyage_client = voyageai.Client(api_key=settings.voyage_api_key)

    result = await pipeline.run_audit(
        anthropic_client=anthropic_client,
        voyage_client=voyage_client,
        settings=settings,
        response_text=case["response_text"],
        source_chunks=case["source_chunks"],
    )

    actual_verdicts = [c["verdict"] for c in result["claims"]]
    assert actual_verdicts == case["expected_verdicts"]
