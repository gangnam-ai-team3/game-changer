# 게임체인저 한 페이지 출시 판단 보고서 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이벤트 점검과 업데이트 점검의 결과를 같은 정보 위계의 한 페이지 보고서로 정리해, 첫 화면만으로 판정과 대표 반응, 핵심 위험, 출시 전 조치를 이해할 수 있게 한다.

**Architecture:** 새 `DecisionReport` 컴포넌트가 공통 보고서 골격과 결과 초점 이동을 맡고, 이벤트와 업데이트 화면은 각 계약을 보고서 데이터로 바꾸는 순수 함수를 현재 파일 안에 둔다. 기존 이용자 카드, 언어권 카드, 에이전트 파이프라인과 계약 JSON은 삭제하지 않고 세 개의 기본 접힘 영역에 전달한다.

**Tech Stack:** Next.js 16.3.0, React 19.2, TypeScript 5.7, 기본 HTML `details`와 `table`, 기존 CSS, Python pytest 소스 배선 검사

**Spec:** `docs/superpowers/specs/2026-08-20-decision-report-one-page-design.md`

## Global Constraints

- 작업 브랜치는 `demo_mvp`를 유지한다.
- 변경 범위는 `frontend/app/components/DecisionReport.tsx`, `frontend/app/page.tsx`, `frontend/app/components/UpdateReview.tsx`, `frontend/app/components/AudienceCards.tsx`, `frontend/app/globals.css`, `tests/test_frontend_update_contract.py`로 제한한다.
- `frontend/app/components/AgentPipeline.tsx`, 백엔드, Python 계약, 판정 정책과 에이전트 코드는 수정하지 않는다.
- 새 패키지와 새 테스트 실행 도구를 추가하지 않는다. React, TypeScript, CSS와 기본 HTML만 사용한다.
- `decision`, `analysis_incomplete`, 위험 순서, 근거 ID와 조치 ID는 백엔드 값을 그대로 사용한다. 프론트엔드가 판정을 새로 계산하지 않는다.
- 가장 큰 위험은 항상 `top_risks[0]`이며 프론트엔드에서 다시 정렬하지 않는다.
- 상단 결론은 `validated.decision_reason`과 ID로 연결된 우선 조치만 사용한다. `executive_summary` 전문은 접힌 `판정 논리 전체 보기`에만 표시한다.
- 핵심 카드에는 따옴표로 된 대표 의견을 표시하지 않는다. 계약 제목, 영향 이용자, 연결 위험, 고유 근거 수와 `예상 행동:` 뒤의 문장만 사용한다.
- `analysis_incomplete=true`일 때만 상단 안내를 표시한다. `fallback_used`만으로 상단 경고를 만들지 않는다.
- 이용자 화면 문구에는 가운뎃점을 사용하지 않고 자연스러운 업무 한국어를 사용한다.
- 1440×900에서는 보고서 헤더, 세 핵심 카드, 위험 표가 결과 첫 화면에 들어와야 한다. 390픽셀에서는 가로 스크롤 없이 한 열과 세로형 표 행으로 보여야 한다.
- 결과 제목은 `DecisionReport`가 마운트될 때 초점을 받고, `details`, `summary`, `table`, 상태 이름과 불투명 초점 테두리를 유지한다.
- 현재 작업 트리의 기존 수정은 사용자 작업이다. `git reset`, `git checkout --`, `git add -A`를 사용하지 않고 각 단계에서 지정 파일과 해당 변경 부분만 스테이징한다.
- 프론트엔드 작업에서는 Claude, Steam, X 등 외부 API를 호출하지 않는다.

---

## File Map

- `frontend/app/components/DecisionReport.tsx`: 보고서 헤더, 상태 안내, 세 핵심 카드, 위험과 조치 표, 세 상세 영역, 결과 초점 이동을 담당한다.
- `frontend/app/components/AudienceCards.tsx`: 중복 대표 의견을 숨기는 `opinionVisible` 속성과 `근거 일치도` 표기를 담당한다.
- `frontend/app/page.tsx`: 이벤트 응답 타입, 제출 이벤트명 스냅샷, 이벤트 계약의 보고서 데이터 변환과 이벤트 상세 슬롯을 담당한다.
- `frontend/app/components/UpdateReview.tsx`: 업데이트 응답 타입, 제출 업데이트명 스냅샷, 업데이트 계약의 보고서 데이터 변환과 업데이트 상세 슬롯을 담당한다.
- `frontend/app/globals.css`: 공통 보고서의 데스크톱과 모바일 배치, 상태 색상, 표의 모바일 행 전환, 초점 스타일을 담당한다.
- `tests/test_frontend_update_contract.py`: 공통 컴포넌트와 두 모드의 배선, ID 연결, 제출값 스냅샷, 중복 방지, 접근성 구조를 소스 수준에서 검사한다.

---

### Task 1: 공통 보고서 골격과 이용자 카드 중복 방지

**Files:**
- Create: `frontend/app/components/DecisionReport.tsx`
- Modify: `frontend/app/components/AudienceCards.tsx`
- Modify: `frontend/app/globals.css`
- Test: `tests/test_frontend_update_contract.py`

**Interfaces:**
- Consumes: React의 `ReactNode`, `useEffect`, `useId`, `useRef`; 기존 `PersonaGameCard`와 `LanguageGameCard` 스타일
- Produces: `DecisionReportData`, `DecisionReportProps`, `DecisionReport`, `ReportCard`, `RiskRow`, `PersonaGameCard.opinionVisible?: boolean`

- [ ] **Step 1: 공통 보고서와 중복 방지 계약을 확인하는 실패 테스트를 작성한다**

`tests/test_frontend_update_contract.py`에 다음 검사를 추가한다.

```python
def test_shared_decision_report_has_accessible_one_page_structure():
    source = (ROOT / "components" / "DecisionReport.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "globals.css").read_text(encoding="utf-8")

    for name in (
        "DecisionReportData",
        "subject",
        "decisionLabel",
        "conclusion",
        "fullReasoning",
        "sourceScope",
        "analysisIncomplete",
        "expectedCard",
        "riskCard",
        "actionCard",
        "riskRows",
        "reactionDetails",
        "evidenceDetails",
        "agentDetails",
    ):
        assert name in source
    assert "useEffect" in source
    assert "headingRef.current?.focus()" in source
    assert "knownDecisions.includes(decision)" in source
    assert 'tabIndex={-1}' in source
    assert 'role="alert"' in source
    assert "analysisIncomplete &&" in source
    assert "판정 논리 전체 보기" in source
    assert "실제 이용자 인용이 아닙니다" in source
    assert "예상 반응과 이용자 유형" in source
    assert "언어권과 판단 근거" in source
    assert "에이전트 실행 과정과 산출물" in source
    assert "<table" in source
    assert 'data-label="위험"' in source
    assert 'data-label="출시 전 확인"' in source
    assert ".decision-report-card-grid" in styles
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in styles
    assert "content:attr(data-label)" in styles


def test_audience_cards_can_hide_duplicate_opinion_and_name_confidence_correctly():
    source = (ROOT / "components" / "AudienceCards.tsx").read_text(encoding="utf-8")

    assert "opinionVisible = true" in source
    assert "opinionVisible ?" in source
    assert "대표 의견은 관련 이용자 유형 카드에 함께 표시했습니다" in source
    assert source.count("근거 일치도") == 2
    assert "<small>신뢰도</small>" not in source
```

- [ ] **Step 2: 새 테스트가 예상한 이유로 실패하는지 확인한다**

Run: `uv run pytest tests/test_frontend_update_contract.py::test_shared_decision_report_has_accessible_one_page_structure tests/test_frontend_update_contract.py::test_audience_cards_can_hide_duplicate_opinion_and_name_confidence_correctly -q`

Expected: 첫 검사는 `DecisionReport.tsx`가 없어 실패하고, 두 번째 검사는 `opinionVisible`이 없어 실패한다.

- [ ] **Step 3: 공통 타입과 보고서 컴포넌트를 만든다**

`frontend/app/components/DecisionReport.tsx`를 다음 구조로 만든다.

```tsx
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
    <section className="decision-report" aria-labelledby={headingId} data-decision={decisionTone}>
      <header className="decision-report-head">
        <div>
          <p className="eyebrow">출시 판단 보고서</p>
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

      <div className="decision-report-card-grid">
        <SummaryCard card={expectedCard} />
        <SummaryCard card={riskCard} />
        <SummaryCard card={actionCard} />
      </div>

      <section className="decision-report-risks" aria-labelledby={`${headingId}-risks`}>
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
    </section>
  );
}
```

- [ ] **Step 4: 이용자 카드에 대표 의견 표시 여부와 정확한 지표 이름을 연결한다**

`PersonaGameCard`의 매개변수와 타입에 `opinionVisible = true`와 `opinionVisible?: boolean`을 추가하고, 의견 영역을 다음과 같이 바꾼다.

```tsx
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
```

`PersonaGameCard`와 `LanguageGameCard`의 통계 하단에서 다음 표기를 사용한다.

```tsx
<span><small>근거 일치도</small><strong>{evidenceCount ? `${Math.round(confidence * 100)}%` : "산정 전"}</strong></span>
```

언어권 카드의 값이 비공개일 때는 기존 `비공개` 값을 유지하고 라벨만 `근거 일치도`로 바꾼다.

- [ ] **Step 5: 공통 보고서의 데스크톱과 모바일 CSS를 추가한다**

`frontend/app/globals.css`에 기존 변수와 색상을 재사용하는 다음 범위의 스타일을 추가한다. 기존 광범위 선택자를 바꾸지 않고 `.decision-report` 아래로 한정한다.

```css
.decision-report{margin-top:28px;padding:24px;border:1px solid var(--border);border-radius:16px;background:#fff;color:var(--text)}
.decision-report-head{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.decision-report-head h2{margin:4px 0 10px;font-size:28px;line-height:1.25;outline:none}
.decision-report-head h2:focus-visible,.decision-report-details summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px;border-radius:6px}
.decision-report-conclusion{max-width:920px;margin:0;font-size:16px;line-height:1.65;font-weight:650}
.decision-report-scope,.decision-report-caution{margin:8px 0 0;color:var(--muted);font-size:12px;line-height:1.5}
.decision-report-badge{flex:none;padding:7px 11px;border:1px solid currentColor;border-radius:999px;font-size:13px;font-weight:750}
.decision-report[data-decision="go"] .decision-report-badge{color:#16794c}.decision-report[data-decision="revise"] .decision-report-badge{color:#9a5b00}.decision-report[data-decision="test"] .decision-report-badge{color:#3656a6}.decision-report[data-decision="hold"] .decision-report-badge{color:#9a5b00}
.decision-report-alert{margin:14px 0 0;padding:11px 13px;border:1px solid #d97706;border-radius:10px;background:#fffbeb;color:#92400e;font-size:13px;font-weight:650}
.decision-report-card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}
.decision-report-card{display:flex;min-height:170px;flex-direction:column;padding:16px;border:1px solid var(--border);border-radius:12px;background:var(--bg)}
.decision-report-card>span{color:var(--accent);font-size:12px;font-weight:750}
.decision-report-card h3{margin:9px 0 7px;font-size:17px;line-height:1.35}
.decision-report-card p{margin:0;font-size:14px;line-height:1.55}
.decision-report-card small{margin-top:auto;padding-top:12px;color:var(--muted);font-size:12px}
.decision-report-risks{margin-top:18px}
.decision-report-risks h3{margin:0 0 10px;font-size:16px}
.decision-report-risks table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}
.decision-report-risks th,.decision-report-risks td{padding:11px 10px;border-top:1px solid var(--border);text-align:left;vertical-align:top;overflow-wrap:anywhere}
.decision-report-risks th{color:var(--muted);font-size:12px;font-weight:650}
.decision-report-risks th:nth-child(1){width:20%}.decision-report-risks th:nth-child(2){width:10%}.decision-report-risks th:nth-child(3){width:34%}.decision-report-risks th:nth-child(4){width:36%}
.decision-report-risks td strong,.decision-report-risks td span{display:block}.decision-report-risks td span{margin-top:4px;color:var(--muted)}
.decision-report-empty{margin:0;padding:14px;border:1px dashed var(--border);border-radius:10px;color:var(--muted);font-size:14px}
.decision-report-details{display:grid;gap:8px;margin-top:18px}
.decision-report-details>details{border:1px solid var(--border);border-radius:10px;background:#fff}
.decision-report-details>details>summary{cursor:pointer;padding:13px 15px;font-size:14px;font-weight:700}
.decision-report-detail-body{padding:0 15px 15px}
.decision-report-reasoning{margin-bottom:14px;padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--bg)}
.decision-report-reasoning summary{cursor:pointer;font-size:13px;font-weight:700}.decision-report-reasoning p{white-space:pre-line;font-size:14px;line-height:1.7}

@media (max-width:800px){
  .decision-report{padding:18px 14px}.decision-report-head{display:grid;gap:12px}.decision-report-badge{justify-self:start}
  .decision-report-card-grid{grid-template-columns:1fr}.decision-report-card{min-height:0}
  .decision-report-risks thead{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
  .decision-report-risks table,.decision-report-risks tbody,.decision-report-risks tr,.decision-report-risks td{display:block;width:100%}
  .decision-report-risks tr{margin-top:10px;border:1px solid var(--border);border-radius:10px;overflow:hidden}
  .decision-report-risks td{display:grid;grid-template-columns:108px minmax(0,1fr);gap:10px;border-top:1px solid var(--border)}
  .decision-report-risks td:first-child{border-top:0}
  .decision-report-risks td::before{content:attr(data-label);color:var(--muted);font-size:12px;font-weight:650}
}
```

- [ ] **Step 6: Task 1 테스트와 프로덕션 빌드를 통과시킨다**

Run: `uv run pytest tests/test_frontend_update_contract.py -q`

Expected: 기존 검사와 새 공통 컴포넌트 검사 모두 PASS

Run: `npm --prefix frontend run build`

Expected: TypeScript 검사와 Next.js 프로덕션 빌드 PASS

Run: `git diff --check`

Expected: 공백 오류 없음

- [ ] **Step 7: Task 1 변경만 커밋한다**

```bash
git add frontend/app/components/DecisionReport.tsx frontend/app/components/AudienceCards.tsx
git add -p frontend/app/globals.css tests/test_frontend_update_contract.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: add shared decision report shell"
```

`git diff --cached --name-only`에는 Task 1의 네 파일만 있어야 한다. 부분 스테이징 화면에서는 이 계획의 테스트와 `.decision-report` 스타일 블록만 선택한다.

---

### Task 2: 이벤트 점검을 한 페이지 보고서에 연결

**Files:**
- Modify: `frontend/app/page.tsx`
- Test: `tests/test_frontend_update_contract.py`

**Interfaces:**
- Consumes: `DecisionReport`, `DecisionReportData`, `PersonaGameCard.opinionVisible`, 이벤트의 `RunResult`
- Produces: `buildEventReport(result: RunResult, subject: string): DecisionReportData`, `selectEventPanel(result: RunResult): PersonaPanel | undefined`, 제출 시점 이벤트명 상태

- [ ] **Step 1: 이벤트 보고서 배선과 선택 규칙을 확인하는 실패 테스트를 작성한다**

`tests/test_frontend_update_contract.py`에 다음 검사를 추가하고, 오래된 `decision-logic`, `decisionHeading`, `final-pipeline`을 요구하는 기존 검사는 새 공통 구조를 요구하도록 같은 변경 부분에서 수정한다.

```python
def test_event_result_maps_contract_to_shared_decision_report():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")

    assert 'import { DecisionReport, DecisionReportData }' in source
    assert "decision_reason: string" in source
    assert "input_mode?: string" in source
    assert "submittedSubject" in source
    assert "const requestSubject = form.event_name.trim()" in source
    assert "setSubmittedSubject(requestSubject)" in source
    assert "function selectEventPanel" in source
    assert "function findEventRevision" in source
    assert "function buildEventReport" in source
    assert "top_risks[0]" in source
    assert "addresses_risk_ids.includes(riskId)" in source
    assert "uniqueEvidenceCount(panel.evidence_ids)" in source
    assert "left.confidence" in source
    assert "left.persona.localeCompare(right.persona)" in source
    assert 'opinionVisible={visibleOpinions.has(panel.persona)}' in source
    assert "feedback.input_mode" in source
    assert "<DecisionReport" in source
    assert "reactionDetails={" in source
    assert "evidenceDetails={" in source
    assert "agentDetails={" in source
    assert "result.fallback_used &&" not in source
    assert "ref={decisionHeading}" not in source
```

- [ ] **Step 2: 이벤트 전용 검사가 기존 화면 구조에서 실패하는지 확인한다**

Run: `uv run pytest tests/test_frontend_update_contract.py::test_event_result_maps_contract_to_shared_decision_report -q`

Expected: `DecisionReport`, 제출값 스냅샷, ID 연결 함수와 `opinionVisible` 배선이 없어 FAIL

- [ ] **Step 3: 이벤트 응답 타입과 제출값 스냅샷을 추가한다**

`page.tsx`의 React import에서 결과 초점 전용 `useEffect`, `useRef`를 제거하고 다음 import를 추가한다.

```tsx
import { DecisionReport, DecisionReportData } from "./components/DecisionReport";
```

이벤트 응답 타입을 다음과 같이 좁힌다.

```tsx
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
```

결과 상태 옆에 제출 이벤트명을 보존하고, 요청 시작 시 지역 변수로 고정한 뒤 결과 이벤트에서 함께 저장한다.

```tsx
const [submittedSubject, setSubmittedSubject] = useState(initialForm.event_name);

async function submit(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();
  // 기존 입력 검증은 이 위치보다 먼저 그대로 유지한다.
  const requestSubject = form.event_name.trim() || "이름 없는 이벤트";
  // 기존 요청과 스트림 처리를 그대로 유지한다.
  if (eventName === "result" && message.result) {
    setSubmittedSubject(requestSubject);
    setResult(message.result);
    setLiveEvents(message.result.events);
  }
}
```

설명 주석은 실제 코드에 넣지 않고 기존 검증과 스트림 코드 사이에 지역 변수와 상태 갱신만 추가한다.

- [ ] **Step 4: 이벤트 계약을 보고서 데이터로 바꾸는 순수 함수를 추가한다**

`EventReview` 위에 다음 보조 함수와 변환 함수를 둔다.

```tsx
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
```

- [ ] **Step 5: 기존 이벤트 상세 JSX를 두 슬롯으로 나누고 공통 보고서를 렌더링한다**

기존 `ResultInsights`를 `EventReactionDetails`와 `EventEvidenceDetails`로 나눈다. 첫 함수는 이용자 유형 카드만, 두 번째 함수는 확인된 위험의 파생 요약, 언어권 카드, 우선 개선안만 렌더링한다. 기존 카드 내부 JSX와 안전 문구는 유지하고 이용자 카드에 중복 표시 값을 전달한다.

```tsx
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
```

`EventEvidenceDetails`에는 기존 `확인된 위험`, `언어권별 예상`, `우선 개선안` 섹션을 그 순서로 옮긴다. 위험 카드의 `연결된 파생 요약 보기`, `이용자의 직접 인용이 아닙니다`, `derived-evidence` 요소를 삭제하지 않는다.

`EventEvidenceDetails({ result }: { result: RunResult })` 함수 안에서 `riskTitle` 맵을 선언하고 현재 `page.tsx`의 `확인된 위험`, `언어권별 예상`, `우선 개선안` JSX 블록을 내용 변경 없이 반환한다. 새 빈 상태나 새 데이터 계산을 추가하지 않는다.

기존 결과 전체를 다음 공통 컴포넌트 한 개로 교체한다.

```tsx
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
```

기존 독립 `decision-brief`, `risk-section`, `ResultInsights`, `final-pipeline`, 바깥 `ArtifactDetails` 렌더링은 제거한다. 실행 중 `AgentPipeline events={liveEvents} active mode="event"`는 그대로 둔다.

이 교체와 함께 더 이상 쓰지 않는 `decisionCopy`, `decisionHeading`, `copy`, `visibleLanguages`, `primaryRisk`, `primaryPanel`, `primaryRevision` 선언을 제거한다.

- [ ] **Step 6: 이벤트 보고서 배선과 전체 프론트 계약을 검증한다**

Run: `uv run pytest tests/test_frontend_update_contract.py -q`

Expected: 이벤트의 새 배선 검사와 기존 자료 출처, 날짜, 파이프라인 검사가 모두 PASS

Run: `npm --prefix frontend run build`

Expected: `decision_reason`, 보고서 슬롯과 이용자 카드 속성의 TypeScript 검사 PASS

Run: `git diff --check`

Expected: 공백 오류 없음

- [ ] **Step 7: Task 2 변경 부분만 커밋한다**

```bash
git add -p frontend/app/page.tsx tests/test_frontend_update_contract.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: present event decisions as one-page reports"
```

부분 스테이징에서 제출값 스냅샷, 이벤트 변환 함수, 상세 슬롯, 공통 보고서 렌더링과 해당 테스트만 선택한다.

---

### Task 3: 업데이트 점검을 한 페이지 보고서에 연결하고 최종 검증

**Files:**
- Modify: `frontend/app/components/UpdateReview.tsx`
- Modify: `tests/test_frontend_update_contract.py`

**Interfaces:**
- Consumes: `DecisionReport`, `DecisionReportData`, `PersonaGameCard.opinionVisible`, 업데이트의 `UpdateRunResult`
- Produces: `buildUpdateReport(result: UpdateRunResult, subject: string): DecisionReportData`, `selectUpdatePositive`, `findUpdateRecommendation`, `findUpdateMetric`, 제출 시점 업데이트명 상태

- [ ] **Step 1: 업데이트 보고서의 ID 연결과 제출값 보존을 확인하는 실패 테스트를 작성한다**

`tests/test_frontend_update_contract.py`에 다음 검사를 추가하고 기존 업데이트 결과 검사는 공통 보고서와 세 상세 슬롯을 요구하도록 수정한다.

```python
def test_update_result_maps_ids_to_shared_decision_report():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")

    assert 'import { DecisionReport, DecisionReportData }' in source
    assert "decision_reason: string" in source
    assert "submittedSubject" in source
    assert "const requestSubject = form.update_name.trim()" in source
    assert "setSubmittedSubject(requestSubject)" in source
    assert "function selectUpdatePositive" in source
    assert "function findUpdateRecommendation" in source
    assert "function findUpdateMetric" in source
    assert "top_risks[0]" in source
    assert "addresses_risk_ids.includes(riskId)" in source
    assert "validation_metric_ids" in source
    assert "item.metric_id === metricId" in source
    assert "updateEvidenceCount(item.evidence_ids)" in source
    assert "left.impact_id.localeCompare(right.impact_id)" in source
    assert 'opinionVisible={visibleOpinions.has(item.persona)}' in source
    assert "feedback.input_mode" in source
    assert "<DecisionReport" in source
    assert "reactionDetails={" in source
    assert "evidenceDetails={" in source
    assert "agentDetails={" in source
    assert "result.fallback_used &&" not in source
    assert "ref={decisionHeading}" not in source
```

- [ ] **Step 2: 업데이트 전용 검사가 기존 배열 첫 항목 방식에서 실패하는지 확인한다**

Run: `uv run pytest tests/test_frontend_update_contract.py::test_update_result_maps_ids_to_shared_decision_report -q`

Expected: 제출값 스냅샷, ID 기반 권고안과 지표 연결, 공통 보고서 배선이 없어 FAIL

- [ ] **Step 3: 업데이트 응답 타입과 제출값 스냅샷을 추가한다**

`UpdateReview.tsx`에서 결과 초점 전용 `useEffect`, `useRef` import와 상태를 제거하고 다음 import를 추가한다.

```tsx
import { DecisionReport, DecisionReportData } from "./DecisionReport";
```

`UpdateRunResult`의 `validated`를 다음 타입으로 좁힌다.

```tsx
validated: { decision_reason: string } & Artifact;
```

결과 상태 옆에 제출 업데이트명을 보존하고 요청 지역 변수로 고정한다.

```tsx
const [submittedSubject, setSubmittedSubject] = useState(initial.update_name);

async function submit(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();
  // 기존 입력 검증은 이 위치보다 먼저 그대로 유지한다.
  const requestSubject = form.update_name.trim() || "이름 없는 업데이트";
  // 기존 요청과 스트림 처리를 그대로 유지한다.
  if (eventName === "result" && message.result) {
    setSubmittedSubject(requestSubject);
    setResult(message.result);
    setEvents(message.result.events);
  }
}
```

설명 주석은 실제 코드에 넣지 않고 기존 검증과 요청 처리 사이에 필요한 줄만 추가한다.

- [ ] **Step 4: 업데이트 계약을 보고서 데이터로 바꾸는 순수 함수를 추가한다**

`UpdateReview` 위에 다음 함수를 둔다. 이벤트 파일의 작은 보조 함수를 가져와 공통 추상화하지 않고 업데이트 타입에 맞게 현재 파일 안에서 유지한다.

```tsx
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
```

- [ ] **Step 5: 업데이트 상세 JSX를 두 슬롯으로 나누고 공통 보고서를 렌더링한다**

`UpdateReactionDetails`에는 기존 `출시 전 예상 반응`의 긍정, 부정, 반응이 갈릴 조건과 이용자 유형 카드를 옮긴다. 이용자 유형 카드에 다음 값을 추가한다.

```tsx
const visibleOpinions = visibleUpdateOpinions(result.brief.persona_impacts);

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
```

`UpdateEvidenceDetails`에는 기존 `공식으로 확인된 변경 맥락`, `언어권별 예상`, `출시 후 검증할 지표`, 조건부 `업데이트 후 실제 반응`, `근거와 비식별 의견`을 그 순서로 옮긴다. 공식 자료 링크와 비식별 출처 링크의 안전 속성 `target="_blank" rel="noreferrer"`를 유지한다.

`UpdateEvidenceDetails({ result }: { result: UpdateRunResult })` 함수 안에서 `actualAfter = result.brief.evidence.filter((item) => item.period === "after")`와 위험 제목 맵을 선언한다. 현재 `UpdateReview.tsx`의 `공식으로 확인된 변경 맥락`, `언어권별 예상`, `출시 후 검증할 지표`, 조건부 `업데이트 후 실제 반응`, `근거와 비식별 의견` JSX 블록을 내용 변경 없이 그 순서로 반환한다. `actualAfter`와 위험 제목 맵은 이 상세 함수 안에서만 계산한다.

기존 결과 전체를 다음 공통 컴포넌트 한 개로 교체한다.

```tsx
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
```

기존 독립 `decision-brief`, `official-context`, `reaction-section`, `insight-section`, `metric-section`, `actual-after-section`, `evidence-section`, `final-pipeline`, 바깥 `ArtifactDetails` 렌더링은 제거한다. 실행 중 `AgentPipeline events={events} active mode="update"`는 그대로 둔다.

이 교체와 함께 더 이상 쓰지 않는 `decisionDescriptions`, `decisionHeading`, `actualAfter`, `decision`, `visibleLanguages`, `primaryPositive`, `primaryNegative`, `primaryRisk`, `positiveEvidenceCount`, `negativeEvidenceCount`, `coveredRiskCount`, `riskTitles`, `primaryRecommendation`의 기존 상위 선언을 제거한다. 상세 함수 안으로 옮긴 `actualAfter`와 `riskTitles`만 유지한다.

- [ ] **Step 6: 두 모드가 같은 보고서 계약과 중복 방지 규칙을 사용하는지 최종 소스 검사를 추가한다**

기존 `test_both_result_modes_expose_complete_decision_brief`와 `test_both_modes_use_shared_collectible_audience_cards`를 다음 핵심 검사로 바꾼다.

```python
def test_both_result_modes_use_one_page_report_without_duplicate_top_sections():
    event_source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    update_source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")
    report_source = (ROOT / "components" / "DecisionReport.tsx").read_text(encoding="utf-8")

    for source in (event_source, update_source):
        assert "<DecisionReport" in source
        assert "analysisIncomplete: result.analysis_incomplete" in source
        assert "decision_reason" in source
        assert "executive_summary" in source
        assert "opinionVisible=" in source
        assert 'mode="' in source
        assert 'active mode=' in source
        assert 'className="decision-brief"' not in source
        assert 'className="final-pipeline"' not in source
    assert "실제 이용자 인용이 아닙니다" in report_source


def test_one_page_report_copy_has_no_middle_dots():
    for path in (
        ROOT / "components" / "DecisionReport.tsx",
        ROOT / "page.tsx",
        ROOT / "components" / "UpdateReview.tsx",
        ROOT / "components" / "AudienceCards.tsx",
    ):
        assert "·" not in path.read_text(encoding="utf-8")
```

`active mode=` 검사는 실행 중 파이프라인이 남아 있음을, 일반 `mode=` 검사는 결과 상세에 파이프라인이 전달됨을 확인한다.

- [ ] **Step 7: 전체 프론트 계약과 프로덕션 빌드를 실행한다**

Run: `uv run pytest tests/test_frontend_update_contract.py -q`

Expected: 모든 프론트 소스 배선 검사 PASS

Run: `npm --prefix frontend run build`

Expected: TypeScript 검사, 정적 페이지 생성과 Next.js 프로덕션 빌드 PASS

Run: `git diff --check`

Expected: 공백 오류 없음

- [ ] **Step 8: 외부 API 없이 네 가지 결과와 두 화면 폭을 수동 확인한다**

백엔드와 프론트엔드를 서로 다른 터미널에서 실행한다.

터미널 1:

```bash
uv run --env-file backend/.env uvicorn backend.app.main:app --port 8000
```

터미널 2:

```bash
npm --prefix frontend run dev
```

브라우저에서 Claude 보강을 끈 상태로 다음 순서로 확인한다.

1. 이벤트 점검의 `Weekly Supply` 저장 사례로 `Go` 보고서를 확인한다.
2. 이벤트 점검의 `Black Market 2025` 저장 사례로 `Revise` 보고서를 확인한다.
3. 업데이트 점검의 `Dragunov 확률 피해 제거` 저장 사례로 `Test` 또는 현재 정책의 결정론적 판정을 확인한다.
4. 아래 임시 코퍼스 절차로 `analysis_incomplete=true`인 `Hold` 보고서를 확인한다.

네 번째 시나리오에서는 정상 백엔드를 중지한 뒤 원본 코퍼스를 건드리지 않는 임시 복사본을 만든다.

```bash
DEMO_REPORT_ROOT="$(mktemp -d)"
mkdir -p "$DEMO_REPORT_ROOT/.data/corpus"
cp .data/corpus/pubg_steam.sqlite3 "$DEMO_REPORT_ROOT/.data/corpus/pubg_steam.sqlite3"
sqlite3 "$DEMO_REPORT_ROOT/.data/corpus/pubg_steam.sqlite3" \
  "DELETE FROM evidence WHERE language='ko' AND rowid NOT IN (SELECT rowid FROM evidence WHERE language='ko' LIMIT 10); DELETE FROM evidence WHERE language='en' AND rowid NOT IN (SELECT rowid FROM evidence WHERE language='en' LIMIT 10);"
DEMO_REPORT_ROOT="$DEMO_REPORT_ROOT" uv run python -c 'import os; from pathlib import Path; import uvicorn; import backend.app.main as main; main.ROOT = Path(os.environ["DEMO_REPORT_ROOT"]); uvicorn.run(main.app, host="127.0.0.1", port=8000)'
```

브라우저에서 이벤트 점검의 `사전 구축 Steam 코퍼스`를 선택하고 `코퍼스 데모 날짜 적용`을 누른 뒤 Claude 보강을 끄고 실행한다. 임시 DB는 한국어와 영어의 관련 근거가 각각 최대 10건이므로 코퍼스 표본 기준에 미달하고, 실제 운영 DB를 바꾸지 않은 채 `analysis_incomplete=true`와 `Hold`를 만든다. 확인을 마친 뒤 임시 백엔드를 중지하고 임시 폴더 경로를 확인한 후 삭제한다.

각 결과에서 다음을 확인한다.

- 1440×900에서 결과로 초점이 이동하고 헤더, 세 핵심 카드, 위험 표가 첫 화면에 보인다.
- 390픽셀에서 세 카드와 각 표 행이 한 열로 쌓이고 페이지 가로 스크롤이 생기지 않는다.
- 가장 큰 위험과 같은 ID를 참조하는 조치와 확인 지표가 표시된다.
- 결과를 받은 뒤 입력명을 수정해도 보고서 제목이 바뀌지 않는다.
- 같은 대표 의견은 근거 수와 일치도가 높은 이용자 카드 한 곳에만 나타난다.
- `analysis_incomplete=false`인 대체 처리 결과는 상단 경고를 만들지 않는다.
- 세 상세 영역은 기본 접힘이며 펼치면 언어권, 비식별 근거, 에이전트 과정과 계약 JSON을 확인할 수 있다.

- [ ] **Step 9: Task 3 변경 부분만 커밋한다**

```bash
git add -p frontend/app/components/UpdateReview.tsx tests/test_frontend_update_contract.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: present update decisions as one-page reports"
```

부분 스테이징에서 업데이트 응답 타입, 제출값 스냅샷, ID 연결 함수, 상세 슬롯, 공통 보고서 렌더링과 해당 테스트만 선택한다.

- [ ] **Step 10: 커밋 이후 최종 회귀를 확인한다**

```bash
uv run pytest tests/test_frontend_update_contract.py -q
npm --prefix frontend run build
git diff --check
git status --short
```

Expected: 테스트와 빌드가 통과하고 공백 오류가 없으며, `git status --short`에는 구현 전부터 존재한 사용자 변경만 남는다.
