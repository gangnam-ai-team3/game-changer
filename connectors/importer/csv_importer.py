from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from urllib.parse import urlparse

from connectors import ConnectorError
from contracts import ErrorCode, EvidenceItem, Language, SourceType
from policy import CLOSED_RISK_SEVERITY

REQUIRED_COLUMNS = {
    "source",
    "source_url",
    "source_id",
    "language",
    "observed_at",
    "summary",
    "mechanism_tags",
}
FORBIDDEN_COLUMNS = {"username", "user_name", "author", "handle", "raw_text", "text", "content"}
APPROVED_HOSTS = {
    "reddit": (SourceType.REDDIT_IMPORT, {"reddit.com", "www.reddit.com"}),
    "threads": (SourceType.THREADS_IMPORT, {"threads.net", "www.threads.net"}),
    "instagram": (SourceType.INSTAGRAM_IMPORT, {"instagram.com", "www.instagram.com"}),
}
APPROVED_MECHANISM_TAGS = {category.value for category in CLOSED_RISK_SEVERITY}


def import_approved_csv(data: bytes | str, cutoff_at: datetime) -> list[EvidenceItem]:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    forbidden = columns & FORBIDDEN_COLUMNS
    if forbidden:
        _invalid(f"personal/raw columns are forbidden: {', '.join(sorted(forbidden))}")
    if not REQUIRED_COLUMNS.issubset(columns):
        missing = REQUIRED_COLUMNS - columns
        _invalid(f"missing columns: {', '.join(sorted(missing))}")

    results: list[EvidenceItem] = []
    for row_number, row in enumerate(reader, start=2):
        try:
            source_name = row["source"].strip().lower()
            source, hosts = APPROVED_HOSTS[source_name]
            url = row["source_url"].strip()
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in hosts
                or parsed.port not in (None, 443)
            ):
                raise ValueError("source URL is not from an approved host")
            observed_at = datetime.fromisoformat(row["observed_at"])
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError("observed_at must include a timezone")
            observed_at = observed_at.astimezone(UTC)
            if observed_at >= cutoff_at:
                raise ValueError("row is on or after cutoff_at")
            public_id = row["source_id"].strip()
            if not public_id:
                raise ValueError("source_id must not be empty")
            anonymous_id = hashlib.sha256(f"{source_name}:{public_id}".encode()).hexdigest()[:20]
            tags = sorted(
                {tag.strip().lower() for tag in row["mechanism_tags"].split("|") if tag.strip()}
            )
            if not tags or not set(tags) <= APPROVED_MECHANISM_TAGS:
                raise ValueError("mechanism_tags must contain only approved values")
            results.append(
                EvidenceItem(
                    evidence_id=f"imp-{anonymous_id}",
                    source=source,
                    source_url=f"https://{parsed.hostname}",
                    source_id=anonymous_id,
                    language=Language(row["language"].strip()),
                    observed_at=observed_at,
                    summary=(
                        f"비식별 승인 입력에서 {', '.join(tags)} "
                        "메커니즘 우려가 확인됨."
                    ),
                    mechanism_tags=tags,
                    relevance=1.0,
                )
            )
        except (KeyError, ValueError) as exc:
            _invalid(f"row {row_number}: {exc}")
    return results


def _invalid(message: str) -> None:
    raise ConnectorError(ErrorCode.INVALID_IMPORT, message)
