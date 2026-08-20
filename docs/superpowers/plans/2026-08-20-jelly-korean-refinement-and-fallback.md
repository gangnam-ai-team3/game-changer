# Jelly Korean Refinement and Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jelly의 한국어 표현을 Res가 차단 대신 편집하고, 완전한 핵심 분석에서 부가 에이전트 실패가 최종 판정을 `Hold`로 바꾸지 않게 한다.

**Architecture:** 기존 Jelly 어댑터에 결정론적 한국어 편집 경계를 두고, 의미 계약과 문체 규칙을 분리한다. 업데이트 오케스트레이터는 수집 및 근거 부족만 `analysis_incomplete`로 처리하고, Jelly 실패는 해당 단계의 결정론 결과로 대체한 뒤 승진배 에이전트를 계속 실행한다.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, pytest, Node.js 24, Anthropic Messages API

**Spec:** `docs/specs/2026-08-20-jelly-korean-refinement-and-fallback-design.md`

## Global Constraints

- 새 패키지를 추가하지 않고 Python 표준 라이브러리와 기존 의존성만 사용한다.
- `claude-sonnet-5`는 Jelly와 승진배 에이전트에, `claude-haiku-4-5-20251001`은 페르소나 문구 편집에 사용한다.
- 한 실행의 Claude 호출 예산은 하나의 `ClaudeBudget(max_requests=3)`로 공유한다.
- API 키, Steam 원문, 공급자의 상세 오류 메시지를 이벤트, JSONL, 결과 계약에 남기지 않는다.
- Jelly 문장 편집은 판정, 위험 ID, 위험 등급, 근거 ID, 신뢰도를 바꾸지 않는다.
- 가운뎃점을 포함한 문체 문제는 편집하고, 행 누락, 잘못된 분류값, 응답 구조 훼손은 계약 실패로 거부한다.
- 수집 실패, 빈 근거, 표본 미달은 기존 `Hold` 정책을 유지한다.
- 결과 화면 재설계는 이 계획에 포함하지 않는다.

---

### Task 1: Jelly 응답을 차단 대신 편집하기

**Files:**
- Modify: `res/team_adapters.py:31-301`
- Modify: `jelly/call-agent.js:106-153`
- Test: `tests/test_team_adapters.py`

**Interfaces:**
- Consumes: Jelly 구조화 응답 `{rows, synthesis}`와 코드가 확정한 `RiskItem` 또는 `UpdateRiskItem` 목록
- Produces: `_edit_jelly_sentence(value: str, fallback: str) -> str`, `_validated_jelly_trends(result: dict, risks) -> dict[str, int]`

- [ ] **Step 1: 가운뎃점과 빈 문장이 편집되는 실패 테스트 작성**

```python
def test_jelly_refines_style_and_fills_empty_prose_without_changing_risks():
    brief = load_dragunov_brief("jelly-refinement")
    baseline = UpdateReviewOrchestrator().run(brief)
    response = _jelly_result(len(baseline.impact.risks))
    response["rows"][0]["cause"] = "피해량·반동·연사력을 같이 확인해야 함"
    response["rows"][0]["fix"] = ""
    runner = FakeJellyRunner(response)

    impact = UpdateJellyRedteamAdapter(runner=runner, enabled=True).run(
        brief, baseline.evidence
    )

    assert impact == baseline.impact
    assert len(runner.calls) == 1
```

- [ ] **Step 2: 편집 테스트가 현재 실패하는지 확인**

Run: `uv run pytest -q tests/test_team_adapters.py::test_jelly_refines_style_and_fills_empty_prose_without_changing_risks`

Expected: `StructuredModelError` with `Jelly 결과 계약을 검증하지 못했습니다.`

- [ ] **Step 3: 최소 한국어 편집 함수 구현**

```python
def _edit_jelly_sentence(value: str, fallback: str) -> str:
    text = value.strip() or fallback.strip()
    if not re.search(r"[가-힣]", text):
        text = fallback.strip()
    replacements = {
        "·": ", ",
        "본질적으로": "",
        "궁극적으로": "",
        "실질적으로": "",
        "이유는 명확": "근거를 보면",
        "혁신적인 변화": "주요 변화",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if text and not re.search(r"[.!?]$", text):
        text += "."
    return text
```

`_validated_jelly_trends` 인자를 `count`에서 `risks`로 바꾸고, 각 행의 `cause`는 `risk.failure_path`, `fix`는 `risk.revision_question`을 대체 문장으로 사용한다. 다듬은 문장에만 `require_native_business_korean`을 적용하고, 행 번호와 동향값은 기존처럼 엄격히 검증한다.

- [ ] **Step 4: Jelly 입력 규칙을 편집 경계와 맞춤**

`res/team_adapters.py` 와 `jelly/call-agent.js` 두 곳의 중복 프롬프트에 다음 문장을 동일하게 적용한다.

```text
원인과 개선 방향은 비우지 말고 완전한 한국어 문장으로 작성하십시오. 가운뎃점은 쓰지 말고 쉼표나 자연스러운 연결 표현을 사용하십시오.
```

- [ ] **Step 5: 응답 구조 실패와 외부 호출 실패 구분**

```python
if completed is None or completed.returncode != 0:
    raise _team_unavailable("Jelly")
try:
    result = json.loads(completed.stdout)
except (TypeError, json.JSONDecodeError):
    raise _jelly_schema_error() from None
if type(result) is not dict:
    raise _jelly_schema_error()
```

`_run_jelly` 안에서 `_validated_jelly_trends`가 낸 `SCHEMA_INVALID`를 `SOURCE_UNAVAILABLE`로 바꾸는 `try/except`는 제거한다. 외부 호출 상세 메시지는 계속 버린다.

- [ ] **Step 6: 의미 계약 회귀 테스트 추가**

```python
@pytest.mark.parametrize("indexes", ([0, 0], [0, 2]))
def test_jelly_still_rejects_duplicate_or_unknown_indexes(indexes):
    event = load_demo_event("jelly-index-contract")
    baseline = EventPreflightOrchestrator().run(event)
    result = _jelly_result(len(baseline.risks.risks))
    for row, index in zip(result["rows"], indexes, strict=False):
        row["index"] = index
    runner = FakeJellyRunner(result)

    with pytest.raises(StructuredModelError) as caught:
        EventJellyRedteamAdapter(runner=runner, enabled=True).run(
            event, baseline.evidence
        )

    assert caught.value.code is ErrorCode.SCHEMA_INVALID
```

- [ ] **Step 7: Jelly 어댑터 테스트 실행**

Run: `uv run pytest -q tests/test_team_adapters.py`

Expected: all tests pass.

- [ ] **Step 8: Task 1 커밋**

```bash
git add res/team_adapters.py jelly/call-agent.js tests/test_team_adapters.py
git commit -m "fix: refine Jelly Korean output safely"
```

### Task 2: 부가 에이전트 실패 후에도 판정 계속하기

**Files:**
- Modify: `update_review/orchestrator.py:37-263`
- Modify: `backend/app/main.py:136-270`
- Test: `tests/test_api_team_wiring.py`
- Test: `tests/test_update_pipeline.py`

**Interfaces:**
- Consumes: `ClaudeBudget(max_requests=3)`, `StructuredModelError`, 코퍼스 `UpdateFeedbackBundle`
- Produces: `UpdateReviewOrchestrator(..., budget: ClaudeBudget | None = None)`, 단계별 결정론 대체 결과, 수집 상태로만 계산한 `analysis_incomplete`

- [ ] **Step 1: Jelly 실패 후 승진배 에이전트가 계속되는 실패 테스트로 기존 정책 고정**

```python
def test_update_corpus_team_jelly_failure_uses_fallback_and_continues_audit(
    monkeypatch, tmp_path
):
    jelly_calls, probe_calls = [], []

    class FailingJellyRunner:
        def __init__(self, *, budget):
            self.budget = budget

        def run(self, rows):
            jelly_calls.append(rows)
            raise StructuredModelError(ErrorCode.SOURCE_UNAVAILABLE, "safe")

    class GroundedJinbaeProbe:
        def __init__(self, *, budget):
            self.budget = budget

        def run(self, claim_text, candidate_chunks):
            probe_calls.append((claim_text, candidate_chunks))
            return {
                "verdict": "grounded",
                "citations": [item["id"] for item in candidate_chunks],
                "rationale": "근거 ID 연결을 확인했습니다.",
            }

    monkeypatch.setattr(api_main, "ROOT", tmp_path)
    monkeypatch.setattr(api_main, "UpdateCorpusCollector", _FixtureCorpusCollector)
    monkeypatch.setattr(api_main, "JellyRunner", FailingJellyRunner)
    monkeypatch.setattr(api_main, "JinbaeProbe", GroundedJinbaeProbe)

    result = api_main._run_update(
        _request("update", use_llm=True), "jelly-fallback-continues"
    )

    assert len(jelly_calls) == 1
    assert len(probe_calls) == 1
    assert result.fallback_used is True
    assert result.analysis_incomplete is False
    assert result.brief.decision.value == "Revise"
```

- [ ] **Step 2: 정책 테스트가 현재 `Hold`로 실패하는지 확인**

Run: `uv run pytest -q tests/test_api_team_wiring.py::test_update_corpus_team_jelly_failure_uses_fallback_and_continues_audit`

Expected: `probe_calls == []`, `analysis_incomplete is True`, or decision `Hold` assertion failure.

- [ ] **Step 3: 오케스트레이터에 공유 예산 주입 경로 추가**

```python
def __init__(
    self,
    *,
    collector=None,
    evidence=None,
    redteam=None,
    audit=None,
    use_llm: bool = False,
    llm_client=None,
    budget: ClaudeBudget | None = None,
) -> None:
    budget = budget if budget is not None else (ClaudeBudget() if use_llm else None)
```

`backend/app/main.py` 코퍼스 팀 경로에서 동일한 `budget`을 페르소나 편집, Jelly, 승진배 에이전트와 `UpdateReviewOrchestrator` 모두에 전달한다.

```python
team = {
    "budget": budget,
    "evidence": UpdateEvidenceAgent(rewrite_personas=True, budget=budget),
    "redteam": UpdateJellyRedteamAdapter(runner=runner, enabled=True),
    "audit": UpdateJinbaeAuditAdapter(probe=probe, enabled=True),
}
```

- [ ] **Step 4: 단계 실패를 해당 단계에서만 대체하도록 수정**

`stage` 함수의 `StructuredModelError` 처리에서 다음 두 코드를 제거한다.

```python
force_deterministic = True
analysis_incomplete = True
```

호출 실패 단계는 `deterministic_call()`로 대체하되, 다음 단계의 `allow_llm` 판정은 유지한다. `force_deterministic=True`는 수집 결과의 오류, 빈 근거, 표본 미달을 확인한 후에만 설정한다.

- [ ] **Step 5: 실제 수집 실패 `Hold` 회귀 테스트 유지**

`tests/test_update_sources.py::test_live_failure_never_substitutes_dragunov_fixture`를 수정하지 않고 그대로 실행해, Steam 수집 실패에서 다음 단언이 유지되는지 확인한다.

```python
assert result.feedback.status is ArtifactStatus.PARTIAL
assert result.feedback.evidence == []
assert result.brief.decision is UpdateDecision.HOLD
assert result.analysis_incomplete is True
```

Run: `uv run pytest -q tests/test_update_sources.py::test_live_failure_never_substitutes_dragunov_fixture`

Expected: pass.

- [ ] **Step 6: 업데이트 오케스트레이터와 API 팀 연결 테스트 실행**

Run: `uv run pytest -q tests/test_api_team_wiring.py tests/test_update_pipeline.py tests/test_team_adapters.py`

Expected: all tests pass.

- [ ] **Step 7: Task 2 커밋**

```bash
git add update_review/orchestrator.py backend/app/main.py tests/test_api_team_wiring.py tests/test_update_pipeline.py
git commit -m "fix: continue update review after sidecar fallback"
```

### Task 3: 전체 회귀와 실제 팀 에이전트 실행 확인

**Files:**
- Verify: `.data/runs/<run_id>.jsonl`
- Verify: `frontend/app/components/AgentPipeline.tsx`
- Verify: `frontend/app/components/UpdateReview.tsx`

**Interfaces:**
- Consumes: 실제 `ANTHROPIC_API_KEY`, 사전 구축 PUBG Steam 코퍼스, Dragunov 업데이트 입력
- Produces: Haiku 페르소나 편집 → Jelly Sonnet 5 점검 → 승진배 Sonnet 5 근거 검증 → 정책 판정의 순차 실행 증거

- [ ] **Step 1: Python 전체 회귀 실행**

Run: `uv run pytest -q`

Expected: all tests pass with no new warning category.

- [ ] **Step 2: 기존 이벤트와 업데이트 성공 게이트 실행**

Run: `uv run python -m evaluation.verify_success`

Expected: JSON output contains `"passed": true`.

Run: `uv run python -m evaluation.verify_update_success`

Expected: JSON output contains `"passed": true`.

- [ ] **Step 3: 프론트엔드 생산 빌드 실행**

Run: `npm --prefix frontend run build`

Expected: Next.js production build completes successfully.

- [ ] **Step 4: 실제 코퍼스 팀 점검 1회 실행**

`http://localhost:3000`에서 업데이트 점검, 사전 구축 Steam 코퍼스, 팀 에이전트 추가 검증을 선택하고 Dragunov 업데이트를 실행한다.

Expected execution nodes in order:

```text
persona_copy_checked
jelly_sidecar_started
jelly_output_checked
jinbae_probe_started
jinbae_probe_checked
decision_fixed
```

- [ ] **Step 5: 실제 실행 JSONL에서 판정과 비노출 경계 확인**

Run: `rg -n 'persona_copy_checked|jelly_output_checked|jinbae_probe_checked|decision_fixed|SOURCE_UNAVAILABLE|AUTH_FAILED' .data/runs/<run_id>.jsonl`

Expected: the four completion markers and `decision_fixed` are present; `SOURCE_UNAVAILABLE` and `AUTH_FAILED` are absent.

Run: `rg -n 'ANTHROPIC_API_KEY|sk-ant|steamid|recommendationid' .data/runs/<run_id>.jsonl`

Expected: no output.

- [ ] **Step 6: 실제 판정 일관성 확인**

Expected result:

```text
analysis_incomplete=false
fallback_used=false
판정=일부 수정 후 출시(Revise)
위험=높음 3개, 보통 1개
확인 지표 연결=4/4
```

실제 Jelly 호출이 외부 요인으로 실패하면 `fallback_used=true`, `analysis_incomplete=false`, 승진배 호출 시도, `Revise` 유지를 확인한다.

- [ ] **Step 7: 실행 결과 요약**

다음 내용을 사용자에게 보고한다.

```text
Jelly 실제 호출 성공 여부
승진배 에이전트 후속 실행 여부
최종 판정과 근거 수
사용한 호출 횟수와 대체 경로 여부
전체 회귀, 성공 게이트, 프론트엔드 빌드 결과
```
