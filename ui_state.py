from dataclasses import dataclass
from typing import Any, MutableMapping

from execution import AGENT_ORDER, ExecutionEvent, ExecutionState


@dataclass(frozen=True, slots=True)
class AgentView:
    agent: str
    state: ExecutionState
    current_node: str
    messages: tuple[str, ...]
    metrics: dict[str, int | float | str | bool]
    expanded: bool


@dataclass(frozen=True, slots=True)
class PipelineView:
    agents: tuple[AgentView, ...]
    show_decision: bool
    error: str | None


def build_pipeline_view(
    events: list[ExecutionEvent], *, finished: bool, error: str | None = None
) -> PipelineView:
    views = []
    for agent in AGENT_ORDER:
        observed = [item for item in events if item.agent == agent]
        latest = observed[-1] if observed else None
        views.append(
            AgentView(
                agent=agent,
                state=latest.state if latest else ExecutionState.WAITING,
                current_node=latest.node if latest else "queued",
                messages=tuple(item.message for item in observed if item.state != ExecutionState.WAITING),
                metrics=dict(latest.metrics) if latest else {},
                expanded=not finished or (latest is not None and latest.state == ExecutionState.FAILED),
            )
        )
    return PipelineView(tuple(views), show_decision=finished and error is None, error=error)


def begin_run(state: MutableMapping[str, Any], input_mode: str) -> None:
    state.pop("preflight_result", None)
    state.pop("preflight_error", None)
    state["execution_events"] = []
    state["active_input_mode"] = input_mode


def store_success(state: MutableMapping[str, Any], result: Any, *, input_mode: str) -> None:
    state["preflight_result"] = result
    state.pop("preflight_error", None)
    if input_mode == "fixture":
        state["fixture_backup_result"] = result


def store_failure(state: MutableMapping[str, Any], message: str) -> None:
    state.pop("preflight_result", None)
    state["preflight_error"] = message
