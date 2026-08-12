from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

AGENT_ORDER = ("collection", "evidence_rag_personas", "event_redteam", "audit_strategy")


class ExecutionState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETE = "complete"
    RETRYING = "retrying"
    FAILED = "failed"


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    agent: str
    node: str
    state: ExecutionState
    message: str = Field(min_length=1)
    metrics: dict[str, int | float | str | bool] = Field(default_factory=dict)


EventCallback = Callable[[ExecutionEvent], None]
