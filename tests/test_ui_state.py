from execution import AGENT_ORDER, ExecutionEvent, ExecutionState
from ui_state import begin_run, build_pipeline_view, store_failure, store_success


def event(sequence, agent, node, state):
    return ExecutionEvent(
        sequence=sequence,
        agent=agent,
        node=node,
        state=state,
        message=f"{agent}:{node}",
    )


def waiting_events():
    return [
        event(index, agent, "waiting", ExecutionState.WAITING)
        for index, agent in enumerate(AGENT_ORDER)
    ]


def test_running_view_expands_all_agent_cards_and_highlights_latest_node():
    events = [
        *waiting_events(),
        event(4, "collection", "source_selected", ExecutionState.RUNNING),
    ]
    view = build_pipeline_view(events, finished=False)
    assert view.show_decision is False
    assert all(agent.expanded for agent in view.agents)
    assert view.agents[0].current_node == "source_selected"
    assert view.agents[0].state == ExecutionState.RUNNING


def test_running_view_keeps_not_yet_emitted_agents_waiting():
    view = build_pipeline_view([event(0, "collection", "queued", ExecutionState.WAITING)], finished=False)
    assert [agent.state for agent in view.agents[1:]] == [ExecutionState.WAITING] * 3


def test_completed_view_collapses_agent_cards_and_uses_decision_view():
    events = waiting_events() + [
        event(index + 4, agent, "complete", ExecutionState.COMPLETE)
        for index, agent in enumerate(AGENT_ORDER)
    ]
    view = build_pipeline_view(events, finished=True)
    assert view.show_decision is True
    assert all(not agent.expanded for agent in view.agents)


def test_failed_view_marks_failed_agent_and_keeps_downstream_waiting():
    events = waiting_events() + [
        event(4, "collection", "bundle_ready", ExecutionState.COMPLETE),
        event(5, "evidence_rag_personas", "pack_ready", ExecutionState.FAILED),
    ]
    view = build_pipeline_view(events, finished=False, error="SCHEMA_INVALID")
    assert view.agents[1].state == ExecutionState.FAILED
    assert view.agents[1].expanded is True
    assert all(agent.state == ExecutionState.WAITING for agent in view.agents[2:])


def test_new_run_clears_stale_result_but_preserves_fixture_backup():
    state = {
        "preflight_result": "stale",
        "preflight_error": "old",
        "fixture_backup_result": "safe",
    }
    begin_run(state, "live")
    assert "preflight_result" not in state
    assert "preflight_error" not in state
    assert state["fixture_backup_result"] == "safe"
    store_failure(state, "network down")
    assert state["fixture_backup_result"] == "safe"
    store_success(state, "fixture-result", input_mode="fixture")
    assert state["fixture_backup_result"] == "fixture-result"
