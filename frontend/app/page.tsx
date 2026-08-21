"use client";

import { ChangeEvent, FormEvent, useState } from "react";

import { AgentEvent, AgentPipeline } from "./components/AgentPipeline";
import { LanguageGameCard, PersonaGameCard } from "./components/AudienceCards";
import { businessKorean, businessKoreanJson } from "./components/businessKorean";
import { corpusDemoDates, isFutureUtcDate } from "./components/corpusDemoDates";
import { DecisionReport, DecisionReportData } from "./components/DecisionReport";
import { UpdateReview } from "./components/UpdateReview";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const initialForm = {
  game: "PUBG: BATTLEGROUNDS",
  event_name: "Black Market 2025",
  goal: "복귀 Progressive 스킨의 수집 매력을 활용해 이벤트 참여와 유료 전환을 유도하되, 이용자가 목표 보상까지의 비용과 진행 경로를 명확히 이해할 수 있도록 한다.",
  target_users: "복귀 이용자, 무과금 및 소과금 이용자, 스킨 수집 이용자, 전투 중심 이용자",
  starts_on: "2025-06-11",
  ends_on: "2025-07-22",
  cutoff_on: "2025-06-11",
  participation_rule: "패스 미션, Loot Cache 구매와 개봉, Workshop 특별 제작 참여",
  repeat_rule: "일일 및 주간 미션과 반복 Loot Cache 개봉",
  rewards: "Progressive weapon skin, Chroma, Black Market Token, Prime Parcel",
  currencies: "G-Coin, BP, Black Market Token, Scrap",
  probability_guarantee: "Loot Cache에서 확률 보상을 얻고 일부 Prime Parcel에서 다시 확률 보상을 얻는 2단계 구조. 원하는 스킨까지의 고정 마일스톤은 없음.",
  monetization_policy: "Crafter Pass와 G-Coin Loot Cache 팩을 판매하고 확률형 보너스로 추가 토큰을 제공합니다. 구매, 개봉, 제작, 진행 확인 화면은 분리되어 있습니다.",
  expiration_policy: "이벤트 종료 뒤 남은 Black Market Token은 교환이나 환불 없이 삭제",
};

type FormState = typeof initialForm;
type SourceMode = "fixture" | "corpus" | "live" | "import";

const fixturePresets: Record<string, FormState> = {
  black_market_2025: initialForm,
  weekly_supply_2025: {
    game: "PUBG: BATTLEGROUNDS",
    event_name: "Weekly Supply",
    goal: "주간 미션을 완료한 이용자가 획득 가능한 BP와 참여 조건을 명확히 이해하도록 한다.",
    target_users: "모든 이용자, 무과금 및 소과금 이용자, 주간 플레이 이용자",
    starts_on: "2025-06-11",
    ends_on: "2025-07-09",
    cutoff_on: "2025-06-11",
    participation_rule: "주간 미션을 완료하고 포인트를 BP로 교환",
    repeat_rule: "매주 수요일 UTC 02:00 초기화, 미션과 보상은 주 1회 수령",
    rewards: "최대 23,000 BP",
    currencies: "BP, 주간 미션 포인트",
    probability_guarantee: "확률 없음. 미션 완료 포인트를 정해진 BP 보상으로 교환",
    monetization_policy: "유료 구매 없음. 게임 플레이로 참여",
    expiration_policy: "주간 초기화 전에 해당 주의 미션과 보상을 직접 수령",
  },
};

type Risk = {
  risk_id: string;
  category: string;
  title: string;
  severity: string;
  evidence_ids: string[];
  failure_path: string;
  confidence: number;
};
type Artifact = Record<string, unknown>;
type LanguageResult = {
  language: string;
  conclusion: string | null;
  hidden_reason?: string | null;
  evidence_ids: string[];
  confidence: number;
};
type PersonaPanel = {
  persona: string;
  reaction: string;
  risk_ids: string[];
  evidence_ids: string[];
  confidence: number;
};
type Revision = {
  priority: number;
  title: string;
  change: string;
  success_metric: string;
  addresses_risk_ids: string[];
};
type EventEvidence = { evidence_id: string; summary: string } & Record<string, unknown>;
type RunResult = {
  brief: {
    run_id: string;
    decision: string;
    executive_summary: string;
    top_risks: Risk[];
    panel_results: PersonaPanel[];
    language_results: LanguageResult[];
    revision_plan: Revision[];
  } & Artifact;
  feedback: { evidence: EventEvidence[]; input_mode?: string } & Artifact;
  evidence: Artifact;
  risks: Artifact;
  validated: { decision_reason: string } & Artifact;
  events: AgentEvent[];
  fallback_used: boolean;
  analysis_incomplete: boolean;
  llm_provider: string;
  llm_requested: boolean;
};

const riskLabels: Record<string, string> = {
  double_gacha: "확률이 두 번 적용되는 구조",
  fragmented_flow: "진행 과정이 여러 화면으로 나뉨",
  opaque_progress: "목표까지 남은 진행량이 보이지 않음",
  random_bonus: "같은 지출인데 진행량이 달라짐",
  expiring_currency: "이벤트 종료 후 재화가 사라짐",
};
const personaLabels: Record<string, string> = {
  time_constrained_casual_returning: "시간이 부족한 복귀 이용자",
  value_seeking_free_low_spend: "가성비를 중시하는 이용자",
  collector_high_engagement: "수집을 즐기는 이용자",
  core_combat_first: "전투 경험을 우선하는 이용자",
};
const languageLabels: Record<string, string> = {
  en: "영어권",
  ko: "한국어권",
  "zh-CN": "중국어권",
  es: "스페인어권",
  "pt-BR": "포르투갈어권",
};
const severityLabels: Record<string, string> = {
  Low: "낮음",
  Medium: "보통",
  High: "높음",
  Critical: "매우 높음",
};
const decisionLabels: Record<string, string> = {
  Go: "출시 가능",
  Revise: "수정 후 재검토",
  Hold: "판정 보류",
};

function EventField({
  label,
  name,
  value,
  onChange,
  multiline = false,
  type = "text",
}: {
  label: string;
  name: keyof FormState;
  value: string;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  multiline?: boolean;
  type?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {multiline ? (
        <textarea name={name} value={value} onChange={onChange} />
      ) : (
        <input name={name} type={type} value={value} onChange={onChange} />
      )}
    </label>
  );
}

function formatApiError(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item),
      )
      .join(", ");
  }
  return typeof detail === "string" ? detail : "검토를 실행할 수 없습니다.";
}

function ArtifactDetails({ result }: { result: RunResult }) {
  const artifacts: Array<[string, string, Artifact]> = [
    ["FeedbackBundle", "자료 수집 결과", result.feedback],
    ["EvidencePack", "의견 및 이용자 유형 결과", result.evidence],
    ["RiskAssessment", "위험 점검 결과", result.risks],
    ["ValidatedDecision", "판정 및 개선안 결과", result.validated],
    ["DecisionBrief", "발표용 최종 요약", result.brief],
  ];
  return (
    <section className="artifact-section">
      <div className="section-title">
        <h2>에이전트 산출물</h2>
        <p>카드를 펼치면 정의된 값과 결과를 JSON으로 확인할 수 있습니다.</p>
      </div>
      <div className="artifact-grid">
        {artifacts.map(([contract, label, artifact]) => (
          <details className="artifact-detail" key={contract}>
            <summary>
              <span>{label}</span>
              <code>{contract}</code>
            </summary>
            <pre>{businessKoreanJson(artifact)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}

const inputModeLabels: Record<string, string> = {
  fixture: "검증된 저장 자료",
  corpus: "사전 구축 코퍼스",
  live: "실시간 공개 자료",
  import: "승인 CSV",
};

function uniqueEvidenceCount(ids: string[]) {
  return new Set(ids).size;
}

function expectedAction(value: string) {
  const marker = "예상 행동:";
  const index = value.indexOf(marker);
  return index >= 0 ? businessKorean(value.slice(index + marker.length).trim()) : "";
}

function opinionKey(value: string) {
  const opinion = value.split("예상 행동:")[0].replace("예상 대표 의견:", "");
  return businessKorean(opinion).replace(/[\p{P}\s]/gu, "");
}

function comparePanels(left: PersonaPanel, right: PersonaPanel) {
  return (
    uniqueEvidenceCount(right.evidence_ids) - uniqueEvidenceCount(left.evidence_ids)
    || right.confidence - left.confidence
    || left.persona.localeCompare(right.persona)
  );
}

function selectEventPanel(result: RunResult) {
  const primaryRiskId = result.brief.top_risks[0]?.risk_id;
  return result.brief.panel_results
    .filter((panel) => panel.evidence_ids.length > 0)
    .slice()
    .sort((left, right) => {
      const leftTier = primaryRiskId && left.risk_ids.includes(primaryRiskId) ? 0 : left.risk_ids.length ? 1 : 2;
      const rightTier = primaryRiskId && right.risk_ids.includes(primaryRiskId) ? 0 : right.risk_ids.length ? 1 : 2;
      return leftTier - rightTier || comparePanels(left, right);
    })[0];
}

function findEventRevision(revisions: Revision[], riskId?: string) {
  if (!riskId) return undefined;
  return revisions
    .filter((revision) => revision.addresses_risk_ids.includes(riskId))
    .slice()
    .sort((left, right) => left.priority - right.priority)[0];
}

function visibleEventOpinions(panels: PersonaPanel[]) {
  const seen = new Set<string>();
  const visible = new Set<string>();
  panels.slice().sort(comparePanels).forEach((panel) => {
    const key = opinionKey(panel.reaction);
    if (key && !seen.has(key)) {
      seen.add(key);
      visible.add(panel.persona);
    }
  });
  return visible;
}

function buildEventReport(result: RunResult, subject: string): DecisionReportData {
  const primaryRisk = result.brief.top_risks[0];
  const panel = selectEventPanel(result);
  const revision = findEventRevision(result.brief.revision_plan, primaryRisk?.risk_id);
  const modeLabel = result.feedback.input_mode ? inputModeLabels[result.feedback.input_mode] : undefined;
  const evidenceCount = new Set(result.feedback.evidence.map((item) => item.evidence_id)).size;
  const languageCount = result.brief.language_results.filter((item) => item.conclusion).length;
  const panelRisk = primaryRisk && panel?.risk_ids.includes(primaryRisk.risk_id)
    ? primaryRisk.title
    : panel?.risk_ids.map((id) => result.brief.top_risks.find((risk) => risk.risk_id === id)?.title).find(Boolean);
  const action = panel ? expectedAction(panel.reaction) : "";

  return {
    subject,
    decision: result.brief.decision,
    decisionLabel: decisionLabels[result.brief.decision] ?? "판정 확인 필요",
    conclusion: businessKorean([
      result.validated.decision_reason,
      revision ? `우선 조치는 ‘${revision.title}’입니다.` : "",
    ].filter(Boolean).join(" ")),
    fullReasoning: businessKorean(result.brief.executive_summary),
    sourceScope: [
      `고유 근거 ${evidenceCount}건`,
      `결론 공개 언어권 ${languageCount}개`,
      modeLabel,
    ].filter(Boolean).join(", "),
    analysisIncomplete: result.analysis_incomplete,
    expectedCard: {
      label: "영향이 큰 이용자 반응",
      title: panel ? personaLabels[panel.persona] ?? "이용자 유형 확인 필요" : "대표 반응 선정 어려움",
      body: panel
        ? businessKorean([panelRisk ? `연결된 위험은 ${panelRisk}입니다.` : "직접 연결된 우선 위험이 없습니다.", action].filter(Boolean).join(" "))
        : "현재 근거만으로 대표 반응을 선정하기 어렵습니다.",
      meta: panel ? `고유 근거 ${uniqueEvidenceCount(panel.evidence_ids)}건` : undefined,
    },
    riskCard: {
      label: "가장 큰 위험",
      title: businessKorean(primaryRisk?.title ?? "우선 위험이 확인되지 않았습니다"),
      body: businessKorean(primaryRisk?.failure_path ?? "현재 검증 범위에서 우선 위험이 확인되지 않았습니다."),
      meta: primaryRisk ? `${severityLabels[primaryRisk.severity] ?? "수준 확인 필요"}, 고유 근거 ${uniqueEvidenceCount(primaryRisk.evidence_ids)}건` : undefined,
    },
    actionCard: {
      label: "출시 전 조치",
      title: businessKorean(revision?.title ?? "연결된 출시 전 조치를 확인할 수 없습니다"),
      body: businessKorean(revision?.change ?? "위험과 연결된 개선안을 상세 근거에서 확인해 주세요."),
      meta: revision ? `확인 기준: ${businessKorean(revision.success_metric)}` : "확인 기준이 연결되지 않았습니다",
    },
    riskRows: result.brief.top_risks.slice(0, 3).map((risk) => {
      const linked = findEventRevision(result.brief.revision_plan, risk.risk_id);
      return {
        id: risk.risk_id,
        risk: businessKorean(risk.title),
        level: severityLabels[risk.severity] ?? "확인 필요",
        impact: businessKorean(risk.failure_path),
        action: businessKorean(linked?.change ?? "연결된 출시 전 조치를 확인할 수 없습니다"),
        check: businessKorean(linked?.success_metric ?? "확인 기준이 연결되지 않았습니다"),
      };
    }),
  };
}

function EventReactionDetails({ result }: { result: RunResult }) {
  const riskTitle = new Map(result.brief.top_risks.map((risk) => [risk.risk_id, risk.title]));
  const visibleOpinions = visibleEventOpinions(result.brief.panel_results);
  return (
    <section className="insight-section">
      <div className="section-title">
        <h3>이용자 유형별 예상 반응</h3>
        <p>예상 행동과 연결된 위험, 근거 수를 이용자 유형별로 확인합니다.</p>
      </div>
      <div className="audience-card-grid">
        {result.brief.panel_results.map((panel) => (
          <PersonaGameCard
            key={panel.persona}
            persona={panel.persona}
            label={personaLabels[panel.persona] ?? panel.persona}
            reaction={panel.reaction}
            evidenceCount={uniqueEvidenceCount(panel.evidence_ids)}
            confidence={panel.confidence}
            opinionVisible={visibleOpinions.has(panel.persona)}
            context={panel.risk_ids.length
              ? `연결된 우려: ${panel.risk_ids.map((id) => businessKorean(riskTitle.get(id) ?? "관련 위험")).join(", ")}`
              : "직접 연결된 우려 없음"}
          />
        ))}
      </div>
    </section>
  );
}

function EventEvidenceDetails({ result }: { result: RunResult }) {
  const riskTitle = new Map(result.brief.top_risks.map((risk) => [risk.risk_id, risk.title]));
  return (
    <>
      <div className="risk-section">
        <div className="section-title">
          <h2>확인된 위험</h2>
          <p>연결 근거는 비식별 요약이며, 이용자의 직접 인용이 아닙니다.</p>
        </div>
        <div className="risk-grid">
          {result.brief.top_risks.map((risk) => (
            <article className="risk-card" key={risk.risk_id}>
              <span className="risk-category">{riskLabels[risk.category] ?? risk.category}</span>
              <h3>{businessKorean(risk.title)}</h3>
              <p>{businessKorean(risk.failure_path)}</p>
              <small>
                위험 수준 {severityLabels[risk.severity] ?? risk.severity}, 근거 {risk.evidence_ids.length}건, 신뢰도 {Math.round(risk.confidence * 100)}%
              </small>
              <details>
                <summary>연결된 파생 요약 보기</summary>
                <p>아래 내용은 비식별 요약입니다. 이용자의 문장을 직접 인용한 내용이 아니며, 원문은 저장하거나 표시하지 않습니다.</p>
                {result.feedback.evidence
                  .filter((item) => risk.evidence_ids.includes(String(item.evidence_id)))
                  .map((item) => (
                    <div className="derived-evidence" key={String(item.evidence_id)}>
                      <b>{String(item.evidence_id)}</b> {businessKorean(item.summary)}
                    </div>
                  ))}
              </details>
            </article>
          ))}
        </div>
      </div>
      <section className="insight-section">
        <div className="section-title">
          <h2>언어권별 예상</h2>
          <p>최소 표본을 충족한 언어권만 결론을 공개합니다.</p>
        </div>
        <div className="audience-card-grid">
          {result.brief.language_results.map((item) => (
            <LanguageGameCard
              key={item.language}
              language={item.language}
              label={languageLabels[item.language] ?? item.language}
              conclusion={item.conclusion}
              hiddenReason={item.hidden_reason}
              evidenceCount={item.evidence_ids.length}
              confidence={item.confidence}
            />
          ))}
        </div>
      </section>
      <section className="insight-section">
        <div className="section-title">
          <h2>우선 개선안</h2>
          <p>최종 판정에 연결된 위험을 해결하기 위한 순서입니다.</p>
        </div>
        <div className="revision-grid">
          {result.brief.revision_plan.map((revision) => (
            <article className="revision-card" key={revision.priority}>
              <span>우선순위 {revision.priority}</span>
              <h3>{businessKorean(revision.title)}</h3>
              <p>{businessKorean(revision.change)}</p>
              <small>성공 기준: {businessKorean(revision.success_metric)}</small>
              <details>
                <summary>연결 위험 보기</summary>
                <p>{revision.addresses_risk_ids.map((id) => businessKorean(riskTitle.get(id) ?? id)).join(", ")}</p>
              </details>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function EventReview({
  runBlocked = false,
  onRunningChange,
}: {
  runBlocked?: boolean;
  onRunningChange?: (running: boolean) => void;
}) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [sourceMode, setSourceMode] = useState<SourceMode>("fixture");
  const [fixtureCase, setFixtureCase] = useState("black_market_2025");
  const [steamAppId, setSteamAppId] = useState("578080");
  const [useSteam, setUseSteam] = useState(true);
  const [useX, setUseX] = useState(false);
  const [xQuery, setXQuery] = useState("PUBG Black Market");
  const [csvData, setCsvData] = useState("");
  const [csvName, setCsvName] = useState("");
  const [useClaude, setUseClaude] = useState(true);
  const [result, setResult] = useState<RunResult | null>(null);
  const [submittedSubject, setSubmittedSubject] = useState(initialForm.event_name);
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const update = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const name = event.target.name as keyof FormState;
    setForm((previous) => ({ ...previous, [name]: event.target.value }) as FormState);
  };

  const selectSourceMode = (next: SourceMode) => {
    setSourceMode(next);
    setError("");
  };

  const applyCorpusDemoDates = () => {
    const dates = corpusDemoDates();
    setForm((previous) => ({
      ...previous,
      cutoff_on: dates.cutoffOn,
      starts_on: dates.startsOn,
      ends_on: dates.endsOn,
    }));
    setError("");
  };

  const handleCsv = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2_000_000) {
      setCsvData("");
      setCsvName("");
      setError("승인 CSV는 2 MB 이하만 사용할 수 있습니다.");
      return;
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    setCsvData(btoa(binary));
    setCsvName("승인 CSV 선택됨");
    setError("");
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (runBlocked) {
      setError("다른 점검이 실행 중입니다. 완료된 뒤 시작해 주세요.");
      return;
    }
    if (!form.cutoff_on || !form.starts_on || !form.ends_on) {
      setError("자료 기준일, 이벤트 시작일과 종료일을 모두 입력해 주세요.");
      return;
    }
    if (form.cutoff_on > form.starts_on) {
      setError("자료 기준일은 이벤트 시작일과 같거나 앞선 날짜로 설정해 주세요.");
      return;
    }
    if (form.starts_on >= form.ends_on) {
      setError("이벤트 종료일은 시작일 이후로 설정해 주세요.");
      return;
    }
    if (sourceMode === "corpus" && !isFutureUtcDate(form.cutoff_on)) {
      setError("사전 구축 코퍼스를 사용하려면 자료 기준일을 오늘(UTC)보다 뒤로 설정해 주세요.");
      return;
    }
    if (sourceMode === "import" && !csvData) {
      setError("승인 CSV 파일을 선택해 주세요.");
      return;
    }
    if (sourceMode === "live" && !useSteam && !useX) {
      setError("Steam 또는 X 중 하나 이상을 선택해 주세요.");
      return;
    }
    if (sourceMode === "live" && useSteam && (!steamAppId || Number(steamAppId) < 1)) {
      setError("올바른 Steam 앱 ID를 입력해 주세요.");
      return;
    }
    if (sourceMode === "live" && useX && !xQuery.trim()) {
      setError("X 검색어를 입력해 주세요.");
      return;
    }
    const requestSubject = form.event_name.trim() || "이름 없는 이벤트";
    setLoading(true);
    onRunningChange?.(true);
    setError("");
    setResult(null);
    setLiveEvents([]);
    try {
      const payload = {
        ...form,
        target_users: form.target_users.split(",").map((item) => item.trim()).filter(Boolean),
        rewards: form.rewards.split(",").map((item) => item.trim()).filter(Boolean),
        currencies: form.currencies.split(",").map((item) => item.trim()).filter(Boolean),
        source_mode: sourceMode,
        fixture_case: fixtureCase,
        steam_app_id: sourceMode === "live" && useSteam ? Number(steamAppId) : null,
        use_x: sourceMode === "live" ? useX : false,
        x_query: xQuery.trim() || "PUBG Black Market",
        imported_csv: sourceMode === "import" ? csvData : null,
        use_llm: useClaude,
        llm_provider: "claude",
      };
      const response = await fetch(`${API_URL}/api/runs/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(payload),
      });
      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({}));
        throw new Error(formatApiError(body.detail));
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const eventName = frame.match(/^event: (.+)$/m)?.[1];
          const data = frame.match(/^data: (.+)$/m)?.[1];
          if (!eventName || !data) continue;
          const message = JSON.parse(data) as { event?: AgentEvent; result?: RunResult; detail?: unknown };
          if (eventName === "agent_event" && message.event) {
            setLiveEvents((previous) => [...previous, message.event as AgentEvent]);
          }
          if (eventName === "result" && message.result) {
            setSubmittedSubject(requestSubject);
            setResult(message.result);
            setLiveEvents(message.result.events);
          }
          if (eventName === "error") throw new Error(formatApiError(message.detail));
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "검토를 실행할 수 없습니다.");
    } finally {
      setLoading(false);
      onRunningChange?.(false);
    }
  }

  return (
    <>
      <form onSubmit={submit}>
        <section className="form-card">
          <header>
            <span>01</span>
            <div>
              <h2>이벤트 기본 정보</h2>
              <p>무엇을, 누구에게, 왜 운영하는 이벤트인지 입력합니다.</p>
            </div>
          </header>
          <div className="grid two">
            <EventField label="게임" name="game" value={form.game} onChange={update} />
            <EventField label="이벤트명" name="event_name" value={form.event_name} onChange={update} />
          </div>
          <EventField label="목표" name="goal" value={form.goal} onChange={update} multiline />
          <EventField label="대상 이용자" name="target_users" value={form.target_users} onChange={update} />
        </section>
        <section className="form-card">
          <header>
            <span>02</span>
            <div>
              <h2>일정과 참여 방식</h2>
              <p>이벤트 기간과 이용자가 참여하는 방법을 정리합니다.</p>
            </div>
          </header>
          <div className="grid two">
            <EventField label="시작일 (UTC)" name="starts_on" type="date" value={form.starts_on} onChange={update} />
            <EventField label="종료일 (UTC)" name="ends_on" type="date" value={form.ends_on} onChange={update} />
            <EventField label="자료 기준일 (UTC)" name="cutoff_on" value={form.cutoff_on} onChange={update} type="date" />
            <EventField label="참여 조건" name="participation_rule" value={form.participation_rule} onChange={update} multiline />
            <EventField label="반복 조건" name="repeat_rule" value={form.repeat_rule} onChange={update} multiline />
          </div>
        </section>
        <section className="form-card">
          <header>
            <span>03</span>
            <div>
              <h2>보상과 이용 조건</h2>
              <p>보상, 재화, 확률, 결제와 종료 후 처리 방식을 정리합니다.</p>
            </div>
          </header>
          <div className="grid two">
            <EventField label="보상" name="rewards" value={form.rewards} onChange={update} />
            <EventField label="재화" name="currencies" value={form.currencies} onChange={update} />
            <EventField label="확률과 보장 방식" name="probability_guarantee" value={form.probability_guarantee} onChange={update} multiline />
            <EventField label="유료 이용 방식" name="monetization_policy" value={form.monetization_policy} onChange={update} multiline />
            <EventField label="이벤트 종료 후 처리" name="expiration_policy" value={form.expiration_policy} onChange={update} multiline />
          </div>
        </section>
        <section className="form-card options">
          <header>
            <span>04</span>
            <div>
              <h2>자료 출처와 실행</h2>
              <p>저장 자료로 안정적으로 시연하고, 필요할 때 실시간 자료를 선택합니다.</p>
            </div>
          </header>
          <div className="source-mode-grid" role="group" aria-label="이벤트 자료 출처">
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "fixture"}
              onClick={() => selectSourceMode("fixture")}
            >
              <strong>검증된 저장 데이터</strong>
              <span>공식 공개 규칙을 바탕으로 만든 합성 사례로 안정적으로 시연합니다.</span>
            </button>
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "corpus"}
              onClick={() => selectSourceMode("corpus")}
            >
              <strong>사전 구축 Steam 코퍼스</strong>
              <span>한국어와 영어 리뷰에서 파생한 비식별 요약을 미리 분류해 관련 근거를 찾습니다. 리뷰 원문은 포함하지 않습니다.</span>
            </button>
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "live"}
              onClick={() => selectSourceMode("live")}
            >
              <strong>Steam과 X 실시간 갱신</strong>
              <span>Steam만, X만, 또는 두 자료를 함께 수집합니다.</span>
            </button>
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "import"}
              onClick={() => selectSourceMode("import")}
            >
              <strong>승인 CSV 가져오기</strong>
              <span>개인정보와 원문 열이 없는 승인된 CSV만 사용합니다.</span>
            </button>
          </div>
          {sourceMode === "fixture" && (
            <label className="field">
              <span>시연 사례</span>
              <select
                value={fixtureCase}
                onChange={(event) => {
                  const next = event.target.value;
                  setFixtureCase(next);
                  setForm(fixturePresets[next]);
                  setResult(null);
                  setError("");
                }}
              >
                <option value="black_market_2025">대규모 확률형 이벤트: Black Market 2025</option>
                <option value="weekly_supply_2025">단순 주간 미션: Weekly Supply</option>
              </select>
              <small className="field-help">공식 공개 규칙을 바탕으로 만든 비식별 합성 의견입니다.</small>
            </label>
          )}
          {sourceMode === "corpus" && (
            <div className="source-note corpus-note">
              <p>자료 기준일은 내일(UTC), 검토 대상 시작일은 그다음 날로 설정합니다. 코퍼스에는 한국어와 영어 비식별 요약과 분류값만 저장되며, 리뷰 원문은 포함하지 않습니다.</p>
              <button type="button" className="corpus-date-action" onClick={applyCorpusDemoDates}>
                코퍼스 데모 날짜 적용
              </button>
            </div>
          )}
          {sourceMode === "live" && (
            <div className="source-fields">
              <div className="grid two" role="group" aria-label="실시간 자료 선택">
                <label className="toggle source-toggle">
                  <input
                    type="checkbox"
                    checked={useSteam}
                    onChange={(event) => setUseSteam(event.target.checked)}
                  />
                  <span>Steam 공개 리뷰 수집</span>
                  <small>선택하면 입력한 앱 ID의 공개 리뷰를 확인합니다.</small>
                </label>
                <label className="toggle source-toggle">
                  <input
                    type="checkbox"
                    checked={useX}
                    onChange={(event) => setUseX(event.target.checked)}
                  />
                  <span>X 공개 게시물 수집</span>
                  <small>선택하면 서버에 설정된 X API 연결을 사용합니다.</small>
                </label>
              </div>
              <div className="grid two source-fields">
                {useSteam && (
                  <label className="field">
                    <span>Steam 앱 ID</span>
                    <input
                      inputMode="numeric"
                      value={steamAppId}
                      onChange={(event) => setSteamAppId(event.target.value)}
                    />
                  </label>
                )}
                {useX && (
                  <label className="field">
                    <span>X 검색어</span>
                    <input value={xQuery} onChange={(event) => setXQuery(event.target.value)} />
                  </label>
                )}
              </div>
              <p className="source-note">
                Steam만, X만, 또는 두 자료를 함께 선택할 수 있습니다. 비밀 키는 서버 환경 변수에서만 읽습니다.
              </p>
            </div>
          )}
          {sourceMode === "import" && (
            <label className="field">
              <span>승인 CSV 파일</span>
              <input type="file" accept=".csv,text/csv" onChange={handleCsv} />
              <small className="field-help">{csvName || "개인정보와 원문 열이 없는 승인 CSV만 사용합니다."}</small>
            </label>
          )}
          <label className="toggle">
            <input type="checkbox" checked={useClaude} onChange={(event) => setUseClaude(event.target.checked)} />
            <span>{sourceMode === "corpus" ? "팀 에이전트로 추가 검증" : "Claude로 설명 보강"}</span>
            <small>{sourceMode === "corpus"
              ? useClaude
                ? "정아현(Jelly) 위험 점검과 승진배 근거 검증 에이전트를 Claude로 실행합니다."
                : "저장된 코퍼스와 코드 정책만 사용하며 두 에이전트의 Claude 호출은 생략합니다."
              : useClaude
                ? "근거 연결과 최종 판정은 코드 정책으로 다시 검증합니다."
                : "코드 정책만으로 점검합니다."}</small>
          </label>
          <p className="prelaunch-notice">
            출시 전 예상이며 실제 이용자 반응이나 출시 후 성과를 의미하지 않습니다.
            {sourceMode === "fixture" && " 저장 자료는 공식 공개 규칙을 바탕으로 만든 합성 시연 사례입니다."}
            {" "}API 키와 자료 원문은 화면에 표시하거나 저장하지 않습니다.
          </p>
          <button className="primary" disabled={loading || runBlocked}>
            {loading ? "이벤트 점검 중..." : runBlocked ? "다른 점검 실행 중" : "이벤트 점검 시작"}
          </button>
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      </form>

      {loading && (
        <section className="live-panel">
          <div className="section-title">
            <h2>에이전트 실행 중</h2>
            <p>서버에서 받는 즉시 각 에이전트와 노드의 상태를 표시합니다.</p>
          </div>
          <AgentPipeline events={liveEvents} active mode="event" />
        </section>
      )}

      {result && (() => {
        const report = buildEventReport(result, submittedSubject);
        return (
          <DecisionReport
            {...report}
            reactionDetails={<EventReactionDetails result={result} />}
            evidenceDetails={<EventEvidenceDetails result={result} />}
            agentDetails={(
              <>
                <AgentPipeline events={result.events} mode="event" />
                <ArtifactDetails result={result} />
              </>
            )}
          />
        );
      })()}
    </>
  );
}

export default function Home() {
  const [reviewMode, setReviewMode] = useState<"event" | "update">("event");
  const [runningMode, setRunningMode] = useState<"event" | "update" | null>(null);
  const updateRunningMode = (mode: "event" | "update", running: boolean) => {
    setRunningMode((current) => running ? mode : current === mode ? null : current);
  };

  return (
    <main className="shell">
      <p className="eyebrow">
        <i /> {reviewMode === "event" ? "게임체인저 / 글로벌 이벤트 사전 검토" : "게임체인저 / 출시 전 업데이트 점검"}
      </p>
      <h1>게임체인저</h1>
      <p className="lead">
        {reviewMode === "event"
          ? "출시 예정인 게임 이벤트를 이용자 경험과 이용 조건의 관점에서 점검합니다."
          : "출시 예정인 게임 업데이트의 예상 반응과 검증 조건을 출시 전에 점검합니다."}
      </p>
      <div className="mode-switch" role="group" aria-label="검토 대상">
        <button
          type="button"
          aria-pressed={reviewMode === "event"}
          aria-controls="event-review-panel"
          onClick={() => setReviewMode("event")}
        >
          <strong>이벤트 점검</strong>
          <span>{runningMode === "event" ? "현재 이벤트 점검을 실행 중입니다." : "보상, 참여, 이용 조건을 점검합니다."}</span>
        </button>
        <button
          type="button"
          aria-pressed={reviewMode === "update"}
          aria-controls="update-review-panel"
          onClick={() => setReviewMode("update")}
        >
          <strong>업데이트 점검</strong>
          <span>{runningMode === "update" ? "현재 업데이트 점검을 실행 중입니다." : "변경안의 예상 반응과 출시 조건을 점검합니다."}</span>
        </button>
      </div>
      <div id="event-review-panel" hidden={reviewMode !== "event"}>
        <EventReview
          runBlocked={runningMode === "update"}
          onRunningChange={(running) => updateRunningMode("event", running)}
        />
      </div>
      <div id="update-review-panel" hidden={reviewMode !== "update"}>
        <UpdateReview
          runBlocked={runningMode === "event"}
          onRunningChange={(running) => updateRunningMode("update", running)}
        />
      </div>
    </main>
  );
}
