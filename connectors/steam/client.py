from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from connectors import ConnectorError, RawFeedback
from contracts import ErrorCode, Language, SourceType

STEAM_LANGUAGES = {
    Language.ENGLISH: "english",
    Language.KOREAN: "koreana",
    Language.CHINESE_SIMPLIFIED: "schinese",
    Language.SPANISH: "spanish",
    Language.PORTUGUESE_BRAZIL: "brazilian",
}


class SteamClient:
    def __init__(self, opener=urlopen) -> None:
        self._opener = opener

    def fetch_reviews(
        self,
        app_id: int,
        language: Language,
        cutoff_at: datetime,
        limit: int = 100,
        *,
        start_at: datetime | None = None,
    ) -> list[RawFeedback]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if start_at is not None and (
            start_at.tzinfo is None or start_at >= cutoff_at
        ):
            raise ValueError("start_at must be timezone-aware and earlier than cutoff_at")

        results: list[RawFeedback] = []
        cursor = "*"
        try:
            for _ in range(5):
                params = urlencode(
                    {
                        "json": 1,
                        "filter": "recent",
                        "language": STEAM_LANGUAGES[language],
                        "cursor": cursor,
                        "review_type": "all",
                        "purchase_type": "all",
                        "num_per_page": min(100, limit - len(results)),
                    }
                )
                url = f"https://store.steampowered.com/appreviews/{app_id}?{params}"
                with self._opener(Request(url, headers={"User-Agent": "EventPreflight/1.0"}), timeout=20) as response:
                    payload = json.load(response)

                reviews = payload.get("reviews", [])
                if not reviews:
                    break
                for review in reviews:
                    observed_at = datetime.fromtimestamp(review["timestamp_created"], tz=UTC)
                    if observed_at >= cutoff_at or (
                        start_at is not None and observed_at < start_at
                    ):
                        continue
                    public_id = str(review["recommendationid"])
                    results.append(
                        RawFeedback(
                            source=SourceType.STEAM,
                            # The review identifier and app path are external
                            # metadata.  The collector only needs the trusted
                            # source host, so avoid carrying either forward.
                            source_url="https://steamcommunity.com",
                            source_id=_anonymous_id(public_id),
                            language=language,
                            observed_at=observed_at,
                            text=str(review.get("review", "")),
                        )
                    )
                    if len(results) >= limit:
                        return results
                cursor = payload.get("cursor", "")
                if not cursor:
                    break
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, f"Steam GetReviews failed: {exc}") from exc
        return results


def _anonymous_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]
