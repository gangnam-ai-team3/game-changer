# 모양 견본

> 지난 결과의 형식을 옮겨 둔 자리입니다. 아래 값은 이번 실행 결과가 아닙니다.

## EvidencePack

```yaml
run_id: <같은 실행의 ID>
schema_version: "1.0"
status: complete | partial | failed
producer: evidence_rag
input_refs:
  - <FeedbackBundle 참조>
errors: []
issues:
  - issue_id: <이슈 ID>
    category: <구조화된 위험 범주>
    title: <반복 이슈 제목>
    evidence_ids: [<근거 ID>]
    confidence: <0~1>
language_insights:
  - language: <언어권>
    conclusion: <충분할 때만 작성>
    hidden_reason: <숨긴 경우 이유>
    evidence_ids: [<근거 ID>]
personas: []
```

## DecisionBrief

```yaml
decision: Go | Revise | Hold
executive_summary: <한 문장 요약>
top_risks: []
language_results: []
panel_results: []
evidence: []
revision_plan: []
```
