"use client";

import { ChangeEvent, FormEvent, useState } from "react";

import { AgentEvent, AgentPipeline } from "./AgentPipeline";
import { businessKorean, businessKoreanJson } from "./businessKorean";
import { utcWallClockToIso } from "./utcWallClock";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type UpdateType = "weapon_balance" | "ui_ux" | "system_rules";
type SourceMode = "fixture" | "live" | "import";

type Evidence = {
  evidence_id: string;
  source: string;
  source_url: string;
  language: string;
  observed_at: string;
  period: string;
  sentiment: string;
  summary: string;
  mechanism_tags: string[];
  relevance: number;
  synthetic: boolean;
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

type Metric = {
  metric_id: string;
  title: string;
  measurement: string;
  success_condition: string;
  addresses_risk_ids: string[];
};

type Impact = {
  impact_id: string;
  title: string;
  summary: string;
  affected_personas: string[];
  evidence_ids: string[];
  confidence: number;
};

type LanguageInsight = {
  language: string;
  conclusion: string | null;
  hidden_reason: string | null;
  sentiment_counts: Record<string, number>;
  evidence_ids: string[];
  confidence: number;
};

type SplitCondition = {
  signal_id: string;
  title: string;
  summary: string;
  evidence_ids: string[];
};

type PersonaImpact = {
  persona: string;
  expected_reaction: string;
  evidence_ids: string[];
  confidence: number;
};

type Recommendation = {
  priority: number;
  title: string;
  action: string;
  addresses_risk_ids: string[];
  validation_metric_ids: string[];
};

type Artifact = Record<string, unknown>;

type UpdateRunResult = {
  brief: {
    run_id: string;
    decision: string;
    executive_summary: string;
    official_context: string | null;
    official_context_url: string | null;
    expected_positive: Impact[];
    expected_negative: Impact[];
    split_conditions: SplitCondition[];
    persona_impacts: PersonaImpact[];
    language_insights: LanguageInsight[];
    top_risks: Risk[];
    validation_metrics: Metric[];
    evidence: Evidence[];
    recommendations: Recommendation[];
  } & Artifact;
  feedback: { evidence: Evidence[]; status?: string; input_mode?: string } & Artifact;
  evidence: Artifact;
  impact: Artifact;
  validated: Artifact;
  events: AgentEvent[];
  fallback_used: boolean;
  analysis_incomplete: boolean;
  llm_provider: string;
  llm_requested: boolean;
};

type UpdateForm = {
  game: string;
  update_name: string;
  update_type: UpdateType;
  current_state: string;
  change_summary: string;
  goal: string;
  expected_benefits: string;
  concerns: string;
  scope: string;
  planned_on: string;
  cutoff_on: string;
  official_context_url: string;
  official_context: string;
  target_weapon: string;
  damage: string;
  recoil: string;
  rate_of_fire: string;
  ammunition: string;
  spawn_and_modes: string;
  changed_screen: string;
  user_journey: string;
  exposed_information: string;
  possible_errors: string;
  participation_conditions: string;
  rewards: string;
  restrictions: string;
  exception_rules: string;
  existing_user_impact: string;
};

const decisionLabels: Record<string, string> = {
  Go: "출시 가능",
  Revise: "일부 수정 후 출시",
  Test: "테스트 후 출시",
  Hold: "판정 보류",
};

const decisionDescriptions: Record<string, string> = {
  Go: "현재 근거와 검증 지표를 바탕으로 출시를 준비할 수 있습니다.",
  Revise: "출시 전에 우선 위험을 줄이는 수정이 필요합니다.",
  Test: "제한된 테스트 또는 검증 지표 확인 후 출시를 판단합니다.",
  Hold: "외부 자료 또는 입력이 충분하지 않아 출시 판단을 보류합니다.",
};

const updateTypeLabels: Record<UpdateType, string> = {
  weapon_balance: "무기 밸런스",
  ui_ux: "UI와 UX",
  system_rules: "시스템 규칙",
};

const languageLabels: Record<string, string> = {
  en: "영어권",
  ko: "한국어권",
  "zh-CN": "중국어권",
  es: "스페인어권",
  "pt-BR": "포르투갈어권",
};

const personaLabels: Record<string, string> = {
  time_constrained_casual_returning: "시간이 부족한 복귀 이용자",
  value_seeking_free_low_spend: "가성비를 중시하는 이용자",
  collector_high_engagement: "수집을 즐기는 이용자",
  core_combat_first: "전투 경험을 우선하는 이용자",
};

const initial: UpdateForm = {
  game: "PUBG: BATTLEGROUNDS",
  update_name: "Dragunov 확률 피해 제거",
  update_type: "weapon_balance",
  current_state: "기본 피해 58, 최대 피해 73의 확률형 구조",
  change_summary: "확률형 피해를 제거하고 피해를 60으로 고정",
  goal: "운에 따른 편차를 줄이고 전투 결과 예측 가능성을 높인다.",
  expected_benefits: "피해 결과 예측 가능성, 실력 중심 전투, 공정성 인식 개선",
  concerns: "반동과 연사력을 포함한 실제 성능, 사용률 쏠림, 메타 변화",
  scope: "일반 매칭의 Dragunov 사용 경험",
  planned_on: "2026-08-20",
  cutoff_on: "2026-08-13",
  official_context_url: "https://pubg.com/en/news/6616",
  official_context: "PUBG Update 25.2의 확률형 피해 제거 공식 변경 맥락",
  target_weapon: "Dragunov",
  damage: "기본 피해 58, 최대 피해 73의 확률형 구조에서 피해 60 고정으로 변경",
  recoil: "현행 유지",
  rate_of_fire: "해당 없음",
  ammunition: "7.62mm",
  spawn_and_modes: "일반 매칭",
  changed_screen: "해당 없음",
  user_journey: "해당 없음",
  exposed_information: "해당 없음",
  possible_errors: "해당 없음",
  participation_conditions: "해당 없음",
  rewards: "해당 없음",
  restrictions: "해당 없음",
  exception_rules: "해당 없음",
  existing_user_impact: "해당 없음",
};

function updateDetails(form: UpdateForm) {
  if (form.update_type === "weapon_balance") {
    return {
      kind: "weapon_balance",
      target_weapon: form.target_weapon,
      damage: form.damage,
      recoil: form.recoil,
      rate_of_fire: form.rate_of_fire,
      ammunition: form.ammunition,
      spawn_and_modes: form.spawn_and_modes,
    };
  }
  if (form.update_type === "ui_ux") {
    return {
      kind: "ui_ux",
      changed_screen: form.changed_screen,
      user_journey: form.user_journey,
      exposed_information: form.exposed_information,
      possible_errors: form.possible_errors,
    };
  }
  return {
    kind: "system_rules",
    participation_conditions: form.participation_conditions,
    rewards: form.rewards,
    restrictions: form.restrictions,
    exception_rules: form.exception_rules,
    existing_user_impact: form.existing_user_impact,
  };
}

function commaValues(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatApiError(detail: unknown) {
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item
          ? String(item.msg)
          : String(item),
      )
      .join(", ");
  }
  return typeof detail === "string" ? detail : "업데이트 점검을 실행할 수 없습니다.";
}

function FormField({
  label,
  name,
  value,
  onChange,
  multiline = false,
  type = "text",
}: {
  label: string;
  name: keyof UpdateForm;
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

function ArtifactDetails({ result }: { result: UpdateRunResult }) {
  const artifacts: Array<[string, string, Artifact]> = [
    ["UpdateFeedbackBundle", "자료 수집 결과", result.feedback],
    ["UpdateEvidencePack", "변경 영향 분석 결과", result.evidence],
    ["UpdateImpactAssessment", "레드팀 영향 점검 결과", result.impact],
    ["UpdateValidatedDecision", "검증 및 전략 판정 결과", result.validated],
    ["UpdateDecisionBrief", "발표용 최종 요약", result.brief],
  ];

  return (
    <section className="artifact-section">
      <div className="section-title">
        <h2>에이전트 산출물</h2>
        <p>카드를 펼치면 안전하게 정규화된 계약 JSON을 확인할 수 있습니다.</p>
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

export function UpdateReview() {
  const [form, setForm] = useState<UpdateForm>(initial);
  const [sourceMode, setSourceMode] = useState<SourceMode>("fixture");
  const [steamAppId, setSteamAppId] = useState("578080");
  const [useX, setUseX] = useState(false);
  const [xQuery, setXQuery] = useState("PUBG Dragunov damage");
  const [periodStart, setPeriodStart] = useState("2026-08-06T00:00");
  const [periodEnd, setPeriodEnd] = useState("2026-08-13T00:00");
  const [csvData, setCsvData] = useState("");
  const [csvName, setCsvName] = useState("");
  const [useClaude, setUseClaude] = useState(true);
  const [result, setResult] = useState<UpdateRunResult | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const updateForm = (
    event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    const name = event.target.name as keyof UpdateForm;
    setForm((previous) => ({ ...previous, [name]: event.target.value }) as UpdateForm);
  };

  const selectUpdateType = (next: UpdateType) => {
    setForm((previous) => ({ ...previous, update_type: next }));
    if (next !== "weapon_balance" && sourceMode === "fixture") {
      setSourceMode("live");
    }
    setResult(null);
    setError("");
  };

  const selectSourceMode = (next: SourceMode) => {
    if (next === "fixture" && form.update_type !== "weapon_balance") {
      return;
    }
    setSourceMode(next);
    setError("");
  };

  const handleCsv = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2_000_000) {
      setCsvData("");
      setCsvName("");
      setError("승인 CSV는 UTF-8 기준 2 MB 이하만 사용할 수 있습니다.");
      return;
    }
    const text = await file.text();
    if (new TextEncoder().encode(text).byteLength > 2_000_000) {
      setCsvData("");
      setCsvName("");
      setError("승인 CSV는 UTF-8 기준 2 MB 이하만 사용할 수 있습니다.");
      return;
    }
    setCsvData(text);
    setCsvName("승인 CSV 선택됨");
    setError("");
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sourceMode === "import" && !csvData) {
      setError("승인 CSV 파일을 선택해 주세요.");
      return;
    }
    if (sourceMode === "live" && !steamAppId && !useX) {
      setError("Steam 앱 ID 또는 X 검색 중 하나를 선택해 주세요.");
      return;
    }

    const livePeriodStart = sourceMode === "live" ? utcWallClockToIso(periodStart) : null;
    const livePeriodEnd = sourceMode === "live" ? utcWallClockToIso(periodEnd) : null;
    if (sourceMode === "live" && (!livePeriodStart || !livePeriodEnd)) {
      setError("수집 시각을 UTC 기준 YYYY-MM-DDTHH:mm 형식으로 정확히 입력해 주세요.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setEvents([]);

    try {
      const payload = {
        game: form.game,
        update_name: form.update_name,
        update_type: form.update_type,
        current_state: form.current_state,
        change_summary: form.change_summary,
        goal: form.goal,
        expected_benefits: commaValues(form.expected_benefits),
        concerns: commaValues(form.concerns),
        scope: form.scope,
        planned_on: form.planned_on,
        cutoff_on: form.cutoff_on,
        official_context_url: form.official_context_url || null,
        official_context: form.official_context || null,
        details: updateDetails(form),
        source_mode: sourceMode,
        fixture_case: "dragunov_random_damage_removal",
        steam_app_id: sourceMode === "live" && steamAppId ? Number(steamAppId) : null,
        use_x: sourceMode === "live" ? useX : false,
        x_query:
          sourceMode === "live" && xQuery.trim()
            ? xQuery.trim()
            : "PUBG Dragunov damage",
        period_start: livePeriodStart,
        period_end: livePeriodEnd,
        imported_csv: sourceMode === "import" ? csvData : null,
        use_llm: useClaude,
      };
      const response = await fetch(`${API_URL}/api/update-runs/stream`, {
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
          const message = JSON.parse(data) as {
            event?: AgentEvent;
            result?: UpdateRunResult;
            detail?: unknown;
          };
          if (eventName === "agent_event" && message.event) {
            setEvents((previous) => [...previous, message.event as AgentEvent]);
          }
          if (eventName === "result" && message.result) {
            setResult(message.result);
            setEvents(message.result.events);
          }
          if (eventName === "error") {
            throw new Error(formatApiError(message.detail));
          }
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "업데이트 점검을 실행할 수 없습니다.");
    } finally {
      setLoading(false);
    }
  }

  const actualAfter = result?.brief.evidence.filter((item) => item.period === "after") ?? [];
  const decision = result ? decisionLabels[result.brief.decision] ?? result.brief.decision : "";
  const visibleLanguages = result?.brief.language_insights.filter((item) => item.conclusion) ?? [];
  const primaryPositive = result?.brief.expected_positive[0];
  const primaryNegative = result?.brief.expected_negative[0];
  const primaryRisk = result?.brief.top_risks[0];
  const primaryRecommendation = result?.brief.recommendations
    .slice()
    .sort((left, right) => left.priority - right.priority)[0];

  return (
    <section className="update-review" aria-label="업데이트 점검">
      <div className="update-heading">
        <p className="eyebrow">
          <i /> 게임체인저 / 출시 전 업데이트 점검
        </p>
        <h2>변경안의 예상 반응과 출시 조건을 점검합니다.</h2>
        <p>
          변경 내용을 기준으로 예상되는 긍정 반응과 우려 반응, 검증 지표, 출시 판단을 한 화면에서
          확인합니다.
        </p>
      </div>

      <form onSubmit={submit}>
        <section className="form-card">
          <header>
            <span>01</span>
            <div>
              <h2>업데이트 유형</h2>
              <p>유형에 따라 필요한 변경 세부 조건과 사용할 자료 출처를 구분합니다.</p>
            </div>
          </header>
          <div className="update-types" role="group" aria-label="업데이트 유형">
            {(Object.keys(updateTypeLabels) as UpdateType[]).map((type) => (
              <button
                className="update-type"
                key={type}
                type="button"
                aria-pressed={form.update_type === type}
                onClick={() => selectUpdateType(type)}
              >
                <strong>{updateTypeLabels[type]}</strong>
                <span>
                  {type === "weapon_balance"
                    ? "피해량, 반동, 사용 환경의 균형을 점검합니다."
                    : type === "ui_ux"
                      ? "화면, 이용 동선, 정보 이해와 오류 가능성을 점검합니다."
                      : "참여 조건, 보상, 예외 규칙의 영향을 점검합니다."}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="form-card">
          <header>
            <span>02</span>
            <div>
              <h2>업데이트 기본 정보</h2>
              <p>현재 상태와 변경 목표를 명확히 적어 출시 전 예상의 기준을 만듭니다.</p>
            </div>
          </header>
          <div className="grid two">
            <FormField label="게임" name="game" value={form.game} onChange={updateForm} />
            <FormField
              label="업데이트 이름"
              name="update_name"
              value={form.update_name}
              onChange={updateForm}
            />
          </div>
          <div className="grid two">
            <FormField
              label="현재 상태"
              name="current_state"
              value={form.current_state}
              onChange={updateForm}
              multiline
            />
            <FormField
              label="변경 내용"
              name="change_summary"
              value={form.change_summary}
              onChange={updateForm}
              multiline
            />
            <FormField label="변경 목표" name="goal" value={form.goal} onChange={updateForm} multiline />
            <FormField
              label="적용 범위"
              name="scope"
              value={form.scope}
              onChange={updateForm}
              multiline
            />
            <FormField
              label="예상 효과 (쉼표로 구분)"
              name="expected_benefits"
              value={form.expected_benefits}
              onChange={updateForm}
            />
            <FormField
              label="우려 사항 (쉼표로 구분)"
              name="concerns"
              value={form.concerns}
              onChange={updateForm}
            />
            <FormField
              label="예정일 (UTC)"
              name="planned_on"
              value={form.planned_on}
              onChange={updateForm}
              type="date"
            />
            <FormField
              label="자료 기준일 (UTC)"
              name="cutoff_on"
              value={form.cutoff_on}
              onChange={updateForm}
              type="date"
            />
          </div>
          <FormField
            label="공식 변경 맥락 URL (HTTPS)"
            name="official_context_url"
            value={form.official_context_url}
            onChange={updateForm}
          />
          <FormField
            label="공식 변경 맥락"
            name="official_context"
            value={form.official_context}
            onChange={updateForm}
            multiline
          />
        </section>

        <section className="form-card">
          <header>
            <span>03</span>
            <div>
              <h2>변경 세부 조건</h2>
              <p>{updateTypeLabels[form.update_type]} 유형에 필요한 조건만 입력합니다.</p>
            </div>
          </header>
          {form.update_type === "weapon_balance" && (
            <div className="grid two">
              <FormField
                label="대상 무기"
                name="target_weapon"
                value={form.target_weapon}
                onChange={updateForm}
              />
              <FormField label="피해량" name="damage" value={form.damage} onChange={updateForm} />
              <FormField label="반동" name="recoil" value={form.recoil} onChange={updateForm} />
              <FormField
                label="연사력"
                name="rate_of_fire"
                value={form.rate_of_fire}
                onChange={updateForm}
              />
              <FormField
                label="탄약"
                name="ammunition"
                value={form.ammunition}
                onChange={updateForm}
              />
              <FormField
                label="스폰 및 사용 모드"
                name="spawn_and_modes"
                value={form.spawn_and_modes}
                onChange={updateForm}
              />
            </div>
          )}
          {form.update_type === "ui_ux" && (
            <div className="grid two">
              <FormField
                label="변경 화면"
                name="changed_screen"
                value={form.changed_screen}
                onChange={updateForm}
              />
              <FormField
                label="이용자 동선"
                name="user_journey"
                value={form.user_journey}
                onChange={updateForm}
              />
              <FormField
                label="새로 노출되는 정보"
                name="exposed_information"
                value={form.exposed_information}
                onChange={updateForm}
              />
              <FormField
                label="오류 가능성"
                name="possible_errors"
                value={form.possible_errors}
                onChange={updateForm}
              />
            </div>
          )}
          {form.update_type === "system_rules" && (
            <div className="grid two">
              <FormField
                label="참여 조건"
                name="participation_conditions"
                value={form.participation_conditions}
                onChange={updateForm}
              />
              <FormField label="보상" name="rewards" value={form.rewards} onChange={updateForm} />
              <FormField
                label="제한"
                name="restrictions"
                value={form.restrictions}
                onChange={updateForm}
              />
              <FormField
                label="예외 규칙"
                name="exception_rules"
                value={form.exception_rules}
                onChange={updateForm}
              />
              <FormField
                label="기존 이용자 영향"
                name="existing_user_impact"
                value={form.existing_user_impact}
                onChange={updateForm}
                multiline
              />
            </div>
          )}
        </section>

        <section className="form-card options">
          <header>
            <span>04</span>
            <div>
              <h2>자료 출처와 실행</h2>
              <p>시연 자료와 외부 자료는 분리합니다. 외부 실패는 저장 사례로 대체하지 않습니다.</p>
            </div>
          </header>
          <div className="source-mode-grid" role="group" aria-label="업데이트 자료 출처">
            {form.update_type === "weapon_balance" && (
              <button
                type="button"
                className="source-mode"
                aria-pressed={sourceMode === "fixture"}
                onClick={() => selectSourceMode("fixture")}
              >
                <strong>검증된 저장 데이터</strong>
                <span>Dragunov 합성 비교 자료로 안정적으로 시연합니다.</span>
              </button>
            )}
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "live"}
              onClick={() => selectSourceMode("live")}
            >
              <strong>Steam과 X 실시간 갱신</strong>
              <span>기준일 이전의 선택한 공개 자료만 수집합니다.</span>
            </button>
            <button
              type="button"
              className="source-mode"
              aria-pressed={sourceMode === "import"}
              onClick={() => selectSourceMode("import")}
            >
              <strong>승인 CSV 가져오기</strong>
              <span>개인정보와 원문 열이 없는 승인된 UTF-8 CSV만 사용합니다.</span>
            </button>
          </div>

          {sourceMode === "fixture" && (
            <p className="source-note">
              모든 근거는 합성 비교 참고 자료이며 실제 이용자 여론이나 사후 결과가 아닙니다.
            </p>
          )}
          {sourceMode === "live" && (
            <div className="grid two source-fields">
              <label className="field">
                <span>Steam 앱 ID</span>
                <input
                  inputMode="numeric"
                  value={steamAppId}
                  onChange={(event) => setSteamAppId(event.target.value)}
                />
              </label>
              <label className="field">
                <span>X 검색어</span>
                <input value={xQuery} onChange={(event) => setXQuery(event.target.value)} />
              </label>
              <label className="field">
                <span>수집 시작 시각 (UTC)</span>
                <input
                  type="datetime-local"
                  value={periodStart}
                  onChange={(event) => setPeriodStart(event.target.value)}
                />
              </label>
              <label className="field">
                <span>수집 종료 및 기준 시각 (UTC)</span>
                <input
                  type="datetime-local"
                  value={periodEnd}
                  onChange={(event) => setPeriodEnd(event.target.value)}
                />
              </label>
              <label className="toggle source-toggle">
                <input
                  type="checkbox"
                  checked={useX}
                  onChange={(event) => setUseX(event.target.checked)}
                />
                <span>X 공개 자료도 수집</span>
                <small>비용 한도와 기준일은 서버의 안전 정책으로 검증합니다.</small>
              </label>
            </div>
          )}
          {sourceMode === "import" && (
            <label className="field">
              <span>승인 CSV 파일</span>
              <input type="file" accept=".csv,text/csv" onChange={handleCsv} />
              <small className="field-help">
                {csvName || "UTF-8 텍스트 2 MB 이하의 승인 CSV만 전송합니다. 원문은 화면에 표시하지 않습니다."}
              </small>
            </label>
          )}
          <label className="toggle">
            <input
              type="checkbox"
              checked={useClaude}
              onChange={(event) => setUseClaude(event.target.checked)}
            />
            <span>Claude로 한국어 설명 보강</span>
            <small>
              {useClaude
                ? "근거 ID, 위험, 최종 판정은 코드 정책으로 다시 검증합니다."
                : "결정론적 분석 경로만 실행합니다."}
            </small>
          </label>
          <p className="prelaunch-notice">
            출시 전 예상이며 실제 이용자 반응이 아닙니다. API 키를 입력하거나 저장하지 않으며,
            자료 원문도 결과 화면에 표시하지 않습니다.
          </p>
          <button className="primary" disabled={loading}>
            {loading ? "업데이트 점검 중..." : "출시 전 업데이트 점검 시작"}
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>
      </form>

      {loading && (
        <section className="live-panel">
          <div className="section-title">
            <h2>에이전트 실행 중</h2>
            <p>서버 SSE 이벤트를 받는 즉시 각 단계와 노드의 상태를 표시합니다.</p>
          </div>
          <AgentPipeline events={events} active mode="update" />
        </section>
      )}

      {result && (
        <section className="results update-results">
          <section className="decision-brief" aria-labelledby="update-decision-title">
            <header className="decision-brief-head">
              <div>
                <p className="eyebrow">출시 판단</p>
                <h2 id="update-decision-title">{decision}</h2>
              </div>
              <span className="decision">{decision}</span>
            </header>
            <p className="decision-summary">{businessKorean(result.brief.executive_summary)}</p>
            <p className="decision-caution">
              출시 전 자료를 바탕으로 한 예상입니다. 실제 이용자 반응과 출시 후 성과를 의미하지 않습니다.
            </p>

            <div className="decision-logic" aria-label="출시 판단 과정">
              <article>
                <span>1. 판단 근거</span>
                <strong>비식별 근거 {result.brief.evidence.length}건</strong>
                <small>기준일 이전 자료만 사용</small>
              </article>
              <b aria-hidden="true">→</b>
              <article>
                <span>2. 예상 반응</span>
                <strong>이용자 유형 {result.brief.persona_impacts.length}개, 언어권 {visibleLanguages.length}개</strong>
                <small>표본 기준을 통과한 결론만 공개</small>
              </article>
              <b aria-hidden="true">→</b>
              <article>
                <span>3. 출시 판단</span>
                <strong>{decision}</strong>
                <small>{businessKorean(decisionDescriptions[result.brief.decision] ?? decisionDescriptions.Hold)}</small>
              </article>
            </div>

            <div className="decision-signal-grid">
              <article className="decision-signal positive">
                <span>예상 긍정 반응</span>
                <strong>{businessKorean(primaryPositive?.title ?? "확인된 긍정 신호 없음")}</strong>
                <p>{businessKorean(primaryPositive?.summary ?? "현재 근거에서는 별도의 긍정 반응을 예상하기 어렵습니다.")}</p>
              </article>
              <article className="decision-signal negative">
                <span>예상 우려 반응</span>
                <strong>{businessKorean(primaryNegative?.title ?? primaryRisk?.title ?? "확인된 우려 신호 없음")}</strong>
                <p>{businessKorean(primaryNegative?.summary ?? primaryRisk?.failure_path ?? "현재 근거에서는 우선 확인할 우려 반응이 없습니다.")}</p>
              </article>
              <article className="decision-signal split">
                <span>반응이 갈릴 조건</span>
                <strong>{businessKorean(result.brief.split_conditions[0]?.title ?? "뚜렷한 분기 조건 없음")}</strong>
                <p>{businessKorean(result.brief.split_conditions[0]?.summary ?? "이용자 유형별 차이는 아래 예상 반응에서 확인할 수 있습니다.")}</p>
              </article>
            </div>

            <div className="decision-context-grid">
              <section>
                <h3>이용자 유형별 예상 반응</h3>
                <div className="decision-list">
                  {result.brief.persona_impacts.map((item) => (
                    <article key={item.persona}>
                      <strong>{personaLabels[item.persona] ?? businessKorean(item.persona)}</strong>
                      <p>{businessKorean(item.expected_reaction)}</p>
                      <small>근거 {item.evidence_ids.length}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
                    </article>
                  ))}
                </div>
              </section>
              <section>
                <h3>언어권별 예상</h3>
                <div className="decision-list">
                  {result.brief.language_insights.map((item) => (
                    <article className={item.conclusion ? "" : "is-muted"} key={item.language}>
                      <strong>{languageLabels[item.language] ?? businessKorean(item.language)}</strong>
                      <p>{businessKorean(item.conclusion ?? item.hidden_reason ?? "표본이 부족해 결론을 공개하지 않습니다.")}</p>
                      <small>{item.conclusion ? `근거 ${item.evidence_ids.length}건, 신뢰도 ${Math.round(item.confidence * 100)}%` : "표본 보강 필요"}</small>
                    </article>
                  ))}
                </div>
              </section>
            </div>

            <div className="decision-grounding">
              <section>
                <h3>판단을 좌우한 위험</h3>
                {result.brief.top_risks.length ? (
                  <ul>
                    {result.brief.top_risks.slice(0, 3).map((risk) => (
                      <li key={risk.risk_id}>
                        <strong>{businessKorean(risk.title)}</strong>
                        <span>{businessKorean(risk.failure_path)}</span>
                        <small>근거 {risk.evidence_ids.length}건, 신뢰도 {Math.round(risk.confidence * 100)}%</small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>현재 자료에서는 우선 수정이 필요한 위험이 확인되지 않았습니다.</p>
                )}
              </section>
              <aside className="decision-action">
                <span>지금 해야 할 일</span>
                <h3>{businessKorean(primaryRecommendation?.title ?? decision)}</h3>
                <p>{businessKorean(primaryRecommendation?.action ?? decisionDescriptions[result.brief.decision] ?? decisionDescriptions.Hold)}</p>
                {result.brief.validation_metrics[0] && (
                  <small>확인 기준: {businessKorean(result.brief.validation_metrics[0].success_condition)}</small>
                )}
              </aside>
            </div>

            <footer className="decision-meta">
              <span>{result.analysis_incomplete
                ? "외부 자료 분석이 충분하지 않아 판정을 보류했습니다."
                : result.llm_requested
                  ? result.fallback_used
                    ? "Claude 설명은 안전한 결정론 경로로 대체했습니다."
                    : `Claude 설명 보강을 사용했습니다. (${result.llm_provider})`
                  : "결정론적 분석을 사용했습니다."}</span>
              <span>실행 ID: {result.brief.run_id}</span>
            </footer>
          </section>

          {(result.brief.official_context || result.brief.official_context_url) && (
            <section className="official-context">
              <p className="eyebrow">공식 자료</p>
              <h2>공식으로 확인된 변경 맥락</h2>
              {result.brief.official_context && <p>{businessKorean(result.brief.official_context)}</p>}
              {result.brief.official_context_url && (
                <a href={result.brief.official_context_url} target="_blank" rel="noreferrer">
                  공식 변경 내용 열기
                </a>
              )}
            </section>
          )}

          <section className="reaction-section">
            <div className="section-title">
              <h2>출시 전 예상 반응</h2>
              <p>예상되는 긍정 반응과 우려 반응, 반응이 갈릴 조건을 실제 반응과 구분해 표시합니다.</p>
            </div>
            <div className="reaction-grid">
              <article className="reaction-card positive">
                <span>예상 긍정 반응</span>
                {result.brief.expected_positive.length ? (
                  result.brief.expected_positive.map((item) => (
                    <div className="reaction-entry" key={item.impact_id}>
                      <h3>{businessKorean(item.title)}</h3>
                      <p>{businessKorean(item.summary)}</p>
                      <small>근거 {item.evidence_ids.length}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
                    </div>
                  ))
                ) : (
                  <p>현재 자료에서 공개할 긍정 예상 신호가 없습니다.</p>
                )}
              </article>
              <article className="reaction-card negative">
                <span>예상 부정 반응</span>
                {result.brief.expected_negative.length ? (
                  result.brief.expected_negative.map((item) => (
                    <div className="reaction-entry" key={item.impact_id}>
                      <h3>{businessKorean(item.title)}</h3>
                      <p>{businessKorean(item.summary)}</p>
                      <small>근거 {item.evidence_ids.length}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
                    </div>
                  ))
                ) : (
                  <p>현재 자료에서 공개할 부정 예상 신호가 없습니다.</p>
                )}
              </article>
              <article className="reaction-card split">
                <span>반응이 갈릴 이용자 유형</span>
                {result.brief.persona_impacts.map((item) => (
                  <div className="reaction-entry" key={item.persona}>
                    <h3>{personaLabels[item.persona] ?? item.persona}</h3>
                    <p>{businessKorean(item.expected_reaction)}</p>
                    <small>근거 {item.evidence_ids.length}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
                  </div>
                ))}
                {result.brief.split_conditions.map((item) => (
                  <div className="reaction-entry" key={item.signal_id}>
                    <h3>{businessKorean(item.title)}</h3>
                    <p>{businessKorean(item.summary)}</p>
                  </div>
                ))}
              </article>
            </div>
          </section>

          <section className="insight-section">
            <div className="section-title">
              <h2>언어권별 예상</h2>
              <p>표본 기준을 통과한 언어권만 감정 건수와 결론을 공개합니다.</p>
            </div>
            <div className="language-grid">
              {result.brief.language_insights.map((language) => (
                <article
                  className={`language-card ${language.conclusion ? "" : "muted"}`}
                  key={language.language}
                >
                  <strong>{languageLabels[language.language] ?? language.language}</strong>
                  {language.conclusion ? (
                    <>
                      <p>{businessKorean(language.conclusion)}</p>
                      <small>
                        {Object.entries(language.sentiment_counts)
                          .map(([sentiment, count]) => `${sentiment} ${count}건`)
                          .join(", ")}
                      </small>
                    </>
                  ) : (
                    <>
                      <p>{businessKorean(language.hidden_reason ?? "표본 기준에 미달해 결론을 공개하지 않습니다.")}</p>
                      <small>감정 비율과 수치는 공개하지 않습니다.</small>
                    </>
                  )}
                </article>
              ))}
            </div>
          </section>

          <section className="metric-section">
            <div className="section-title">
              <h2>출시 후 검증할 지표</h2>
              <p>실제 결과가 생긴 뒤에만 확인할 측정 항목입니다.</p>
            </div>
            <div className="metric-table-wrap">
              <table className="metric-table">
                <thead>
                  <tr>
                    <th scope="col">지표</th>
                    <th scope="col">측정 방법</th>
                    <th scope="col">성공 기준</th>
                    <th scope="col">연결 위험</th>
                  </tr>
                </thead>
                <tbody>
                  {result.brief.validation_metrics.map((metric) => (
                    <tr key={metric.metric_id}>
                      <td>{businessKorean(metric.title)}</td>
                      <td>{businessKorean(metric.measurement)}</td>
                      <td>{businessKorean(metric.success_condition)}</td>
                      <td>{metric.addresses_risk_ids.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {actualAfter.length > 0 && (
            <section className="actual-after-section">
              <div className="section-title">
                <h2>업데이트 후 실제 반응</h2>
                <p>기준일 이후에 안전하게 수집된 실제 반응이 있는 경우에만 표시합니다.</p>
              </div>
              <div className="evidence-list">
                {actualAfter.map((item) => (
                  <details key={item.evidence_id}>
                    <summary>{businessKorean(item.summary)}</summary>
                    <p className="evidence-meta">
                      {item.language}, {item.sentiment}, {item.mechanism_tags.join(", ")}, {item.source}
                    </p>
                  </details>
                ))}
              </div>
            </section>
          )}

          <section className="evidence-section">
            <div className="section-title">
              <h2>근거와 비식별 의견</h2>
              <p>사용자 원문 대신 안전하게 정규화된 요약, 기간, 감정, 태그와 출처만 제공합니다.</p>
            </div>
            <div className="evidence-list">
              {result.brief.evidence.map((item) => (
                <details key={item.evidence_id}>
                  <summary>
                    <span>{businessKorean(item.summary)}</span>
                    <small>{item.synthetic ? "합성 비교 참고" : "비식별 요약"}</small>
                  </summary>
                  <p className="evidence-meta">
                    기간 {item.period}, 감정 {item.sentiment}, 관련성 {Math.round(item.relevance * 100)}%, 태그 {item.mechanism_tags.join(", ")}
                  </p>
                  <a href={item.source_url} target="_blank" rel="noreferrer">
                    {item.source} 출처 열기
                  </a>
                </details>
              ))}
            </div>
          </section>

          <section className="final-pipeline">
            <div className="section-title">
              <h2>에이전트 실행 과정</h2>
              <p>단계별 노드는 가로 카드에서 열어 정의된 값과 처리 상태를 확인할 수 있습니다.</p>
            </div>
            <AgentPipeline events={result.events} mode="update" />
          </section>

          <ArtifactDetails result={result} />
        </section>
      )}
    </section>
  );
}
