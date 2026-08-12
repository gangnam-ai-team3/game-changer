from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from connectors import ConnectorError, RawFeedback
from contracts import ErrorCode, Language, SourceType


@dataclass(slots=True)
class ProjectBudget:
    cap_usd: float = 10.0
    spent_usd: float = 0.0

    def reserve(self, estimated_cost_usd: float) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("estimated cost cannot be negative")
        if self.spent_usd + estimated_cost_usd > self.cap_usd:
            raise ConnectorError(ErrorCode.BUDGET_EXCEEDED, "X project budget would exceed $10")
        self.spent_usd += estimated_cost_usd


class XClient:
    def __init__(
        self,
        bearer_token: str | None,
        budget: ProjectBudget | None = None,
        opener=urlopen,
    ) -> None:
        self._token = bearer_token
        self._budget = budget or ProjectBudget()
        self._opener = opener

    def fetch_recent(
        self,
        query: str,
        language: Language,
        cutoff_at: datetime,
        max_results: int = 10,
        estimated_cost_usd: float = 0.0,
    ) -> list[RawFeedback]:
        if not self._token:
            raise ConnectorError(ErrorCode.AUTH_FAILED, "X_BEARER_TOKEN is missing")
        if not 10 <= max_results <= 100:
            raise ValueError("X max_results must be between 10 and 100")
        self._budget.reserve(estimated_cost_usd)

        params = urlencode(
            {
                "query": f"({query}) lang:{_x_language(language)} -is:retweet",
                "max_results": max_results,
                "tweet.fields": "created_at,lang",
            }
        )
        request = Request(
            f"https://api.x.com/2/tweets/search/recent?{params}",
            headers={"Authorization": f"Bearer {self._token}", "User-Agent": "EventPreflight/1.0"},
        )
        try:
            with self._opener(request, timeout=20) as response:
                payload = json.load(response)
        except HTTPError as exc:
            code = ErrorCode.AUTH_FAILED if exc.code in {401, 403} else ErrorCode.SOURCE_UNAVAILABLE
            raise ConnectorError(code, f"X API failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, f"X API failed: {exc}") from exc

        results: list[RawFeedback] = []
        for item in payload.get("data", []):
            observed_at = datetime.fromisoformat(item["created_at"]).astimezone(UTC)
            if observed_at >= cutoff_at:
                continue
            public_id = str(item["id"])
            results.append(
                RawFeedback(
                    source=SourceType.X,
                    source_url=f"https://x.com/i/web/status/{public_id}",
                    source_id=hashlib.sha256(public_id.encode()).hexdigest()[:20],
                    language=language,
                    observed_at=observed_at,
                    text=str(item.get("text", "")),
                )
            )
        return results


def _x_language(language: Language) -> str:
    return {
        Language.ENGLISH: "en",
        Language.KOREAN: "ko",
        Language.CHINESE_SIMPLIFIED: "zh",
        Language.SPANISH: "es",
        Language.PORTUGUESE_BRAZIL: "pt",
    }[language]
