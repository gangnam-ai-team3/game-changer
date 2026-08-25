import io
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

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
    pages = [
        {
            "success": 1,
            "reviews": [
                {
                    "recommendationid": "public-review-id",
                    "author": {"steamid": "private-steam-id"},
                    "timestamp_created": int(
                        datetime(2025, 6, 10, tzinfo=UTC).timestamp()
                    ),
                    "language": "english",
                    "review": "double gacha is confusing",
                },
                {
                    "recommendationid": "leaked-id",
                    "timestamp_created": int(event.cutoff_at.timestamp()),
                    "language": "english",
                    "review": "must be excluded",
                },
            ],
            "cursor": "last-page",
        },
        {"success": 1, "reviews": [], "cursor": "last-page"},
    ]
    calls = 0

    def opener(_request, timeout):
        nonlocal calls
        assert timeout == 20
        response = io.BytesIO(json.dumps(pages[calls]).encode())
        calls += 1
        return response

    [item] = SteamClient(opener=opener).fetch_reviews(
        578080, Language.ENGLISH, event.cutoff_at, limit=10
    )
    assert item.source_id != "public-review-id"
    assert "private-steam-id" not in repr(item)
    assert item.observed_at < event.cutoff_at


def test_steam_uses_official_cursor_api_and_deduplicates_reviews(event):
    calls: list[dict[str, list[str]]] = []
    pages = [
        {
            "success": 1,
            "reviews": [
                {
                    "recommendationid": "first",
                    "timestamp_created": int(
                        datetime(2025, 6, 9, tzinfo=UTC).timestamp()
                    ),
                    "language": "english",
                    "review": "first review",
                },
                {
                    "recommendationid": "malformed",
                    "timestamp_created": "not-a-timestamp",
                    "review": "ignored",
                },
                {
                    "recommendationid": "wrong-language",
                    "timestamp_created": int(
                        datetime(2025, 6, 9, tzinfo=UTC).timestamp()
                    ),
                    "language": "koreana",
                    "review": "ignored",
                },
            ],
            "cursor": "next page + token",
        },
        {
            "success": 1,
            "reviews": [
                {
                    "recommendationid": "first",
                    "timestamp_created": int(
                        datetime(2025, 6, 9, tzinfo=UTC).timestamp()
                    ),
                    "language": "english",
                    "review": "duplicate",
                },
                {
                    "recommendationid": "second",
                    "timestamp_created": int(
                        datetime(2025, 6, 8, tzinfo=UTC).timestamp()
                    ),
                    "language": "english",
                    "review": "second review",
                },
            ],
            "cursor": "",
        },
    ]

    def opener(request, timeout):
        assert timeout == 20
        parsed = urlparse(request.full_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "store.steampowered.com"
        assert parsed.path == "/appreviews/578080"
        calls.append(parse_qs(parsed.query))
        return io.BytesIO(json.dumps(pages[len(calls) - 1]).encode())

    rows = SteamClient(opener=opener).fetch_reviews(
        578080, Language.ENGLISH, event.cutoff_at, limit=2
    )

    assert [item.text for item in rows] == ["first review", "second review"]
    assert calls[0] == {
        "json": ["1"],
        "filter": ["recent"],
        "language": ["english"],
        "cursor": ["*"],
        "review_type": ["all"],
        "purchase_type": ["all"],
        "num_per_page": ["2"],
    }
    assert calls[1]["cursor"] == ["next page + token"]


def test_steam_rejects_failed_or_malformed_api_response(event):
    def opener(_request, timeout):
        assert timeout == 20
        return io.BytesIO(json.dumps({"success": 0, "reviews": []}).encode())

    with pytest.raises(ConnectorError) as error:
        SteamClient(opener=opener).fetch_reviews(
            578080, Language.KOREAN, event.cutoff_at
        )

    assert error.value.code is ErrorCode.SOURCE_UNAVAILABLE
    assert str(error.value) == "Steam 리뷰 API 응답을 확인할 수 없습니다."


def test_steam_rejects_nonempty_page_without_next_cursor(event):
    payload = {
        "success": 1,
        "reviews": [
            {
                "recommendationid": "incomplete-page",
                "timestamp_created": int(
                    datetime(2025, 6, 9, tzinfo=UTC).timestamp()
                ),
                "language": "english",
                "review": "must not become a complete result",
            }
        ],
    }

    def opener(_request, timeout):
        assert timeout == 20
        return io.BytesIO(json.dumps(payload).encode())

    with pytest.raises(ConnectorError) as error:
        SteamClient(opener=opener).fetch_reviews(
            578080, Language.ENGLISH, event.cutoff_at
        )

    assert error.value.code is ErrorCode.SOURCE_UNAVAILABLE


@pytest.mark.parametrize("app_id", [0, -1, True])
def test_steam_rejects_invalid_app_id(app_id, event):
    with pytest.raises(ValueError, match="app_id"):
        SteamClient().fetch_reviews(app_id, Language.ENGLISH, event.cutoff_at)


@pytest.mark.parametrize(
    ("max_pages", "next_cursor"),
    [(1, "another-page"), (2, "*")],
)
def test_steam_reports_pagination_failure_instead_of_silent_empty(
    event, max_pages, next_cursor
):
    def opener(_request, timeout):
        assert timeout == 20
        payload = {
            "success": 1,
            "reviews": [
                {
                    "recommendationid": "after-cutoff",
                    "timestamp_created": int(event.cutoff_at.timestamp()),
                    "language": "english",
                    "review": "excluded",
                }
            ],
            "cursor": next_cursor,
        }
        return io.BytesIO(json.dumps(payload).encode())

    with pytest.raises(ConnectorError) as error:
        SteamClient(opener=opener, max_pages=max_pages).fetch_reviews(
            578080, Language.ENGLISH, event.cutoff_at
        )

    assert error.value.code is ErrorCode.SOURCE_UNAVAILABLE
    if max_pages == 1:
        assert "수집 한도에 도달" in str(error.value)
