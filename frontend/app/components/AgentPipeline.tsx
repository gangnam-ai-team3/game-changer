"use client";

import { useMemo } from "react";

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
    role: "근거와 기준을 다시 확인해 Go·Revise·Hold와 개선안을 결정합니다.",
  },
};

const updateAgents: Record<(typeof agentOrder)[number], AgentInfo> = {
  collection: {
    label: "자료 수집 에이전트",
    contract: "UpdateFeedbackBundle",
    role: "기간·출처·감정·비식별 요약을 업데이트 자료로 정규화합니다.",
  },
  evidence_rag_personas: {
    label: "변경 영향 분석 에이전트",
    contract: "UpdateEvidencePack",
    role: "긍정·부정·혼합 신호와 이용자 유형을 연결합니다.",
  },
  event_redteam: {
    label: "업데이트 레드팀 에이전트",
    contract: "UpdateImpactAssessment",
    role: "실패 경로와 출시 후 확인 지표를 제안합니다.",
  },
  audit_strategy: {
    label: "검증·전략 에이전트",
    contract: "UpdateValidatedDecision",
    role: "근거·위험·지표를 검증해 출시 판정을 계산합니다.",
  },
};

const nodeLabels: Record<string, string> = {
  source_selected: "자료 출처 확인",
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
  pack_ready: "의견 분석 결과 정리",
  embedding_ranked: "관련 의견 우선 정렬",
  structured_output_validated: "AI 설명 형식 확인",
  change_reviewed: "변경 전·후 점검",
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
  fallback: "결정론적 안전 경로 전환",
};

const stateLabels: Record<string, string> = {
  waiting: "대기 중",
  running: "처리 중",
  retrying: "재시도 중",
  complete: "완료",
  failed: "확인 필요",
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
        const current = [...visibleEvents]
          .reverse()
          .find((event) => ["running", "retrying"].includes(event.state));
        return { agent, events: visibleEvents, status, current };
      }),
    [events],
  );
  const inputCopy = mode === "update" ? "업데이트 변경안 + 자료" : "이벤트 정보 + 자료";
  const outputCopy = mode === "update" ? "출시 전 업데이트 판정" : "최종 검토 결과";

  return (
    <section className="pipeline" aria-live={active ? "polite" : "off"}>
      <div className="pipeline-head">
        <strong>입력</strong>
        <code>{inputCopy}</code>
        <span>→</span>
        <strong>출력</strong>
        <code>{outputCopy}</code>
        <span className={`pipeline-state ${active ? "is-running" : "is-complete"}`}>
          <i />
          {active ? "에이전트가 순서대로 실행 중입니다" : "실행이 완료되었습니다"}
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
                {current ? ` · ${nodeLabels[current.node] ?? current.node}` : ""}
              </span>
              <p className="agent-owner">담당자 · {owners[agent]}</p>
              <p className="agent-contract">출력 형식 · {info.contract}</p>
              <p className="agent-role">{info.role}</p>
            </div>
            <div className="nodes">
              {nodeEvents.map((event, nodeIndex) => (
                <details className="node" key={`${event.node}-${nodeIndex}`}>
                  <summary>
                    <small>노드 {String(nodeIndex + 1).padStart(2, "0")}</small>
                    <strong>{nodeLabels[event.node] ?? event.node}</strong>
                    <code>{event.node}</code>
                    <p>{event.message}</p>
                  </summary>
                  <div className="node-detail">
                    <p>
                      <b>자연어 설명</b> {event.message}
                    </p>
                    <p>
                      <b>정의된 값</b>{" "}
                      {Object.entries(event.metrics)
                        .map(([key, value]) => `${key}=${String(value)}`)
                        .join(", ") || "추가 지표 없음"}
                    </p>
                    <p>
                      <b>처리 상태</b> {stateLabels[event.state] ?? event.state}
                    </p>
                    <pre>{JSON.stringify(event, null, 2)}</pre>
                  </div>
                </details>
              ))}
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
