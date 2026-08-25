import { businessKorean } from "./businessKorean";

const personaThemes: Record<string, { mark: string; code: string }> = {
  time_constrained_casual_returning: { mark: "⏱", code: "시간형" },
  value_seeking_free_low_spend: { mark: "₩", code: "가치형" },
  collector_high_engagement: { mark: "◆", code: "수집형" },
  core_combat_first: { mark: "◎", code: "전투형" },
};

const languageMarks: Record<string, string> = {
  en: "영",
  ko: "한",
  "zh-CN": "中",
  es: "서",
  "pt-BR": "포",
};

function splitReaction(value: string) {
  const normalized = businessKorean(value);
  const opinion = normalized
    .split("예상 행동:")[0]
    .replace("예상 대표 의견:", "")
    .trim();
  const action = normalized.split("예상 행동:")[1]?.trim();
  return { opinion, action };
}

export function PersonaGameCard({
  persona,
  label,
  reaction,
  evidenceCount,
  confidence,
  context,
  opinionVisible = true,
}: {
  persona: string;
  label: string;
  reaction: string;
  evidenceCount: number;
  confidence: number;
  context: string;
  opinionVisible?: boolean;
}) {
  const theme = personaThemes[persona] ?? { mark: "●", code: "이용자" };
  const { opinion, action } = splitReaction(reaction);
  return (
    <article className={`audience-card persona-card persona-${persona}`} aria-label={`${label} 예상 반응 카드`}>
      <i className="card-foil" aria-hidden="true" />
      <header className="audience-card-head">
        <span>이용자 예상 카드</span>
        <b>{theme.code}</b>
      </header>
      <div className="persona-character">
        <span className="persona-mark" aria-hidden="true">{theme.mark}</span>
        <div>
          <small>이용자 유형</small>
          <h3>{label}</h3>
        </div>
      </div>
      {opinionVisible ? (
        <div className="audience-opinion">
          <span>예상 대표 의견</span>
          <p>{opinion || "직접 연결된 예상 의견이 없습니다."}</p>
          <small>AI가 근거를 바탕으로 구성한 예상이며 실제 인용이 아닙니다.</small>
        </div>
      ) : (
        <div className="audience-opinion is-repeated">
          <span>예상 대표 의견</span>
          <p>대표 의견은 관련 이용자 유형 카드에 함께 표시했습니다.</p>
        </div>
      )}
      <div className="audience-action">
        <span>예상 행동</span>
        <p>{action || "현재 이용 방식을 유지할 가능성이 있습니다."}</p>
      </div>
      <p className="audience-context">{context}</p>
      <footer className="audience-stats">
        <span><small>근거</small><strong>{evidenceCount ? `${evidenceCount}건` : "확인 필요"}</strong></span>
        <span><small>근거 일치도</small><strong>{evidenceCount ? `${Math.round(confidence * 100)}%` : "산정 전"}</strong></span>
      </footer>
    </article>
  );
}

export function LanguageGameCard({
  language,
  label,
  conclusion,
  hiddenReason,
  evidenceCount,
  confidence,
  sentimentCounts,
}: {
  language: string;
  label: string;
  conclusion: string | null;
  hiddenReason?: string | null;
  evidenceCount: number;
  confidence: number;
  sentimentCounts?: Record<string, number>;
}) {
  const counts = sentimentCounts ?? {};
  const sentimentTotal = Object.values(counts).reduce((sum, count) => sum + count, 0);
  return (
    <article className={`audience-card language-game-card ${conclusion ? "" : "is-locked"}`} aria-label={`${label} 예상 반응 카드`}>
      <i className="card-foil" aria-hidden="true" />
      <header className="audience-card-head">
        <span>언어권 예상 카드</span>
        <b>{label}</b>
      </header>
      <div className="language-emblem">
        <span aria-hidden="true">{languageMarks[language] ?? language.slice(0, 2).toUpperCase()}</span>
        <div>
          <small>언어권</small>
          <h3>{label}</h3>
        </div>
      </div>
      <div className="language-conclusion">
        <span>{conclusion ? "예상 반응" : "표본 확인 필요"}</span>
        <p>{businessKorean(conclusion ?? hiddenReason ?? "표본을 보강한 뒤 예상 반응을 확인해야 합니다.")}</p>
      </div>
      {sentimentTotal > 0 && conclusion && (
        <div
          className="sentiment-strip"
          role="img"
          aria-label={`긍정 ${counts.positive ?? 0}건, 우려 ${counts.negative ?? 0}건, 혼합 ${counts.mixed ?? 0}건, 중립 ${counts.neutral ?? 0}건`}
        >
          {(counts.positive ?? 0) > 0 && <span className="is-positive" style={{ flexGrow: counts.positive }} />}
          {(counts.negative ?? 0) > 0 && <span className="is-negative" style={{ flexGrow: counts.negative }} />}
          {(counts.mixed ?? 0) > 0 && <span className="is-mixed" style={{ flexGrow: counts.mixed }} />}
          {(counts.neutral ?? 0) > 0 && <span className="is-neutral" style={{ flexGrow: counts.neutral }} />}
        </div>
      )}
      {sentimentTotal > 0 && conclusion && (
        <div className="sentiment-legend" aria-hidden="true">
          {(counts.positive ?? 0) > 0 && <span className="is-positive">긍정 {counts.positive}건</span>}
          {(counts.negative ?? 0) > 0 && <span className="is-negative">우려 {counts.negative}건</span>}
          {(counts.mixed ?? 0) > 0 && <span className="is-mixed">혼합 {counts.mixed}건</span>}
          {(counts.neutral ?? 0) > 0 && <span className="is-neutral">중립 {counts.neutral}건</span>}
        </div>
      )}
      <footer className="audience-stats">
        <span><small>근거</small><strong>{conclusion ? `${evidenceCount}건` : "보강 필요"}</strong></span>
        <span><small>근거 일치도</small><strong>{conclusion ? `${Math.round(confidence * 100)}%` : "비공개"}</strong></span>
      </footer>
    </article>
  );
}
