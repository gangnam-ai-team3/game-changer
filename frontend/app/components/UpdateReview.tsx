"use client";

import { ChangeEvent, FormEvent, useState } from "react";

import { AgentEvent, AgentPipeline } from "./AgentPipeline";
import { LanguageGameCard, PersonaGameCard } from "./AudienceCards";
import { businessKorean, businessKoreanJson } from "./businessKorean";
import { corpusDemoDates, isFutureUtcDate } from "./corpusDemoDates";
import { DecisionReport, DecisionReportData } from "./DecisionReport";
import { utcWallClockToIso } from "./utcWallClock";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type UpdateType = "weapon_balance" | "ui_ux" | "system_rules";
type SourceMode = "fixture" | "corpus" | "live" | "import";

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
  positive_signal_ids: string[];
  negative_signal_ids: string[];
  split_signal_ids: string[];
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
  validated: { decision_reason: string } & Artifact;
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
  Revise: "수정 후 재검토",
  Test: "테스트 후 출시",
  Hold: "판정 보류",
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

const periodLabels: Record<string, string> = {
  before: "출시 전 자료",
  comparable_reference: "유사 사례 비교 자료",
  after: "출시 후 실제 반응",
};

const sentimentLabels: Record<string, string> = {
  positive: "긍정",
  negative: "우려",
  mixed: "혼합",
  neutral: "중립",
};

const mechanismLabels: Record<string, string> = {
  predictability: "결과 예측 가능성",
  skill_fairness: "실력 반영 공정성",
  balance_regression: "전투 밸런스 재확인",
  fairness_regression: "이용 조건별 공정성",
  validation_needed: "설명과 실제 성능 검증",
  information_clarity: "변경 정보 명확성",
  flow_disruption: "이용 흐름 방해",
  rule_exception: "예외 규칙 일관성",
  learning_burden: "새 규칙 학습 부담",
};

const sourceLabels: Record<string, string> = {
  steam: "Steam",
  x: "X",
  reddit_import: "승인된 Reddit 자료",
  threads_import: "승인된 Threads 자료",
  instagram_import: "승인된 Instagram 자료",
  synthetic: "검증된 저장 자료",
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

const updateSeverityLabels: Record<string, string> = {
  Low: "낮음",
  Medium: "보통",
  High: "높음",
  Critical: "매우 높음",
};

function updateEvidenceCount(ids: string[]) {
  return new Set(ids).size;
}

function updateExpectedAction(value: string) {
  const marker = "예상 행동:";
  const index = value.indexOf(marker);
  return index >= 0 ? businessKorean(value.slice(index + marker.length).trim()) : "";
}

function updateOpinionKey(value: string) {
  const opinion = value.split("예상 행동:")[0].replace("예상 대표 의견:", "");
  return businessKorean(opinion).replace(/[\p{P}\s]/gu, "");
}

function selectUpdatePositive(items: Impact[]) {
  return items.slice().sort((left, right) => (
    updateEvidenceCount(right.evidence_ids) - updateEvidenceCount(left.evidence_ids)
    || right.confidence - left.confidence
    || left.impact_id.localeCompare(right.impact_id)
  ))[0];
}

function findUpdateRecommendation(recommendations: Recommendation[], riskId?: string) {
  if (!riskId) return undefined;
  return recommendations
    .filter((item) => item.addresses_risk_ids.includes(riskId))
    .slice()
    .sort((left, right) => left.priority - right.priority)[0];
}

function findUpdateMetric(metrics: Metric[], recommendation: Recommendation | undefined, riskId?: string) {
  for (const metricId of recommendation?.validation_metric_ids ?? []) {
    const metric = metrics.find((item) => item.metric_id === metricId);
    if (metric) return metric;
  }
  return riskId ? metrics.find((item) => item.addresses_risk_ids.includes(riskId)) : undefined;
}

function visibleUpdateOpinions(items: PersonaImpact[]) {
  const seen = new Set<string>();
  const visible = new Set<string>();
  items.slice().sort((left, right) => (
    updateEvidenceCount(right.evidence_ids) - updateEvidenceCount(left.evidence_ids)
    || right.confidence - left.confidence
    || left.persona.localeCompare(right.persona)
  )).forEach((item) => {
    const key = updateOpinionKey(item.expected_reaction);
    if (key && !seen.has(key)) {
      seen.add(key);
      visible.add(item.persona);
    }
  });
  return visible;
}

function buildUpdateReport(result: UpdateRunResult, subject: string): DecisionReportData {
  const primaryRisk = result.brief.top_risks[0];
  const positive = selectUpdatePositive(result.brief.expected_positive);
  const recommendation = findUpdateRecommendation(result.brief.recommendations, primaryRisk?.risk_id);
  const metric = findUpdateMetric(result.brief.validation_metrics, recommendation, primaryRisk?.risk_id);
  const modeLabels: Record<string, string> = {
    fixture: "검증된 저장 자료",
    corpus: "사전 구축 코퍼스",
    live: "실시간 공개 자료",
    import: "승인 CSV",
  };
  const modeLabel = result.feedback.input_mode ? modeLabels[result.feedback.input_mode] : undefined;
  const evidenceCount = new Set(result.brief.evidence.map((item) => item.evidence_id)).size;
  const languageCount = result.brief.language_insights.filter((item) => item.conclusion).length;
  const affected = positive?.affected_personas.map((id) => personaLabels[id] ?? "이용자 유형 확인 필요").join(", ");
  const positiveAction = positive ? updateExpectedAction(positive.summary) : "";

  return {
    subject,
    decision: result.brief.decision,
    decisionLabel: decisionLabels[result.brief.decision] ?? "판정 확인 필요",
    conclusion: businessKorean([
      result.validated.decision_reason,
      recommendation ? `우선 조치는 ‘${recommendation.title}’입니다.` : "",
    ].filter(Boolean).join(" ")),
    fullReasoning: businessKorean(result.brief.executive_summary),
    sourceScope: [
      `고유 근거 ${evidenceCount}건`,
      `결론 공개 언어권 ${languageCount}개`,
      modeLabel,
    ].filter(Boolean).join(", "),
    analysisIncomplete: result.analysis_incomplete,
    expectedCard: {
      label: "예상 효과",
      title: businessKorean(positive?.title ?? "대표 효과 선정 어려움"),
      body: positive
        ? businessKorean([affected ? `영향 이용자는 ${affected}입니다.` : "", positiveAction].filter(Boolean).join(" "))
        : "현재 근거만으로 대표 효과를 선정하기 어렵습니다.",
      meta: positive ? `고유 근거 ${updateEvidenceCount(positive.evidence_ids)}건` : undefined,
    },
    riskCard: {
      label: "가장 큰 위험",
      title: businessKorean(primaryRisk?.title ?? "우선 위험이 확인되지 않았습니다"),
      body: businessKorean(primaryRisk?.failure_path ?? "현재 검증 범위에서 우선 위험이 확인되지 않았습니다."),
      meta: primaryRisk ? `${updateSeverityLabels[primaryRisk.severity] ?? "수준 확인 필요"}, 고유 근거 ${updateEvidenceCount(primaryRisk.evidence_ids)}건` : undefined,
    },
    actionCard: {
      label: "출시 전 조치",
      title: businessKorean(recommendation?.title ?? "연결된 출시 전 조치를 확인할 수 없습니다"),
      body: businessKorean(recommendation?.action ?? "위험과 연결된 권고안을 상세 근거에서 확인해 주세요."),
      meta: `확인 기준: ${businessKorean(metric?.success_condition ?? "확인 기준이 연결되지 않았습니다")}`,
    },
    riskRows: result.brief.top_risks.slice(0, 3).map((risk) => {
      const linkedRecommendation = findUpdateRecommendation(result.brief.recommendations, risk.risk_id);
      const linkedMetric = findUpdateMetric(result.brief.validation_metrics, linkedRecommendation, risk.risk_id);
      return {
        id: risk.risk_id,
        risk: businessKorean(risk.title),
        level: updateSeverityLabels[risk.severity] ?? "확인 필요",
        impact: businessKorean(risk.failure_path),
        action: businessKorean(linkedRecommendation?.action ?? "연결된 출시 전 조치를 확인할 수 없습니다"),
        check: businessKorean(linkedMetric?.success_condition ?? "확인 기준이 연결되지 않았습니다"),
      };
    }),
  };
}

function UpdateReactionDetails({ result }: { result: UpdateRunResult }) {
  const visibleOpinions = visibleUpdateOpinions(result.brief.persona_impacts);
  const signalTitles = new Map(
    [...result.brief.expected_positive, ...result.brief.expected_negative, ...result.brief.split_conditions]
      .map((signal) => [
        "signal_id" in signal ? signal.signal_id : signal.impact_id.replace(/^impact-/, ""),
        businessKorean(signal.title),
      ]),
  );

  return (
    <section className="reaction-section">
      <div className="section-title">
        <h3>출시 전 예상 반응</h3>
        <p>예상되는 긍정 반응과 우려 반응, 반응이 갈릴 조건을 실제 반응과 구분해 표시합니다.</p>
      </div>
      <div className="reaction-grid">
        <article className="reaction-card positive">
          <span>예상 긍정 반응</span>
          {result.brief.expected_positive.length ? result.brief.expected_positive.map((item) => (
            <div className="reaction-entry" key={item.impact_id}>
              <h3>{businessKorean(item.title)}</h3>
              <p className="reaction-copy">{businessKorean(item.summary)}</p>
              <small>근거 {updateEvidenceCount(item.evidence_ids)}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
            </div>
          )) : <p>현재 자료에서 공개할 긍정 예상 신호가 없습니다.</p>}
        </article>
        <article className="reaction-card negative">
          <span>예상 부정 반응</span>
          {result.brief.expected_negative.length ? result.brief.expected_negative.map((item) => (
            <div className="reaction-entry" key={item.impact_id}>
              <h3>{businessKorean(item.title)}</h3>
              <p className="reaction-copy">{businessKorean(item.summary)}</p>
              <small>근거 {updateEvidenceCount(item.evidence_ids)}건, 신뢰도 {Math.round(item.confidence * 100)}%</small>
            </div>
          )) : <p>현재 자료에서 공개할 부정 예상 신호가 없습니다.</p>}
        </article>
        <article className="reaction-card split">
          <span>반응이 갈릴 조건</span>
          {result.brief.split_conditions.length ? result.brief.split_conditions.map((item) => (
            <div className="reaction-entry" key={item.signal_id}>
              <h3>{businessKorean(item.title)}</h3>
              <p className="reaction-copy">{businessKorean(item.summary)}</p>
            </div>
          )) : <p>현재 자료에서는 뚜렷하게 반응이 갈릴 조건이 확인되지 않았습니다.</p>}
        </article>
      </div>
      <div className="audience-subsection">
        <h3>이용자 유형별 예상 반응</h3>
        <p>각 이용자 유형의 대표 의견과 예상 행동을 카드별로 비교할 수 있습니다.</p>
        <div className="audience-card-grid">
          {result.brief.persona_impacts.map((item) => {
            const relatedTitles = [...item.positive_signal_ids, ...item.negative_signal_ids, ...item.split_signal_ids]
              .map((id) => signalTitles.get(id))
              .filter(Boolean);
            return (
              <PersonaGameCard
                key={item.persona}
                persona={item.persona}
                label={personaLabels[item.persona] ?? item.persona}
                reaction={item.expected_reaction}
                evidenceCount={updateEvidenceCount(item.evidence_ids)}
                confidence={item.confidence}
                opinionVisible={visibleOpinions.has(item.persona)}
                context={relatedTitles.length
                  ? `연결된 반응: ${relatedTitles.join(", ")}`
                  : "직접 연결된 반응 근거 없음"}
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}

function UpdateEvidenceDetails({ result }: { result: UpdateRunResult }) {
  const actualAfter = result.brief.evidence.filter((item) => item.period === "after");
  const riskTitles = new Map(
    result.brief.top_risks.map((risk) => [risk.risk_id, businessKorean(risk.title)]),
  );

  return (
    <>
      {(result.brief.official_context || result.brief.official_context_url) && (
        <section className="official-context">
          <p className="eyebrow">공식 자료</p>
          <h3>공식으로 확인된 변경 맥락</h3>
          {result.brief.official_context && <p>{businessKorean(result.brief.official_context)}</p>}
          {result.brief.official_context_url && (
            <a href={result.brief.official_context_url} target="_blank" rel="noreferrer">
              공식 변경 내용 열기
            </a>
          )}
        </section>
      )}

      <section className="insight-section">
        <div className="section-title">
          <h3>언어권별 예상</h3>
          <p>표본 기준을 통과한 언어권만 감정 건수와 결론을 공개합니다.</p>
        </div>
        <div className="audience-card-grid">
          {result.brief.language_insights.map((language) => (
            <LanguageGameCard
              key={language.language}
              language={language.language}
              label={languageLabels[language.language] ?? language.language}
              conclusion={language.conclusion}
              hiddenReason={language.hidden_reason}
              evidenceCount={language.evidence_ids.length}
              confidence={language.confidence}
              sentimentCounts={language.sentiment_counts}
            />
          ))}
        </div>
      </section>

      <section className="metric-section">
        <div className="section-title">
          <h3>출시 후 검증할 지표</h3>
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
                  <td>{metric.addresses_risk_ids.map((id) => riskTitles.get(id) ?? "관련 위험").join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {actualAfter.length > 0 && (
        <section className="actual-after-section">
          <div className="section-title">
            <h3>업데이트 후 실제 반응</h3>
            <p>기준일 이후에 안전하게 수집된 실제 반응이 있는 경우에만 표시합니다.</p>
          </div>
          <div className="evidence-list">
            {actualAfter.map((item) => (
              <details key={item.evidence_id}>
                <summary>{businessKorean(item.summary)}</summary>
                <p className="evidence-meta">
                  {languageLabels[item.language] ?? item.language}, {sentimentLabels[item.sentiment] ?? "기타 반응"}, {item.mechanism_tags.map((tag) => mechanismLabels[tag] ?? "기타 변경 요소").join(", ")}, {sourceLabels[item.source] ?? "공개 자료"}
                </p>
              </details>
            ))}
          </div>
        </section>
      )}

      <section className="evidence-section">
        <div className="section-title">
          <h3>근거와 비식별 의견</h3>
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
                기간 {periodLabels[item.period] ?? "기간 확인 필요"}, 반응 {sentimentLabels[item.sentiment] ?? "기타"}, 관련성 {Math.round(item.relevance * 100)}%, 주제 {item.mechanism_tags.map((tag) => mechanismLabels[tag] ?? "기타 변경 요소").join(", ")}
              </p>
              <a href={item.source_url} target="_blank" rel="noreferrer">
                {sourceLabels[item.source] ?? "공개 자료"} 출처 열기
              </a>
            </details>
          ))}
        </div>
      </section>
    </>
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
  const [submittedSubject, setSubmittedSubject] = useState(initial.update_name);
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

  const applyCorpusDemoDates = () => {
    const dates = corpusDemoDates();
    setForm((previous) => ({
      ...previous,
      cutoff_on: dates.cutoffOn,
      planned_on: dates.startsOn,
    }));
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
    if (!form.cutoff_on || !form.planned_on) {
      setError("자료 기준일과 출시 예정일을 모두 입력해 주세요.");
      return;
    }
    if (form.cutoff_on > form.planned_on) {
      setError("자료 기준일은 출시 예정일과 같거나 앞선 날짜로 설정해 주세요.");
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

    const requestSubject = form.update_name.trim() || "이름 없는 업데이트";
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
            setSubmittedSubject(requestSubject);
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

  return (
    <section className="update-review" aria-label="업데이트 점검">
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
          {sourceMode === "corpus" && (
            <div className="source-note corpus-note">
              <p>자료 기준일은 내일(UTC), 검토 대상 시작일은 그다음 날로 설정합니다. 코퍼스에는 한국어와 영어 비식별 요약과 분류값만 저장되며, 리뷰 원문은 포함하지 않습니다.</p>
              <button type="button" className="corpus-date-action" onClick={applyCorpusDemoDates}>
                코퍼스 데모 날짜 적용
              </button>
            </div>
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
            <span>{sourceMode === "corpus" ? "팀 에이전트로 추가 검증" : "Claude로 설명 보강"}</span>
            <small>
              {sourceMode === "corpus"
                ? useClaude
                  ? "유주심 에이전트가 Haiku로 이용자 유형별 문구를 정리하고, 정아현(Jelly) 위험 점검과 승진배 근거 검증 에이전트는 Sonnet 5로 실행됩니다."
                  : "저장된 코퍼스와 코드 정책만 사용하며 페르소나 문구 정리와 두 팀 에이전트의 Claude 호출은 생략합니다."
                : useClaude
                  ? "근거 연결과 최종 판정은 코드 정책으로 다시 검증합니다."
                  : "코드 정책만으로 점검합니다."}
            </small>
          </label>
          <p className="prelaunch-notice">
            출시 전 예상이며 실제 이용자 반응이나 출시 후 성과를 의미하지 않습니다.
            {sourceMode === "fixture" && " 저장 자료는 합성 비교 사례입니다."}
            {" "}API 키와 자료 원문은 화면에 표시하거나 저장하지 않습니다.
          </p>
          <button className="primary" disabled={loading}>
            {loading ? "업데이트 점검 중..." : "업데이트 점검 시작"}
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
            <p>서버에서 받는 즉시 각 에이전트와 노드의 상태를 표시합니다.</p>
          </div>
          <AgentPipeline events={events} active mode="update" />
        </section>
      )}

      {result && (() => {
        const report = buildUpdateReport(result, submittedSubject);
        return (
          <DecisionReport
            {...report}
            reactionDetails={<UpdateReactionDetails result={result} />}
            evidenceDetails={<UpdateEvidenceDetails result={result} />}
            agentDetails={(
              <>
                <AgentPipeline events={result.events} mode="update" />
                <ArtifactDetails result={result} />
              </>
            )}
          />
        );
      })()}
    </section>
  );
}
