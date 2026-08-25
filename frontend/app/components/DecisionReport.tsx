"use client";

import { ReactNode, useEffect, useId, useRef } from "react";

export type ReportCard = {
  label: string;
  title: string;
  body: string;
  meta?: string;
};

export type RiskRow = {
  id: string;
  risk: string;
  level: string;
  impact: string;
  action: string;
  check: string;
};

export type DecisionReportData = {
  subject: string;
  decision: string;
  decisionLabel: string;
  conclusion: string;
  fullReasoning: string;
  sourceScope: string;
  analysisIncomplete: boolean;
  metrics: Array<{ label: string; value: string }>;
  expectedCard: ReportCard;
  riskCard: ReportCard;
  actionCard: ReportCard;
  riskRows: RiskRow[];
};

export type DecisionReportProps = DecisionReportData & {
  reactionDetails: ReactNode;
  evidenceDetails: ReactNode;
  agentDetails: ReactNode;
};

function SummaryCard({ card }: { card: ReportCard }) {
  return (
    <article className="decision-report-card">
      <span>{card.label}</span>
      <h3>{card.title}</h3>
      <p>{card.body}</p>
      {card.meta && <small>{card.meta}</small>}
    </article>
  );
}

export function DecisionReport({
  subject,
  decision,
  decisionLabel,
  conclusion,
  fullReasoning,
  sourceScope,
  analysisIncomplete,
  metrics,
  expectedCard,
  riskCard,
  actionCard,
  riskRows,
  reactionDetails,
  evidenceDetails,
  agentDetails,
}: DecisionReportProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  const knownDecisions = ["Go", "Revise", "Test", "Hold"];
  const decisionTone = knownDecisions.includes(decision) ? decision.toLowerCase() : "unknown";

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section className="decision-report print-report" aria-labelledby={headingId} data-decision={decisionTone}>
      <header className="decision-report-head">
        <div>
          <p className="report-section-label">01 핵심 요약</p>
          <h2 id={headingId} ref={headingRef} tabIndex={-1}>{subject}</h2>
          <p className="decision-report-conclusion">{conclusion}</p>
          <p className="decision-report-scope">{sourceScope}</p>
        </div>
        <span className="decision-report-badge">{decisionLabel}</span>
      </header>

      {analysisIncomplete && (
        <p className="decision-report-alert" role="alert">
          자료 또는 핵심 분석이 완료되지 않았습니다. 상세 근거를 확인한 뒤 판정을 사용해 주세요.
        </p>
      )}

      <p className="decision-report-caution">
        출시 전 자료를 바탕으로 한 예상입니다. 실제 이용자 반응과 출시 후 성과를 의미하지 않습니다.
        아래 대표 의견은 AI가 구성한 예상이며 실제 이용자 인용이 아닙니다.
      </p>

      <section className="decision-report-metrics" aria-label="데이터 범위">
        <p className="report-section-label">02 데이터 범위</p>
        <div>
          {metrics.map((metric) => (
            <article key={metric.label}>
              <small>{metric.label}</small>
              <strong>{metric.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <p className="report-section-label decision-report-section-label">03 예상 반응</p>
      <div className="decision-report-card-grid">
        <SummaryCard card={expectedCard} />
        <SummaryCard card={riskCard} />
        <SummaryCard card={actionCard} />
      </div>

      <section className="decision-report-risks" aria-labelledby={`${headingId}-risks`}>
        <p className="report-section-label">04 위험과 대응</p>
        <h3 id={`${headingId}-risks`}>위험과 출시 전 확인</h3>
        {riskRows.length ? (
          <table>
            <thead>
              <tr>
                <th scope="col">위험</th>
                <th scope="col">수준</th>
                <th scope="col">이용자에게 생길 수 있는 문제</th>
                <th scope="col">출시 전 확인</th>
              </tr>
            </thead>
            <tbody>
              {riskRows.slice(0, 3).map((row) => (
                <tr key={row.id}>
                  <td data-label="위험">{row.risk}</td>
                  <td data-label="수준">{row.level}</td>
                  <td data-label="이용자에게 생길 수 있는 문제">{row.impact}</td>
                  <td data-label="출시 전 확인">
                    <strong>{row.action}</strong>
                    <span>{row.check}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="decision-report-empty">현재 검증 범위에서 우선 위험이 확인되지 않았습니다.</p>
        )}
      </section>

      <div className="decision-report-details">
        <p className="report-section-label">05 상세 근거</p>
        <details>
          <summary>예상 반응과 이용자 유형</summary>
          <div className="decision-report-detail-body">{reactionDetails}</div>
        </details>
        <details>
          <summary>언어권과 판단 근거</summary>
          <div className="decision-report-detail-body">
            <details className="decision-report-reasoning">
              <summary>판정 논리 전체 보기</summary>
              <p>{fullReasoning}</p>
            </details>
            {evidenceDetails}
          </div>
        </details>
        <details>
          <summary>에이전트 실행 과정과 산출물</summary>
          <div className="decision-report-detail-body">{agentDetails}</div>
        </details>
      </div>
      <footer className="report-actions">
        <div>
          <p className="report-section-label">06 리포트 저장</p>
          <strong>현재 보고서를 인쇄하거나 PDF로 저장할 수 있습니다.</strong>
        </div>
        <button type="button" onClick={() => window.print()}>인쇄 또는 PDF 저장</button>
      </footer>
    </section>
  );
}
