import io
import json
from datetime import UTC, datetime

import pytest

from connectors import ConnectorError
from connectors.steam import SteamClient
from connectors.x import ProjectBudget, XClient
from contracts import ErrorCode, Language


def test_x_requires_authentication(event):
    with pytest.raises(ConnectorError) as error:
        XClient(None).fetch_recent("PUBG", Language.ENGLISH, event.cutoff_at)
    assert error.value.code == ErrorCode.AUTH_FAILED


def test_x_enforces_project_budget(event):
    client = XClient("token", budget=ProjectBudget(cap_usd=10, spent_usd=9.5))
    with pytest.raises(ConnectorError) as error:
        client.fetch_recent(
            "PUBG",
            Language.ENGLISH,
            event.cutoff_at,
            estimated_cost_usd=0.51,
        )
    assert error.value.code == ErrorCode.BUDGET_EXCEEDED


def test_steam_filters_cutoff_and_anonymizes_id(event):
    payload = {
        "reviews": [
            {
                "recommendationid": "public-review-id",
                "timestamp_created": int(datetime(2025, 6, 10, tzinfo=UTC).timestamp()),
                "review": "double gacha is confusing",
            },
            {
                "recommendationid": "leaked-id",
                "timestamp_created": int(event.cutoff_at.timestamp()),
                "review": "must be excluded",
            },
        ],
        "cursor": "",
    }

    def opener(_request, timeout):
        assert timeout == 20
        return io.BytesIO(json.dumps(payload).encode())

    [item] = SteamClient(opener=opener).fetch_reviews(
        578080, Language.ENGLISH, event.cutoff_at, limit=10
    )
    assert item.source_id != "public-review-id"
    assert item.observed_at < event.cutoff_at
