"use client";

import { useMemo } from "react";

import { businessKorean, businessKoreanJson } from "./businessKorean";

export type AgentEvent = {
  sequence: number;
  agent: string;
  node: string;
  state: string;
  message: string;
  metrics: Record<string, string | number | boolean>;
};

type PipelineMode = "event" | "update";
type AgentInfo = {
  label: string;
  contract: string;
  role: string;
};

const agentOrder = [
  "collection",
  "evidence_rag_personas",
  "event_redteam",
  "audit_strategy",
] as const;

const owners: Record<(typeof agentOrder)[number], string> = {
  collection: "정현예",
  evidence_rag_personas: "유주심",
  event_redteam: "정아현",
  audit_strategy: "승진배",
};

const eventAgents: Record<(typeof agentOrder)[number], AgentInfo> = {
  collection: {
    label: "자료 수집 에이전트",
    contract: "FeedbackBundle",
    role: "기준일 이전 자료를 모으고 개인정보를 남기지 않는 요약 자료를 만듭니다.",
  },
  evidence_rag_personas: {
    label: "의견 정리 에이전트",
    contract: "EvidencePack",
    role: "반복 문제를 묶고 언어별 결과와 이용자 유형을 정리합니다.",
  },
  event_redteam: {
    label: "위험 점검 에이전트",
    contract: "RiskAssessment",
    role: "기획안이 실제 이용 과정에서 만들 수 있는 위험과 실패 경로를 점검합니다.",
  },
  audit_strategy: {
    label: "최종 판정 에이전트",
    contract: "ValidatedDecision",
    role: "근거와 기준을 다시 확인해 Go, Revise, Hold 중 하나를 선택하고 개선안을 정리합니다.",
  },
};

const updateAgents: Record<(typeof agentOrder)[number], AgentInfo> = {
  collection: {
    label: "자료 수집 에이전트",
    contract: "UpdateFeedbackBundle",
    role: "기간, 출처, 감정, 비식별 요약을 일관된 업데이트 자료로 정리합니다.",
  },
  evidence_rag_personas: {
    label: "변경 영향 분석 에이전트",
    contract: "UpdateEvidencePack",
    role: "긍정, 부정, 혼합 신호를 이용자 유형과 연결합니다.",
  },
  event_redteam: {
    label: "업데이트 레드팀 에이전트",
    contract: "UpdateImpactAssessment",
    role: "실패 경로와 출시 후 확인 지표를 제안합니다.",
  },
  audit_strategy: {
    label: "검증 및 전략 에이전트",
    contract: "UpdateValidatedDecision",
    role: "근거, 위험, 지표를 검증해 출시 판정을 계산합니다.",
  },
};

const nodeLabels: Record<string, string> = {
  source_selected: "자료 출처 확인",
  corpus_selected: "사전 구축 코퍼스 확인",
  corpus_retrieved: "관련 비식별 근거 검색",
  cutoff_checked: "검토 기준일 확인",
  period_checked: "자료 기간 구분",
  anonymized: "개인정보 보호 처리",
  samples_counted: "언어별 의견 수 집계",
  bundle_ready: "수집 결과 정리",
  deduplicated: "중복 의견 정리",
  signals_grouped: "반응 신호 분류",
  issues_grouped: "반복 문제 분류",
  language_gate_checked: "언어별 자료 충분성 확인",
  personas_linked: "이용자 유형 연결",
  personas_built: "이용자 유형 정리",
  persona_copy_started: "페르소나 문구 재구성",
  persona_copy_checked: "페르소나 중복 확인",
  persona_copy_fallback: "기본 페르소나 문구 사용",
  pack_ready: "의견 분석 결과 정리",
  embedding_ranked: "관련 의견 우선 정렬",
  structured_output_validated: "AI 설명 형식 확인",
  change_reviewed: "변경 전후 점검",
  event_reviewed: "이벤트 조건 점검",
  failure_paths_built: "문제 발생 경로 정리",
  metrics_linked: "확인 지표 연결",
  impact_linked: "영향 이용자 연결",
  risks_graded: "위험 수준 결정",
  assessment_ready: "영향 점검 결과 정리",
  evidence_checked: "근거 존재 확인",
  risks_validated: "위험 기준 검토",
  sample_gate_applied: "자료 충분성 확인",
  decision_fixed: "최종 판정",
  recommendations_built: "실행 권고 정리",
  revisions_built: "개선안 정리",
  brief_ranked: "핵심 위험 우선순위 정리",
  persona_panel_built: "이용자별 영향 정리",
  claude_narrative: "Claude 설명 생성",
  claude_output_checked: "Claude 결과 안전성 확인",
  jelly_sidecar_started: "정아현 위험 점검 실행",
  jelly_output_checked: "정아현 분석 결과 확인",
  jinbae_probe_started: "승진배 근거 검증 실행",
  jinbae_probe_checked: "승진배 인용 결과 확인",
  fallback: "결정론적 안전 경로 전환",
};

const stateLabels: Record<string, string> = {
  waiting: "대기 중",
  running: "처리 중",
  retrying: "재시도 중",
  complete: "완료",
  failed: "확인 필요",
};

const metricLabels: Record<string, string> = {
  evidence: "근거",
  samples: "표본",
  corpus_version: "코퍼스 버전",
  input_mode: "자료 입력 방식",
  remaining: "기준일 통과 근거",
  insufficient: "표본 부족 언어권",
  languages: "언어권",
  visible: "결론 공개 언어권",
  issues: "반복 문제",
  signals: "반응 신호",
  positive: "긍정 신호",
  neutral: "중립 신호",
  negative: "우려 신호",
  risk: "위험 신호",
  mixed: "혼합 신호",
  personas: "이용자 유형",
  risks: "위험",
  linked_risks: "연결된 위험",
  validated: "검증된 위험",
  rejected: "제외된 위험",
  metrics: "확인 지표",
  recommendations: "실행 권고",
  revisions: "수정안",
  decision: "최종 판정",
  analysis_incomplete: "분석 미완료",
  update_type: "업데이트 유형",
  accepted: "사용 근거",
  errors: "오류",
  comparable_reference: "비교 참고 근거",
  metrics_complete: "검증 지표 충족",
  provider: "설명 생성 도구",
  claims: "검증 주장",
  chunks: "검토 근거",
  calls: "호출 횟수",
  verdict: "근거 판정",
};

const metricValueLabels: Record<string, string> = {
  Go: "출시 가능",
  Revise: "수정 후 재검토",
  Test: "테스트 후 출시",
  Hold: "판정 보류",
  claude: "Claude",
  fixture: "검증된 저장 데이터",
  live: "실시간 자료",
  import: "승인 CSV",
  corpus: "사전 구축 코퍼스",
  weapon_balance: "무기 밸런스",
  ui_ux: "UI와 UX",
  system_rules: "시스템 규칙",
  positive: "긍정",
  neutral: "중립",
  negative: "우려",
  risk: "위험",
  grounded: "근거 확인",
  partially_grounded: "일부 근거 확인",
  not_grounded: "근거 부족",
  true: "예",
  false: "아니오",
};

export function AgentPipeline({
  events,
  active = false,
  mode,
}: {
  events: AgentEvent[];
  active?: boolean;
  mode: PipelineMode;
}) {
  const agents = mode === "update" ? updateAgents : eventAgents;
  const groups = useMemo(
    () =>
      agentOrder.map((agent) => {
        const allEvents = events.filter((event) => event.agent === agent);
        const visibleEvents = allEvents.filter(
          (event) => !["queued", "agent"].includes(event.node),
        );
        const failed = allEvents.some((event) => event.state === "failed");
        const complete = allEvents.some(
          (event) => event.node === "agent" && event.state === "complete",
        );
        const running = allEvents.some((event) =>
          ["running", "retrying"].includes(event.state),
        );
        const status = failed
          ? "failed"
          : complete
            ? "complete"
            : running
              ? "running"
              : "waiting";
        const current =
          status === "running"
            ? [...visibleEvents]
                .reverse()
                .find((event) => ["running", "retrying"].includes(event.state))
            : undefined;
        return { agent, events: visibleEvents, status, current };
      }),
    [events],
  );
  const inputCopy = mode === "update" ? "업데이트 변경안 + 자료" : "이벤트 정보 + 자료";
  const outputCopy = mode === "update" ? "출시 전 업데이트 판정" : "최종 검토 결과";
  const activeGroup = groups.find((group) => group.current);
  const activeStatus = activeGroup?.current
    ? `${agents[activeGroup.agent].label}, ${nodeLabels[activeGroup.current.node] ?? "현재 노드"} 처리 중`
    : "에이전트가 순서대로 실행 중입니다";

  return (
    <section className="pipeline">
      <div className="pipeline-head">
        <strong>입력</strong>
        <code>{inputCopy}</code>
        <span>→</span>
        <strong>출력</strong>
        <code>{outputCopy}</code>
        <span
          className={`pipeline-state ${active ? "is-running" : "is-complete"}`}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <i />
          {active ? activeStatus : "실행이 완료되었습니다"}
        </span>
      </div>
      {groups.map(({ agent, events: nodeEvents, status, current }, index) => {
        const info = agents[agent];
        return (
          <div className={`agent-row agent-${status}`} key={agent}>
            <div className="agent-meta">
              <small>단계 {String(index + 1).padStart(2, "0")}</small>
              <h3>{info.label}</h3>
              <span className="agent-status">
                <i />
                {stateLabels[status]}
                {current ? `, ${nodeLabels[current.node] ?? current.node}` : ""}
              </span>
              <p className="agent-owner">담당자: {owners[agent]}</p>
              <p className="agent-contract">출력 형식: {info.contract}</p>
              <p className="agent-role">{info.role}</p>
            </div>
            <div className="nodes">
              {nodeEvents.map((event, nodeIndex) => {
                const isCurrent =
                  status === "running" && current?.sequence === event.sequence;
                const visualState = isCurrent
                  ? "current"
                  : status === "complete" ||
                      Boolean(current && event.sequence < current.sequence)
                    ? "complete"
                    : "waiting";
                return (
                <details
                  className={`node node-${visualState}`}
                  key={`${event.node}-${nodeIndex}`}
                  open={active}
                  aria-current={isCurrent ? "step" : undefined}
                >
                  <summary>
                    <small>노드 {String(nodeIndex + 1).padStart(2, "0")}</small>
                    <strong>{nodeLabels[event.node] ?? event.node}</strong>
                    {isCurrent && (
                      <span className="node-active-badge">
                        <i />지금 작업 중
                      </span>
                    )}
                    {!active && <code>{event.node}</code>}
                    <p>{businessKorean(event.message)}</p>
                  </summary>
                  <div className="node-detail">
                    <p>
                      <b>자연어 설명</b> {businessKorean(event.message)}
                    </p>
                    <p>
                      <b>정의된 값</b>{" "}
                      {Object.entries(event.metrics)
                        .filter(([key]) => metricLabels[key])
                        .map(([key, value]) => `${metricLabels[key]} ${metricValueLabels[String(value)] ?? String(value)}`)
                        .join(", ") || "처리 결과를 확인했습니다."}
                    </p>
                    <p>
                      <b>처리 상태</b>{" "}
                      {stateLabels[
                        visualState === "current" ? "running" : visualState
                      ]}
                    </p>
                    {!active && <pre>{businessKoreanJson(event)}</pre>}
                  </div>
                </details>
                );
              })}
              {nodeEvents.length === 0 && (
                <div className="node-placeholder">
                  <span className={status === "running" ? "spinner" : "status-dot"} />
                  <strong>{status === "running" ? "노드 준비 중" : stateLabels[status]}</strong>
                  <p>
                    {status === "waiting"
                      ? "앞 단계가 끝나면 실행됩니다."
                      : "첫 처리 결과를 기다리는 중입니다."}
                  </p>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
