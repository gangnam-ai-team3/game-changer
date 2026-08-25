from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from contracts import ErrorCode, Language, SourceType


class ConnectorError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RawFeedback:
    """Ephemeral connector result. Never serialize this object to project storage."""

    source: SourceType
    source_url: str
    source_id: str
    language: Language
    observed_at: datetime
    text: str

