"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type TrendResult = {
  snapshot_at: string;
  corpus_version: string;
  evidence_count: number;
  corpus_count: number;
  average_confidence: number;
  sentiment_counts: Record<"positive" | "negative" | "mixed" | "neutral", number>;
  language_counts: Record<string, number>;
  top_topics: TrendCount[];
  top_reasons: TrendCount[];
  top_behaviors: TrendCount[];
  evidence: Array<{
    language: string;
    stance: string;
    summary: string;
    confidence: number;
  }>;
};

type TrendCount = { label: string; count: number };
type ContentType = "event" | "update" | "general";

const sentimentLabels = {
  positive: "긍정",
  negative: "부정",
  mixed: "긍정과 우려가 함께 있음",
  neutral: "판단 유보",
};

const languageLabels: Record<string, string> = { ko: "한국어", en: "영어" };
const contentTypeLabels: Record<ContentType, string> = {
  event: "이벤트와 보상",
  update: "업데이트와 밸런스",
  general: "전반적인 플레이 경험",
};

function ratio(count: number, total: number) {
  return total ? Math.round((count / total) * 100) : 0;
}

function formatSnapshot(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "기준 시점 확인 필요"
    : `${date.toLocaleDateString("ko-KR", { timeZone: "UTC" })} UTC`;
}

function TrendList({ title, items }: { title: string; items: TrendCount[] }) {
  return (
    <article className="trend-list-card">
      <h3>{title}</h3>
      {items.length ? (
        <ol>
          {items.map((item) => (
            <li key={item.label}>
              <span>{item.label}</span>
              <strong>{item.count}건</strong>
            </li>
          ))}
        </ol>
      ) : <p>현재 범위에서 뚜렷한 항목을 확인하지 못했습니다.</p>}
    </article>
  );
}

export function TrendReview() {
  const [game, setGame] = useState("PUBG: BATTLEGROUNDS");
  const [reportTitle, setReportTitle] = useState("이벤트 보상과 참여 경험");
  const [contentType, setContentType] = useState<ContentType>("event");
  const [result, setResult] = useState<TrendResult | null>(null);
  const [submittedTitle, setSubmittedTitle] = useState(reportTitle);
  const [submittedType, setSubmittedType] = useState<ContentType>(contentType);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (result) resultHeadingRef.current?.focus();
  }, [result]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch("/api/trends", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game, report_title: reportTitle, content_type: contentType }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "동향을 불러오지 못했습니다.");
      setSubmittedTitle(reportTitle);
      setSubmittedType(contentType);
      setResult(payload as TrendResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "동향을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const total = result?.evidence_count ?? 0;
  const leadingSentiment = result
    ? (Object.entries(result.sentiment_counts) as Array<[keyof TrendResult["sentiment_counts"], number]>)
      .sort((left, right) => right[1] - left[1])[0]
    : undefined;

  return (
    <>
      <form onSubmit={submit} aria-busy={loading}>
        <section className="form-card">
          <header>
            <span>01</span>
            <div>
              <h2>살펴볼 동향</h2>
              <p>게임과 분석 유형을 선택하고, 결과를 구분할 보고서 이름을 입력합니다.</p>
            </div>
          </header>
          <div className="grid two">
            <label className="field">
              <span>게임</span>
              <input value={game} onChange={(event) => setGame(event.target.value)} required />
            </label>
            <label className="field">
              <span>보고서 이름</span>
              <input value={reportTitle} onChange={(event) => setReportTitle(event.target.value)} required />
            </label>
          </div>
          <label className="field trend-type-field">
            <span>분석 유형</span>
            <select value={contentType} onChange={(event) => setContentType(event.target.value as ContentType)}>
              <option value="event">이벤트와 보상</option>
              <option value="update">업데이트와 밸런스</option>
              <option value="general">전반적인 플레이 경험</option>
            </select>
          </label>
          <p className="prelaunch-notice">
            보고서 이름은 결과를 구분하는 용도입니다. 분석은 선택한 유형과 연결된 코퍼스 근거를 기준으로 진행합니다.
          </p>
        </section>

        <section className="form-card">
          <header>
            <span>02</span>
            <div>
              <h2>자료 범위</h2>
              <p>현재 버전은 사전 구축 Steam 코퍼스를 사용합니다.</p>
            </div>
          </header>
          <div className="source-mode-grid" role="group" aria-label="동향 자료 출처">
            <div className="source-mode source-mode-fixed">
              <strong>사전 구축 Steam 코퍼스</strong>
              <span>한국어와 영어 리뷰에서 만든 비식별 파생 자료를 사용합니다.</span>
            </div>
          </div>
          <p className="prelaunch-notice">
            리뷰 원문과 이용자 식별자는 포함하지 않습니다. 이 기능은 Claude API를 호출하지 않습니다.
          </p>
          <button className="primary" disabled={loading}>
            {loading ? "동향 정리 중..." : "동향 추출"}
          </button>
          {error && <p className="error" role="alert">{error}</p>}
        </section>
      </form>

      {result && (
        <section className="trend-report print-report" aria-labelledby="trend-report-heading">
          <header className="trend-report-head">
            <div>
              <p className="report-section-label">01 핵심 요약</p>
              <h2 id="trend-report-heading" ref={resultHeadingRef} tabIndex={-1}>
                {submittedTitle} 참고 동향 보고서
              </h2>
              <p>
                관련 비식별 근거 {total}건 중 가장 많이 확인된 반응은
                {leadingSentiment ? ` ${sentimentLabels[leadingSentiment[0]]} ${leadingSentiment[1]}건` : " 확인하기 어려움"}입니다.
              </p>
            </div>
            <span className="trend-report-badge">현재 코퍼스 단면</span>
          </header>
          <p className="trend-scope-notice" role="status">
            입력한 이름은 보고서를 구분하는 데만 사용합니다. 결과는 {contentTypeLabels[submittedType]} 분류와 연결된 코퍼스 근거를 집계한 참고 동향입니다.
          </p>

          <section className="report-section" aria-labelledby="trend-summary-heading">
            <div className="report-section-heading">
              <span>02</span>
              <div>
                <h3 id="trend-summary-heading">반응 분포</h3>
                <p>선택한 분석 유형과 관련된 근거 안에서 계산한 비중입니다.</p>
              </div>
            </div>
            <div className="trend-sentiment-bar" aria-label="반응 분포">
              {(Object.entries(result.sentiment_counts) as Array<[keyof TrendResult["sentiment_counts"], number]>).map(([key, count]) => (
                <span key={key} className={`is-${key}`} style={{ width: `${ratio(count, total)}%` }} />
              ))}
            </div>
            <div className="trend-metrics">
              {(Object.entries(result.sentiment_counts) as Array<[keyof TrendResult["sentiment_counts"], number]>).map(([key, count]) => (
                <article key={key}>
                  <small>{sentimentLabels[key]}</small>
                  <strong>{ratio(count, total)}%</strong>
                  <span>{count}건</span>
                </article>
              ))}
            </div>
          </section>

          <section className="report-section" aria-labelledby="trend-data-heading">
            <div className="report-section-heading">
              <span>03</span>
              <div>
                <h3 id="trend-data-heading">데이터 범위와 신뢰성</h3>
                <p>같은 코퍼스 버전에서 검색한 표본과 분류 신뢰도입니다.</p>
              </div>
            </div>
            <div className="trend-data-grid">
              <article><small>관련 근거</small><strong>{result.evidence_count}건</strong></article>
              <article><small>전체 코퍼스</small><strong>{result.corpus_count}건</strong></article>
              <article><small>평균 분류 신뢰도</small><strong>{Math.round(result.average_confidence * 100)}%</strong></article>
              <article><small>자료 기준 시점</small><strong>{formatSnapshot(result.snapshot_at)}</strong></article>
            </div>
            <p className="trend-language-note">
              언어별 관련 근거: {Object.entries(result.language_counts).map(([language, count]) => `${languageLabels[language] ?? language} ${count}건`).join(", ")}
            </p>
          </section>

          <section className="report-section" aria-labelledby="trend-detail-heading">
            <div className="report-section-heading">
              <span>04</span>
              <div>
                <h3 id="trend-detail-heading">세부 분석</h3>
                <p>반복해서 나타난 주제, 이유, 예상 행동을 비교합니다.</p>
              </div>
            </div>
            <div className="trend-list-grid">
              <TrendList title="주요 주제" items={result.top_topics} />
              <TrendList title="반응의 주요 이유" items={result.top_reasons} />
              <TrendList title="이어질 수 있는 행동" items={result.top_behaviors} />
            </div>
            <details className="trend-evidence-details">
              <summary>비식별 파생 요약 보기</summary>
              <div>
                {result.evidence.map((item, index) => (
                  <article key={`${item.language}-${index}`}>
                    <strong>{languageLabels[item.language] ?? item.language}, {sentimentLabels[item.stance as keyof typeof sentimentLabels] ?? "기타 반응"}</strong>
                    <p>{item.summary}</p>
                    <small>분류 신뢰도 {Math.round(item.confidence * 100)}%</small>
                  </article>
                ))}
              </div>
            </details>
          </section>

          <section className="report-section trend-limit-grid" aria-labelledby="trend-next-heading">
            <div>
              <div className="report-section-heading">
                <span>05</span>
                <div>
                  <h3 id="trend-next-heading">비교와 후속 점검</h3>
                  <p>현재 연결된 자료의 범위를 분명히 표시합니다.</p>
                </div>
              </div>
              <p>과거 사례의 출시 후 성과와 자사 평시 기준선은 아직 연결되지 않아 비교하지 않습니다.</p>
            </div>
            <aside>
              <strong>데이터 연동 필요</strong>
              <p>날짜별 변화, 리뷰 폭탄 탐지, 매출과 이탈, 판정 적중률은 원천 데이터가 연결된 뒤 제공합니다.</p>
            </aside>
          </section>

          <footer className="report-actions">
            <div>
              <p className="report-section-label">06 리포트 저장</p>
              <strong>현재 보고서를 인쇄하거나 PDF로 저장할 수 있습니다.</strong>
            </div>
            <button type="button" onClick={() => window.print()}>인쇄 또는 PDF 저장</button>
          </footer>
        </section>
      )}
    </>
  );
}
