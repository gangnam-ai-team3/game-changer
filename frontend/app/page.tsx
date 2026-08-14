"use client";

import { ChangeEvent, FormEvent, useState } from "react";

import { AgentEvent, AgentPipeline } from "./components/AgentPipeline";
import { UpdateReview } from "./components/UpdateReview";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const initialForm = {
  game: "PUBG: BATTLEGROUNDS",
  event_name: "Black Market 2025",
  goal: "복귀 Progressive 스킨의 수집 매력을 활용해 이벤트 참여와 유료 전환을 유도하되, 이용자가 목표 보상까지의 비용과 진행 경로를 명확히 이해할 수 있도록 한다.",
  target_users: "복귀 유저, 무·소과금 유저, 스킨 수집 유저, 코어 전투 유저",
  starts_on: "2025-06-11",
  ends_on: "2025-07-22",
  cutoff_on: "2025-06-11",
  participation_rule: "패스 미션, Loot Cache 구매·개봉, Workshop 특별 제작 참여",
  repeat_rule: "일일·주간 미션과 반복 Loot Cache 개봉",
  rewards: "Progressive weapon skin, Chroma, Black Market Token, Prime Parcel",
  currencies: "G-Coin, BP, Black Market Token, Scrap",
  probability_guarantee: "Loot Cache에서 확률 보상을 얻고 일부 Prime Parcel에서 다시 확률 보상을 얻는 2단계 구조. 원하는 스킨까지의 고정 마일스톤은 없음.",
  monetization_policy: "Crafter Pass와 G-Coin Loot Cache 팩을 판매하고 확률형 보너스로 추가 토큰을 제공. 구매·개봉·제작·진행 확인 화면이 분리됨.",
  expiration_policy: "이벤트 종료 뒤 남은 Black Market Token은 교환·환불 없이 삭제",
};

type FormState = typeof initialForm;

const fixturePresets: Record<string, FormState> = {
  black_market_2025: initialForm,
  weekly_supply_2025: {
    game: "PUBG: BATTLEGROUNDS",
    event_name: "Weekly Supply",
    goal: "주간 미션을 완료한 이용자가 획득 가능한 BP와 참여 조건을 명확히 이해하도록 한다.",
    target_users: "모든 이용자, 무·소과금 유저, 주간 플레이 유저",
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
  feedback: { evidence: EventEvidence[] } & Artifact;
  evidence: Artifact;
  risks: Artifact;
  validated: Artifact;
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
const decisionCopy: Record<string, { title: string; description: string }> = {
  Go: { title: "현재 기획안으로 검토 가능", description: "확인된 위험이 기준보다 낮습니다." },
  Revise: { title: "수정 후 다시 검토", description: "이용자 경험을 해칠 수 있는 위험이 확인됐습니다." },
  Hold: { title: "판정 보류", description: "현재 자료만으로는 판단하기 어렵습니다." },
};
const decisionLabels: Record<string, string> = {
  Go: "검토 가능",
  Revise: "수정 필요",
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
      .join(" · ");
  }
  return typeof detail === "string" ? detail : "검토를 실행할 수 없습니다.";
}

function ArtifactDetails({ result }: { result: RunResult }) {
  const artifacts: Array<[string, string, Artifact]> = [
    ["FeedbackBundle", "자료 수집 결과", result.feedback],
    ["EvidencePack", "의견·이용자 유형 결과", result.evidence],
    ["RiskAssessment", "위험 점검 결과", result.risks],
    ["ValidatedDecision", "판정·개선안 결과", result.validated],
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
            <pre>{JSON.stringify(artifact, null, 2)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}

function ResultInsights({ result }: { result: RunResult }) {
  const riskTitle = new Map(result.brief.top_risks.map((risk) => [risk.risk_id, risk.title]));
  return (
    <>
      <section className="insight-section">
        <div className="section-title">
          <h2>이용자 유형별 영향</h2>
          <p>각 이용자 유형이 어떤 위험에 영향을 받는지 근거 수와 함께 보여줍니다.</p>
        </div>
        <div className="insight-grid">
          {result.brief.panel_results.map((panel) => (
            <article className="insight-card" key={panel.persona}>
              <span className="risk-category">{personaLabels[panel.persona] ?? panel.persona}</span>
              <h3>{panel.reaction}</h3>
              <p>
                {panel.risk_ids.length
                  ? `연결된 위험 · ${panel.risk_ids.map((id) => riskTitle.get(id) ?? id).join(" · ")}`
                  : "직접 연결된 상위 위험 없음"}
              </p>
              <small>근거 {panel.evidence_ids.length}개 · 신뢰도 {Math.round(panel.confidence * 100)}%</small>
            </article>
          ))}
        </div>
      </section>
      <section className="insight-section">
        <div className="section-title">
          <h2>언어권별 결과</h2>
          <p>최소 표본을 충족한 언어권만 결론을 공개합니다.</p>
        </div>
        <div className="language-grid">
          {result.brief.language_results.map((item) => (
            <article className={`language-card ${item.conclusion ? "" : "muted"}`} key={item.language}>
              <strong>{languageLabels[item.language] ?? item.language}</strong>
              <p>{item.conclusion ?? item.hidden_reason ?? "표본 기준 미달"}</p>
              <small>
                {item.conclusion
                  ? `근거 ${item.evidence_ids.length}개 · 신뢰도 ${Math.round(item.confidence * 100)}%`
                  : "결론 숨김"}
              </small>
            </article>
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
              <h3>{revision.title}</h3>
              <p>{revision.change}</p>
              <small>성공 기준 · {revision.success_metric}</small>
              <details>
                <summary>연결 위험 보기</summary>
                <p>{revision.addresses_risk_ids.map((id) => riskTitle.get(id) ?? id).join(" · ")}</p>
              </details>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function EventReview() {
  const [form, setForm] = useState<FormState>(initialForm);
  const [sourceMode, setSourceMode] = useState("fixture");
  const [fixtureCase, setFixtureCase] = useState("black_market_2025");
  const [steamAppId, setSteamAppId] = useState("578080");
  const [csvData, setCsvData] = useState("");
  const [csvName, setCsvName] = useState("");
  const [useClaude, setUseClaude] = useState(true);
  const [result, setResult] = useState<RunResult | null>(null);
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const update = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const name = event.target.name as keyof FormState;
    setForm((previous) => ({ ...previous, [name]: event.target.value }) as FormState);
  };

  const handleCsv = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    setCsvData(btoa(binary));
    setCsvName("승인 CSV 선택됨");
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    setLiveEvents([]);
    if (sourceMode === "import" && !csvData) {
      setError("승인 CSV 파일을 선택해 주세요.");
      setLoading(false);
      return;
    }
    try {
      const payload = {
        ...form,
        target_users: form.target_users.split(",").map((item) => item.trim()).filter(Boolean),
        rewards: form.rewards.split(",").map((item) => item.trim()).filter(Boolean),
        currencies: form.currencies.split(",").map((item) => item.trim()).filter(Boolean),
        source_mode: sourceMode,
        fixture_case: fixtureCase,
        steam_app_id: sourceMode === "live" ? Number(steamAppId) : null,
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
    }
  }

  const copy = result ? decisionCopy[result.brief.decision] ?? decisionCopy.Hold : null;

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
          <label className="field">
            <span>자료 출처</span>
            <select value={sourceMode} onChange={(event) => setSourceMode(event.target.value)}>
              <option value="fixture">검증된 저장 데이터 · 시연 사례 선택</option>
              <option value="live">Steam 실시간 갱신</option>
              <option value="import">승인 CSV 가져오기</option>
            </select>
          </label>
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
                <option value="black_market_2025">대규모 확률형 이벤트 · Black Market 2025</option>
                <option value="weekly_supply_2025">단순 주간 미션 · Weekly Supply</option>
              </select>
              <small className="field-help">공식 공개 규칙을 바탕으로 만든 비식별 합성 의견입니다.</small>
            </label>
          )}
          {sourceMode === "live" && (
            <label className="field">
              <span>Steam 앱 ID</span>
              <input value={steamAppId} onChange={(event) => setSteamAppId(event.target.value)} />
            </label>
          )}
          {sourceMode === "import" && (
            <label className="field">
              <span>승인 CSV 파일</span>
              <input type="file" accept=".csv,text/csv" onChange={handleCsv} />
              <small className="field-help">{csvName || "개인정보·원문 열이 없는 승인 CSV만 사용합니다."}</small>
            </label>
          )}
          <label className="toggle">
            <input type="checkbox" checked={useClaude} onChange={(event) => setUseClaude(event.target.checked)} />
            <span>Claude로 자연어 설명 보강</span>
            <small>{useClaude ? "근거·최종 판정은 코드가 다시 검증합니다." : "결정론적 경로만 실행합니다."}</small>
          </label>
          <p className="source-note">
            저장 데이터는 공식 자료를 바탕으로 만든 합성 시연 사례입니다. 이벤트 조건과 근거 자료를 함께 바꿔 비교할 수 있습니다. API 키는 이 화면에 노출하지 않습니다. 분석 설명은 한국어로 제공하고, 근거 원문·비식별 요약은 왜곡을 막기 위해 출처 언어를 유지합니다.
          </p>
          <button className="primary" disabled={loading}>
            {loading ? "검토 중..." : "AI 검토 시작"}
          </button>
          {error && <p className="error">{error}</p>}
        </section>
      </form>

      {loading && (
        <section className="live-panel">
          <div className="section-title">
            <h2>에이전트 실행 중</h2>
            <p>실행을 시작하면 각 에이전트와 노드의 현재 상태가 바로 표시됩니다.</p>
          </div>
          <AgentPipeline events={liveEvents} active mode="event" />
        </section>
      )}

      {result && (
        <section className="results">
          <div className="result-banner">
            <div>
              <p className="eyebrow">검토 결과</p>
              <h2>{copy?.title}</h2>
              <p>{result.brief.executive_summary}</p>
              <small>
                {copy?.description} · {" "}
                {result.llm_requested
                  ? result.fallback_used
                    ? "Claude 요청 후 결정론적 안전 경로로 전환"
                    : "Claude 자연어 분석 사용"
                  : "결정론적 분석 사용"}
                {" · 실행 ID "}
                {String(result.brief.run_id)}
              </small>
            </div>
            <span className="decision">{decisionLabels[result.brief.decision] ?? result.brief.decision}</span>
          </div>
          <div className="stats">
            <div>
              <small>확인된 위험</small>
              <strong>{result.brief.top_risks.length}</strong>
            </div>
            <div>
              <small>확인한 비식별 의견</small>
              <strong>{result.feedback.evidence.length}</strong>
            </div>
            <div>
              <small>처리 노드</small>
              <strong>{result.events.filter((event) => !["queued", "agent"].includes(event.node)).length}</strong>
            </div>
          </div>
          <AgentPipeline events={result.events} mode="event" />
          <div className="risk-section">
            <div className="section-title">
              <h2>확인된 위험</h2>
              <p>위험의 내용을 직접 보여줍니다. 연결된 비식별 의견은 카드를 펼쳐 확인할 수 있습니다.</p>
            </div>
            <div className="risk-grid">
              {result.brief.top_risks.map((risk) => (
                <article className="risk-card" key={risk.risk_id}>
                  <span className="risk-category">{riskLabels[risk.category] ?? risk.category}</span>
                  <h3>{risk.title}</h3>
                  <p>{risk.failure_path}</p>
                  <small>
                    {severityLabels[risk.severity] ?? risk.severity} · 근거 {risk.evidence_ids.length}개 · 신뢰도 {Math.round(risk.confidence * 100)}%
                  </small>
                  <details>
                    <summary>연결된 비식별 의견 보기</summary>
                    <p>개인정보 보호를 위해 사용자 원문은 저장하지 않고 비식별 요약만 제공합니다. 분석 설명은 한국어로 제공하고, 근거 원문·비식별 요약은 출처 언어를 유지합니다.</p>
                    {result.feedback.evidence
                      .filter((item) => risk.evidence_ids.includes(String(item.evidence_id)))
                      .map((item) => (
                        <blockquote key={String(item.evidence_id)}>
                          <b>{String(item.evidence_id)}</b> {String(item.summary)}
                        </blockquote>
                      ))}
                  </details>
                </article>
              ))}
            </div>
          </div>
          <ResultInsights result={result} />
          <ArtifactDetails result={result} />
        </section>
      )}
    </>
  );
}

export default function Home() {
  const [reviewMode, setReviewMode] = useState<"event" | "update">("event");

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
          onClick={() => setReviewMode("event")}
        >
          <strong>이벤트 점검</strong>
          <span>보상·참여·이용 조건을 점검합니다.</span>
        </button>
        <button
          type="button"
          aria-pressed={reviewMode === "update"}
          onClick={() => setReviewMode("update")}
        >
          <strong>업데이트 점검</strong>
          <span>변경안의 예상 반응과 출시 조건을 점검합니다.</span>
        </button>
      </div>
      {reviewMode === "update" ? <UpdateReview /> : <EventReview />}
    </main>
  );
}
