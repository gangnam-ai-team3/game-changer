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
    def __init__(self, opener=urlopen, *, max_pages: int = 5) -> None:
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        self._opener = opener
        self._max_pages = max_pages

    def fetch_reviews(
        self,
        app_id: int,
        language: Language,
        cutoff_at: datetime,
        limit: int = 100,
        *,
        start_at: datetime | None = None,
    ) -> list[RawFeedback]:
        if isinstance(app_id, bool) or not isinstance(app_id, int) or app_id <= 0:
            raise ValueError("app_id must be a positive integer")
        if not isinstance(language, Language):
            raise ValueError("language must be supported")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if cutoff_at.tzinfo is None:
            raise ValueError("cutoff_at must be timezone-aware")
        if start_at is not None and (
            start_at.tzinfo is None or start_at >= cutoff_at
        ):
            raise ValueError("start_at must be timezone-aware and earlier than cutoff_at")

        results: list[RawFeedback] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor = "*"
        try:
            # ponytail: cap one language at 500 fetched rows by default;
            # callers may raise max_pages after checking Steam traffic limits.
            for _ in range(self._max_pages):
                if cursor in seen_cursors:
                    raise ValueError("Steam API repeated a cursor")
                seen_cursors.add(cursor)
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
                with self._opener(
                    Request(url, headers={"User-Agent": "GameChanger/1.0"}),
                    timeout=20,
                ) as response:
                    payload = json.load(response)

                if not isinstance(payload, dict) or payload.get("success") != 1:
                    raise ValueError("invalid Steam API response")
                reviews = payload.get("reviews")
                if not isinstance(reviews, list):
                    raise ValueError("invalid Steam reviews response")
                if not reviews:
                    break
                reached_start = False
                for review in reviews:
                    if not isinstance(review, dict):
                        continue
                    try:
                        observed_at = datetime.fromtimestamp(
                            int(review["timestamp_created"]), tz=UTC
                        )
                        public_id = str(review["recommendationid"]).strip()
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                    text = review.get("review")
                    response_language = review.get("language")
                    if not public_id or not isinstance(text, str) or not text.strip():
                        continue
                    if response_language != STEAM_LANGUAGES[language]:
                        continue
                    if start_at is not None and observed_at < start_at:
                        reached_start = True
                        continue
                    if observed_at >= cutoff_at:
                        continue
                    source_id = _anonymous_id(public_id)
                    if source_id in seen_ids:
                        continue
                    seen_ids.add(source_id)
                    results.append(
                        RawFeedback(
                            source=SourceType.STEAM,
                            # The review identifier and app path are external
                            # metadata.  The collector only needs the trusted
                            # source host, so avoid carrying either forward.
                            source_url="https://steamcommunity.com",
                            source_id=source_id,
                            language=language,
                            observed_at=observed_at,
                            text=text.strip(),
                        )
                    )
                    if len(results) >= limit:
                        return results
                if reached_start:
                    break
                next_cursor = payload.get("cursor")
                if not isinstance(next_cursor, str) or not next_cursor:
                    raise ValueError("Steam API omitted its next cursor")
                cursor = next_cursor
            else:
                raise ConnectorError(
                    ErrorCode.SOURCE_UNAVAILABLE,
                    "검토 기준일까지 확인하기 전에 Steam 리뷰 수집 한도에 도달했습니다. "
                    "수집 기간을 좁혀 다시 실행해 주세요.",
                )
        except HTTPError as exc:
            raise ConnectorError(
                ErrorCode.SOURCE_UNAVAILABLE,
                f"Steam 리뷰 API 요청에 실패했습니다. (HTTP {exc.code})",
            ) from exc
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectorError(
                ErrorCode.SOURCE_UNAVAILABLE,
                "Steam 리뷰 API 응답을 확인할 수 없습니다.",
            ) from exc
        return results


def _anonymous_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]
