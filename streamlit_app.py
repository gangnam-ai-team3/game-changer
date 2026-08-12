from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from agents.collector import CollectionOptions
from contracts import ArtifactStatus, EventBrief, InputMode, Producer
from evaluation.backtest import evaluate_black_market
from evaluation.fixtures import load_demo_event
from execution import ExecutionEvent, ExecutionState
from orchestrator import EventPreflightOrchestrator, PipelineResult, PipelineStopped
from ui_state import AgentView, PipelineView, begin_run, build_pipeline_view, store_failure, store_success

SOURCE_MODES = {
    "검증된 저장 데이터": "fixture",
    "Steam 실시간 갱신": "live",
    "승인 CSV 가져오기": "import",
}

AGENT_LABELS = {
    "collection": "수집 에이전트",
    "evidence_rag_personas": "근거 분석 에이전트",
    "event_redteam": "레드팀 에이전트",
    "audit_strategy": "감사·전략 에이전트",
}

STATE_LABELS = {
    ExecutionState.WAITING: "대기",
    ExecutionState.RUNNING: "실행 중",
    ExecutionState.COMPLETE: "완료",
    ExecutionState.RETRYING: "재시도 중",
    ExecutionState.FAILED: "실패",
}

TRACE_ARTIFACTS: tuple[tuple[str, str, Callable[[PipelineResult], Any]], ...] = (
    ("1. 수집 에이전트", "FeedbackBundle", lambda result: result.feedback),
    ("2. 근거 분석 에이전트", "EvidencePack", lambda result: result.evidence),
    ("3. 레드팀 에이전트", "RiskAssessment", lambda result: result.risks),
    ("4. 감사·전략 에이전트", "ValidatedDecision", lambda result: result.validated),
)
AGENT_CONTRACTS = {
    "collection": "FeedbackBundle",
    "evidence_rag_personas": "EvidencePack",
    "event_redteam": "RiskAssessment",
    "audit_strategy": "ValidatedDecision",
}
AGENT_BY_CONTRACT = {contract: agent for agent, contract in AGENT_CONTRACTS.items()}


st.set_page_config(page_title="게임체인저(Game Changer)", page_icon="🛡️", layout="wide")
st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2rem;}
    [data-testid="stMetricValue"] {font-size: 2rem;}
    .ep-kicker {color:#64748b; font-weight:700; letter-spacing:.08em; font-size:.78rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _load_secrets() -> None:
    try:
        secrets = dict(st.secrets)
    except StreamlitSecretNotFoundError:
        return
    for name in ("OPENAI_API_KEY", "X_BEARER_TOKEN"):
        if name in secrets and not os.getenv(name):
            os.environ[name] = str(secrets[name])


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _render_agent_card(agent: AgentView) -> None:
    with st.container(border=True):
        st.markdown(
            f"**{AGENT_LABELS[agent.agent]}** · `{agent.current_node}` · "
            f"**{STATE_LABELS[agent.state]}**"
        )
        for message in agent.messages:
            st.write(message)
        if agent.metrics:
            st.table([agent.metrics])
        st.caption(f"예상 출력 계약: `{AGENT_CONTRACTS[agent.agent]}`")


def _render_running_pipeline(placeholder: Any, view: PipelineView) -> None:
    placeholder.empty()
    with placeholder.container():
        st.header("2. 수집 → RAG·페르소나 → 레드팀 → 감사")
        for agent in view.agents:
            _render_agent_card(agent)


def _trace_id_rows(contract_name: str, artifact: Any) -> list[dict[str, str]]:
    if contract_name == "FeedbackBundle":
        return [{"종류": "근거 ID", "값": item.evidence_id} for item in artifact.evidence]
    if contract_name == "EvidencePack":
        return [
            *({"종류": "근거 ID", "값": item.evidence_id} for item in artifact.evidence),
            *({"종류": "이슈 ID", "값": item.issue_id} for item in artifact.issues),
        ]
    if contract_name == "RiskAssessment":
        return [
            {"종류": "위험 ID · 근거 ID", "값": f"{risk.risk_id} · {', '.join(risk.evidence_ids)}"}
            for risk in artifact.risks
        ]
    return [
        {"종류": "위험 ID", "값": risk.risk_id} for risk in artifact.validated_risks
    ] + [
        {"종류": "수정 대상 위험 ID", "값": ", ".join(action.addresses_risk_ids)}
        for action in artifact.priority_revisions
    ]


def _render_trace(contract_name: str, artifact: Any, events: list[ExecutionEvent]) -> None:
    st.markdown(f"**계약:** `{contract_name}`")
    st.caption(f"입력 참조: {', '.join(artifact.input_refs) or '없음'}")
    errors = [f"{error.code.value}: {error.message}" for error in artifact.errors]
    st.caption(f"오류: {' · '.join(errors) or '없음'}")
    agent = AGENT_BY_CONTRACT[contract_name]
    agent_events = [event for event in events if event.agent == agent]
    messages = [event.message for event in agent_events]
    st.markdown(f"**실행 메시지:** {' · '.join(messages) or '없음'}")
    metrics = [event.metrics for event in agent_events if event.metrics]
    if metrics:
        st.markdown("**실행 지표**")
        st.table(metrics)
    st.markdown("**근거 ID · 위험 ID**")
    st.table(_trace_id_rows(contract_name, artifact))


def _render_decision(placeholder: Any, result: PipelineResult) -> None:
    brief = result.brief
    placeholder.empty()
    with placeholder.container():
        st.header("3. 의사결정 브리프")
        st.warning("이 브리프는 자문용이며, 담당자가 검토한 뒤 사람이 최종 결정을 내립니다.")
        if result.fallback_used or result.analysis_incomplete:
            st.warning("일부 분석이 결정론적 안전 경로를 사용해 결과가 불완전할 수 있습니다.")
        decision_col, risk_col, evidence_col, language_col = st.columns(4)
        decision_col.metric("최종 판정", brief.decision.value)
        risk_col.metric("상위 위험", len(brief.top_risks))
        evidence_col.metric("비식별 근거", len(brief.evidence))
        visible = sum(item.conclusion is not None for item in brief.language_results)
        language_col.metric("언어권 결론", f"{visible}/5")
        st.info(brief.executive_summary)

        st.subheader("상위 위험")
        st.table(
            [
                {
                    "등급": risk.severity.value,
                    "위험": risk.title,
                    "신뢰도": f"{risk.confidence:.0%}",
                    "근거": len(risk.evidence_ids),
                    "실패 경로": risk.failure_path,
                }
                for risk in brief.top_risks
            ]
        )

        panel_tab, language_tab, revision_tab, evidence_tab = st.tabs(
            ["플레이어 패널", "언어권", "수정 기획안", "근거 ID"]
        )
        with panel_tab:
            for panel in brief.panel_results:
                st.markdown(f"**{panel.persona.value}** — {panel.reaction}  ")
                st.caption(f"근거 {len(panel.evidence_ids)}개 · 신뢰도 {panel.confidence:.0%}")
        with language_tab:
            for insight in brief.language_results:
                if insight.conclusion:
                    st.markdown(f"**{insight.language.value}** — {insight.conclusion}")
                else:
                    st.warning(f"{insight.language.value}: 결론 숨김 — {insight.hidden_reason}")
        with revision_tab:
            for action in brief.revision_plan:
                st.markdown(f"**{action.priority}. {action.title}**")
                st.write(action.change)
                st.caption(f"완료 기준: {action.success_metric}")
        with evidence_tab:
            st.caption("비식별 근거의 ID와 출처만 표시합니다. 원문은 렌더링하지 않습니다.")
            st.table(
                [
                    {
                        "근거 ID": item.evidence_id,
                        "언어": item.language.value,
                        "출처": item.source.value,
                        "synthetic": str(item.synthetic).lower(),
                    }
                    for item in brief.evidence
                ]
            )

        for label, contract_name, get_artifact in TRACE_ARTIFACTS:
            with st.expander(label, expanded=False):
                _render_trace(contract_name, get_artifact(result), result.events)

        if (
            result.feedback.input_mode == InputMode.FIXTURE
            and brief.evidence
            and all(item.synthetic for item in brief.evidence)
        ):
            st.subheader("데모 전용 백테스트")
            score = evaluate_black_market(brief)
            st.caption("2026 정답지는 의사결정 브리프가 완성된 뒤에만 읽습니다. 실제 예측이 아닌 회고형 시뮬레이션입니다.")
            score_a, score_b, score_c = st.columns(3)
            score_a.metric("공식 핵심 문제 발견", f"{score.detected_count}/{score.target_count}")
            score_b.metric("상위 위험 근거 연결", f"{score.evidence_link_rate:.0%}")
            score_c.metric(
                f"{score.sampled_claim_count}건 주장 지지", f"{score.sampled_claim_support_rate:.0%}"
            )
            st.success("완료 기준 통과" if score.passed else "완료 기준 미달")

        st.download_button(
            "의사결정 브리프 JSON 다운로드",
            data=json.dumps(brief.model_dump(mode="json"), ensure_ascii=False, indent=2),
            file_name=f"game-experience-preflight-{brief.run_id}.json",
            mime="application/json",
        )


def _request_fixture_rerun() -> None:
    st.session_state["source_mode"] = "검증된 저장 데이터"
    st.session_state["rerun_fixture_requested"] = True
    st.rerun()


_load_secrets()
demo = load_demo_event("preview")

st.markdown('<div class="ep-kicker">GLOBAL LIVEOPS DECISION SUPPORT</div>', unsafe_allow_html=True)
st.title("게임체인저(Game Changer)")
st.caption(
    "이용자가 실제 게임에서 경험하게 될 출시 예정 변경안을 플레이 과정과 이용 조건에 따라 검토합니다. "
    "현재 프로토타입은 이벤트 사례만 지원하며 흥행이나 매출을 예측하지 않습니다."
)

st.header("1. 이벤트 사례 기획안과 데이터 출처")
with st.form("event-brief"):
    left, right = st.columns(2)
    with left:
        game = st.text_input("게임", demo.game)
        event_name = st.text_input("이벤트명", demo.event_name)
        goal = st.text_area("목표", demo.goal)
        target_users = st.text_input("대상 유저 (쉼표 구분)", ", ".join(demo.target_users))
        starts_on = st.date_input("시작일 (UTC)", demo.starts_at.date())
        ends_on = st.date_input("종료일 (UTC)", demo.ends_at.date())
        cutoff_on = st.date_input("근거 컷오프 (UTC, 해당 일자 미포함)", demo.cutoff_at.date())
    with right:
        participation_rule = st.text_area("참여 조건", demo.participation_rule)
        repeat_rule = st.text_area("반복 조건", demo.repeat_rule)
        rewards = st.text_input("보상 (쉼표 구분)", ", ".join(demo.rewards))
        currencies = st.text_input("재화 (쉼표 구분)", ", ".join(demo.currencies))
        probability = st.text_area("확률·보장 구조", demo.probability_guarantee)
        monetization = st.text_area("과금 정책", demo.monetization_policy)
        expiration = st.text_area("만료 정책", demo.expiration_policy)

    st.divider()
    source_label = st.radio("데이터 경로", list(SOURCE_MODES), horizontal=True, key="source_mode")
    input_mode = SOURCE_MODES[source_label]
    uploaded = None
    steam_app_id = None
    use_x = False
    x_query = "PUBG Black Market"
    x_estimated_total_cost_usd = 0.0
    if input_mode == "live":
        source_left, source_mid = st.columns(2)
        with source_left:
            steam_app_id = st.number_input("Steam app ID", min_value=1, value=578080)
        with source_mid:
            use_x = st.checkbox("X 공식 API")
            x_query = st.text_input("X 검색어", x_query, disabled=not use_x)
            x_estimated_total_cost_usd = st.number_input(
                "예상 프로젝트 조회비 (USD)",
                min_value=0.0,
                max_value=10.0,
                value=1.0,
                disabled=not use_x,
            )
            st.caption("코드 상한과 X Developer Console 지출 상한을 모두 $10로 설정하세요.")
    elif input_mode == "import":
        uploaded = st.file_uploader("승인 URL CSV", type="csv")
        st.caption("Reddit·Threads·Instagram 요약만 허용")
    use_llm = st.toggle(
        "OpenAI 구조화 출력 사용",
        value=False,
        help="끄면 합성 fixture의 결정론적 경로로 실행합니다.",
    )
    submitted = st.form_submit_button("사전검증 실행", type="primary", use_container_width=True)

pipeline_placeholder = st.empty()
rerun_fixture_requested = st.session_state.pop("rerun_fixture_requested", False)

if submitted or rerun_fixture_requested:
    run_id = str(uuid4())
    begin_run(st.session_state, input_mode)
    try:
        event = EventBrief(
            run_id=run_id,
            status=ArtifactStatus.COMPLETE,
            producer=Producer.USER,
            input_refs=[],
            errors=[],
            game=game,
            event_name=event_name,
            goal=goal,
            starts_at=datetime.combine(starts_on, time.min, tzinfo=UTC),
            ends_at=datetime.combine(ends_on, time.min, tzinfo=UTC),
            target_users=_csv_list(target_users),
            participation_rule=participation_rule,
            repeat_rule=repeat_rule,
            rewards=_csv_list(rewards),
            currencies=_csv_list(currencies),
            probability_guarantee=probability,
            monetization_policy=monetization,
            expiration_policy=expiration,
            cutoff_at=datetime.combine(cutoff_on, time.min, tzinfo=UTC),
        )
        options = CollectionOptions(
            use_fixture=input_mode == "fixture",
            imported_csv=uploaded.getvalue() if uploaded else None,
            steam_app_id=int(steam_app_id) if steam_app_id else None,
            use_x=use_x,
            x_query=x_query,
            x_estimated_total_cost_usd=float(x_estimated_total_cost_usd),
        )

        def progress(item: ExecutionEvent) -> None:
            st.session_state["execution_events"].append(item)
            _render_running_pipeline(
                pipeline_placeholder,
                build_pipeline_view(st.session_state["execution_events"], finished=False),
            )

        result = EventPreflightOrchestrator(use_llm=use_llm).run(
            event,
            options,
            on_event=progress,
            log_path=Path(".data/runs") / f"{run_id}.jsonl",
        )
        store_success(st.session_state, result, input_mode=result.feedback.input_mode.value)
        _render_decision(pipeline_placeholder, result)
    except (ValueError, PipelineStopped) as exc:
        message = str(exc)
        store_failure(st.session_state, message)
        events = st.session_state["execution_events"]
        if events:
            _render_running_pipeline(
                pipeline_placeholder,
                build_pipeline_view(events, finished=False, error=message),
            )
    except Exception:
        message = "예상하지 못한 오류로 실행을 중단했습니다."
        store_failure(st.session_state, message)
        events = st.session_state["execution_events"]
        if events:
            _render_running_pipeline(
                pipeline_placeholder,
                build_pipeline_view(events, finished=False, error=message),
            )

result = st.session_state.get("preflight_result")
if result is not None and not (submitted or rerun_fixture_requested):
    _render_decision(pipeline_placeholder, result)

if error := st.session_state.get("preflight_error"):
    st.error(f"실행 중단: {error}")
    st.button("저장 데이터로 다시 실행", type="primary", on_click=_request_fixture_rerun)
