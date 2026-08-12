from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time
from pathlib import Path
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from agents.collector import CollectionOptions
from contracts import ArtifactStatus, EventBrief, Producer
from evaluation.backtest import evaluate_black_market
from evaluation.fixtures import load_demo_event
from orchestrator import EventPreflightOrchestrator, PipelineStopped

st.set_page_config(page_title="게임체인저(Game Changer)", page_icon="🛡️", layout="wide")
st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2rem;}
    [data-testid="stMetricValue"] {font-size: 2rem;}
    .ep-kicker {color:#64748b; font-weight:700; letter-spacing:.08em; font-size:.78rem;}
    .ep-note {padding:.8rem 1rem; background:#f8fafc; border-left:4px solid #475569; border-radius:.4rem;}
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
    source_mode = st.radio(
        "데이터 경로",
        ["Black Market 합성 fixture", "실연동·승인 CSV"],
        horizontal=True,
    )
    use_fixture = source_mode.startswith("Black Market")
    uploaded = None
    steam_app_id = None
    use_x = False
    x_query = "PUBG Black Market"
    x_estimated_total_cost_usd = 0.0
    if not use_fixture:
        source_left, source_mid, source_right = st.columns(3)
        with source_left:
            steam_enabled = st.checkbox("Steam GetReviews")
            steam_app_id = st.number_input("Steam app ID", min_value=1, value=578080) if steam_enabled else None
        with source_mid:
            use_x = st.checkbox("X 공식 API")
            x_query = st.text_input("X 검색어", x_query, disabled=not use_x)
            x_estimated_total_cost_usd = st.number_input(
                "예상 프로젝트 조회비 (USD)", min_value=0.0, max_value=10.0, value=1.0, disabled=not use_x
            )
            st.caption("코드 상한과 X Developer Console 지출 상한을 모두 $10로 설정하세요.")
        with source_right:
            uploaded = st.file_uploader("승인 URL CSV", type="csv")
            st.caption("Reddit·Threads·Instagram 요약만 허용")
    use_llm = st.toggle("OpenAI 구조화 출력 사용", value=False, help="끄면 합성 fixture의 결정론적 경로로 실행합니다.")
    submitted = st.form_submit_button("사전검증 실행", type="primary", use_container_width=True)

if submitted:
    run_id = str(uuid4())
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
            use_fixture=use_fixture,
            imported_csv=uploaded.getvalue() if uploaded else None,
            steam_app_id=int(steam_app_id) if steam_app_id else None,
            use_x=use_x,
            x_query=x_query,
            x_estimated_total_cost_usd=float(x_estimated_total_cost_usd),
        )
        st.header("2. 수집 → RAG·페르소나 → 레드팀 → 감사")
        with st.status("고정 파이프라인 실행 중", expanded=True) as status:
            def progress(stage: str, state: str, message: str) -> None:
                icons = {"running": "⏳", "complete": "✅", "retrying": "↻", "failed": "❌"}
                st.write(f"{icons[state]} `{stage}` — {message}")

            result = EventPreflightOrchestrator(use_llm=use_llm).run(
                event,
                options,
                on_stage=progress,
                log_path=Path(".data/runs") / f"{run_id}.jsonl",
            )
            status.update(label="사전검증 완료", state="complete", expanded=False)
        st.session_state["preflight_result"] = result
        st.session_state["preflight_event"] = event
    except (ValueError, PipelineStopped) as exc:
        st.error(f"실행 중단: {exc}")

if "preflight_result" in st.session_state:
    result = st.session_state["preflight_result"]
    brief = result.brief
    st.header("3. 의사결정 브리프")
    decision_col, risk_col, evidence_col, language_col = st.columns(4)
    decision_col.metric("판단", brief.decision.value)
    risk_col.metric("상위 위험", len(brief.top_risks))
    evidence_col.metric("비식별 근거", len(brief.evidence))
    visible = sum(item.conclusion is not None for item in brief.language_results)
    language_col.metric("언어권 결론", f"{visible}/5")
    st.markdown(f'<div class="ep-note">{brief.executive_summary}</div>', unsafe_allow_html=True)

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
        ["플레이어 패널", "언어권", "수정 기획안", "근거"]
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
        st.caption("합성 fixture는 실제 커뮤니티 원문이 아니며 `synthetic=true`로 표시됩니다.")
        for item in brief.evidence[:30]:
            st.markdown(
                f"`{item.evidence_id}` · {item.language.value} · "
                f"[출처]({item.source_url}) · synthetic={str(item.synthetic).lower()}  \n{item.summary}"
            )

    if all(item.synthetic for item in brief.evidence):
        st.subheader("데모 전용 백테스트")
        score = evaluate_black_market(brief)
        st.caption("2026 정답지는 위 의사결정 브리프가 완성된 뒤에만 읽습니다. 실제 예측이 아닌 회고형 시뮬레이션입니다.")
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
