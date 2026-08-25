# 게임체인저 통제형 하이브리드 멀티에이전트 MVP 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 Black Market 입력을 네 에이전트가 실제로 순차 처리하고, 핵심 근거·위험·판정은 재현하면서 실행 과정과 최종 결과를 명확히 보여주는 Streamlit MVP를 팀 저장소에 완성한다.

**Architecture:** `event-preflight`의 검증된 Python 프로토타입을 팀 저장소 루트에 그대로 통합한 뒤, LLM은 근거 기반 해석과 설명 후보만 만들고 코드가 의미 검증·위험 등급·수정안 연결·최종 판정을 소유하도록 좁힌다. 오케스트레이터가 네 에이전트의 실행 이벤트와 산출물을 기록하며, Streamlit은 실행 중 모든 카드를 펼치고 완료 후 최종 판정과 접힌 추적 기록으로 전환한다.

**Tech Stack:** Python 3.12, Pydantic v2, OpenAI Responses API 구조화 출력, Streamlit, Python 표준 라이브러리, pytest, uv, GitHub Actions

## Global Constraints

- 구현은 `main`이 아닌 `feat/20260812-res-controlled-hybrid-mvp` 브랜치에서 진행한다.
- 작업은 주차별로 기다리지 않고, 앞선 의존성이 통과하면 즉시 다음 작업으로 이동한다.
- 팀 저장소 `game-changer`가 유일한 기준 코드다. `event-preflight`는 기준 커밋을 가져오는 출처로만 쓴다.
- 기준 프로토타입 커밋은 `32bc7ca2ebd9947caee7f7d059d6964f3e3d6afc`이다.
- `.claude/agents/*.md`, `hy/`, `jelly/`, `res/`, `seungjinbae/`, `TEAM.md`는 수정하지 않는다.
- 기존 `README.md`를 덮어쓰지 않고 서비스 실행 안내만 추가한다.
- Python은 `>=3.12,<3.13`을 유지한다.
- 새 런타임 의존성을 추가하지 않는다. LangGraph, 벡터DB, WebSocket, 별도 API 서버를 도입하지 않는다.
- 저장 fixture가 기본 시연 경로이며, Steam 실제 갱신과 승인 CSV는 별도 입력 경로다.
- 커뮤니티 원문, 사용자명, 개인정보, API 키를 Git이나 JSONL 실행 기록에 저장하지 않는다.
- 동일 입력에서는 근거 ID, 위험 범주·등급, 승인·기각, 최종 판정, 위험–수정안 연결이 같아야 한다.
- `run_id`, 실행 시간, LLM 문장 표현은 재현성 비교에서 제외한다.
- LLM은 `run_id`, 생산자, 입력 참조, 위험 등급, 최종 판정을 작성하지 않는다.
- 실행 시각화를 위해 인위적인 `sleep`을 넣지 않는다.
- 외부 Steam/OpenAI 호출은 CI 테스트에서 가짜 클라이언트로 대체한다. 실제 Steam 호출은 명시적인 smoke 명령에서만 실행한다.
- 각 작업은 실패 테스트 확인, 최소 구현, 관련 테스트 통과, 독립 커밋 순서로 끝낸다.

## Source and Target File Map

### 기준 코드로 가져올 파일

- 프로젝트 설정: `.gitignore`, `.python-version`, `pyproject.toml`, `requirements.txt`, `uv.lock`
- CI·배포: `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `.streamlit/config.toml`, `.streamlit/secrets.toml.example`
- 루트 실행 코드: `contracts.py`, `orchestrator.py`, `streamlit_app.py`
- 에이전트: `agents/__init__.py`, `agents/structured.py`, `agents/collector/*`, `agents/evidence_rag/*`, `agents/event_redteam/*`, `agents/audit_strategy/*`
- 커넥터: `connectors/__init__.py`, `connectors/importer/*`, `connectors/steam/*`, `connectors/x/*`
- fixture·평가: `fixtures/*`, `evaluation/__init__.py`, `evaluation/fixtures.py`, `evaluation/backtest.py`, `evaluation/verify_success.py`, `evaluation/black_market_2025_ground_truth.json`
- 테스트: `tests/conftest.py`와 기존 `tests/test_*.py` 10개

### 가져오지 않을 파일

- `event-preflight/.git/`, `.venv/`, `.data/`, `.ruff_cache/`, `.pytest_cache/`, `__pycache__/`, `*.pyc`, `.DS_Store`
- 실제 `.streamlit/secrets.toml`, `.env`
- 사용자 변경이 섞인 `event-preflight/docs/**`
- 대상 저장소와 충돌하는 `event-preflight/README.md`
- 현재 실행 경로에서 사용하지 않는 `evaluation/baseline.py`, `evaluation/baseline_prompt.md`

### 최종 파일 책임

- `contracts.py`: 저장 산출물과 참조 무결성 계약
- `policy.py`: 닫힌 위험 분류, 등급, 판정, 수정안의 단일 진실 공급원
- `execution.py`: 실행 단계·상태·이벤트·콜백 타입
- `agents/*`: 에이전트별 결정론적 핵심 처리와 제한된 LLM 설명 보강
- `orchestrator.py`: 순서, 재시도, 안전 경로, 해시, 이벤트 기록, 브리프 조립
- `ui_state.py`: 실행 이벤트를 화면 상태로 바꾸는 순수 함수와 세션 초기화
- `streamlit_app.py`: 입력, 실시간 실행 카드, 완료 화면, 추적 펼치기
- `scripts/smoke_steam.py`: 발표 전 실제 Steam 조회 확인
- `evaluation/*`: 회고형 평가와 최종 성공 게이트
- `tests/*`: 계약, 정책, 에이전트, 오케스트레이터, UI의 자동 검증

---

### Task 1: 검증된 프로토타입을 팀 저장소에 기준선으로 통합

**Files:**
- Create: `.gitignore`
- Create: `.python-version`
- Create: `.github/workflows/ci.yml`
- Create: `.github/pull_request_template.md`
- Create: `.streamlit/config.toml`
- Create: `.streamlit/secrets.toml.example`
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `uv.lock`
- Create: `contracts.py`
- Create: `orchestrator.py`
- Create: `streamlit_app.py`
- Create: `agents/__init__.py`
- Create: `agents/structured.py`
- Create: `agents/collector/__init__.py`
- Create: `agents/collector/agent.py`
- Create: `agents/collector/prompt.md`
- Create: `agents/evidence_rag/__init__.py`
- Create: `agents/evidence_rag/agent.py`
- Create: `agents/evidence_rag/retrieval.py`
- Create: `agents/evidence_rag/prompt.md`
- Create: `agents/event_redteam/__init__.py`
- Create: `agents/event_redteam/agent.py`
- Create: `agents/event_redteam/prompt.md`
- Create: `agents/audit_strategy/__init__.py`
- Create: `agents/audit_strategy/agent.py`
- Create: `agents/audit_strategy/prompt.md`
- Create: `connectors/__init__.py`
- Create: `connectors/importer/__init__.py`
- Create: `connectors/importer/csv_importer.py`
- Create: `connectors/steam/__init__.py`
- Create: `connectors/steam/client.py`
- Create: `connectors/x/__init__.py`
- Create: `connectors/x/client.py`
- Create: `evaluation/__init__.py`
- Create: `evaluation/fixtures.py`
- Create: `evaluation/backtest.py`
- Create: `evaluation/verify_success.py`
- Create: `evaluation/black_market_2025_ground_truth.json`
- Create: `fixtures/black_market_2025.jsonl`
- Create: `fixtures/import_template.csv`
- Create: `tests/conftest.py`
- Create: `tests/test_agents.py`
- Create: `tests/test_connectors.py`
- Create: `tests/test_contracts.py`
- Create: `tests/test_importer.py`
- Create: `tests/test_non_goals.py`
- Create: `tests/test_orchestrator.py`
- Create: `tests/test_retrieval.py`
- Create: `tests/test_streamlit_app.py`
- Create: `tests/test_structured_api.py`
- Create: `tests/test_success_gate.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: sibling 저장소 `../event-preflight`의 Git 객체 `32bc7ca2ebd9947caee7f7d059d6964f3e3d6afc`
- Produces: `EventPreflightOrchestrator.run(EventBrief, CollectionOptions) -> PipelineResult`, `streamlit_app.py`, 23개 기준 테스트

- [ ] **Step 1: 승인된 설계 커밋에서 구현 브랜치 생성**

Run:

```bash
git status --short
git switch -c feat/20260812-res-controlled-hybrid-mvp
git branch --show-current
```

Expected: 설계·계획 문서 외 예상하지 않은 변경이 없고 마지막 출력이
`feat/20260812-res-controlled-hybrid-mvp`다.

- [ ] **Step 2: 대상 저장소가 기준 런타임 파일을 아직 갖고 있지 않은지 확인**

Run:

```bash
test ! -e contracts.py
test ! -e agents
test ! -e connectors
test ! -e tests
git status --short
```

Expected: 네 `test` 명령이 성공하고, 승인된 설계·계획 외에 예상하지 않은 변경이 없다.

- [ ] **Step 3: dirty working tree가 아닌 기준 커밋에서 선별 파일만 가져오기**

Run:

```bash
git -C ../event-preflight archive 32bc7ca2ebd9947caee7f7d059d6964f3e3d6afc \
  .gitignore .python-version .github .streamlit \
  pyproject.toml requirements.txt uv.lock contracts.py orchestrator.py streamlit_app.py \
  agents connectors \
  evaluation/__init__.py evaluation/fixtures.py evaluation/backtest.py \
  evaluation/verify_success.py evaluation/black_market_2025_ground_truth.json \
  fixtures tests | tar -x -C .
```

Expected: 기준 커밋의 추적 파일만 생성되고 `docs/`, 실행 로그, 캐시, 실제 secrets는 복사되지 않는다.

- [ ] **Step 4: 기존 협업 README 아래에 서비스 실행 안내 추가**

Append this exact section to `README.md`:

~~~~markdown
## 게임체인저 서비스 실행

현재 MVP는 PUBG: BATTLEGROUNDS Black Market 사례를 네 에이전트가 순차 분석합니다.
기본 경로는 검증된 합성 입력을 사용하며, 결과를 미리 저장해 재생하지 않습니다.

```bash
uv sync --extra dev --locked
uv run pytest
uv run python -m evaluation.verify_success
uv run streamlit run streamlit_app.py
```

실시간 연결은 `.streamlit/secrets.toml.example`을 참고해 로컬 secrets를 설정합니다.
실제 secrets와 커뮤니티 원문은 Git에 추가하지 않습니다.
~~~~

- [ ] **Step 5: 잠금 파일 그대로 Python 환경 구성**

Run:

```bash
uv sync --extra dev --locked
```

Expected: Python 3.12 환경이 생성되고 lockfile 변경이 없다.

- [ ] **Step 6: 기준 테스트가 그대로 통과하는지 확인**

Run:

```bash
uv run pytest
```

Expected: `23 passed`.

- [ ] **Step 7: 성공 게이트와 Streamlit import 확인**

Run:

```bash
uv run python -m evaluation.verify_success
uv run python -c "import streamlit_app"
```

Expected: 성공 보고서의 `passed`가 `true`, fixture 판정은 `Revise`, Streamlit import는 예외 없이 종료한다.

- [ ] **Step 8: 금지 파일이 추적되지 않는지 확인**

Run:

```bash
git status --short
git check-ignore .data/example.jsonl .streamlit/secrets.toml .env
```

Expected: `.data`, 실제 secrets, `.env`가 모두 ignore 대상으로 출력되고, `.claude/agents`와 멤버 폴더에는 변경이 없다.

- [ ] **Step 9: 기준선 커밋**

```bash
git add .gitignore .python-version .github .streamlit pyproject.toml requirements.txt uv.lock \
  contracts.py orchestrator.py streamlit_app.py agents connectors evaluation fixtures tests README.md
git commit -m "Import verified Game Changer prototype baseline" \
  -m "Source: event-preflight@32bc7ca2ebd9947caee7f7d059d6964f3e3d6afc"
```

---

### Task 2: 결정론적 정책을 한 파일로 고정

**Files:**
- Create: `policy.py`
- Create: `tests/test_policy.py`
- Modify: `agents/event_redteam/agent.py:19-57,76-106`
- Modify: `agents/audit_strategy/agent.py:24-53,80-139`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `LanguageSample`, `RiskItem`, `RiskCategory`, `Severity`, `Decision`
- Produces: `POLICY_VERSION: str`, `RISK_SPECS`, `REVISION_SPECS`, `expected_severity(category)`, `decide(samples, risks, analysis_incomplete=False)`

- [ ] **Step 1: 판정 우선순위를 고정하는 실패 테스트 작성**

Add `tests/test_policy.py`:

```python
import pytest

from contracts import Decision, Language, LanguageSample, PersonaKind, RiskCategory, RiskItem, Severity
from policy import POLICY_VERSION, decide, expected_severity


def sample(language: Language, sufficient: bool = True) -> LanguageSample:
    return LanguageSample(
        language=language,
        general_count=100 if sufficient else 99,
        mechanism_count=15 if sufficient else 14,
    )


def risk(severity: Severity) -> RiskItem:
    return RiskItem(
        risk_id=f"risk-{severity.value.lower()}",
        category=RiskCategory.DOUBLE_GACHA,
        title="위험",
        severity=severity,
        affected_personas=[PersonaKind.VALUE_SEEKING],
        affected_languages=[Language.ENGLISH],
        evidence_ids=["evidence-1"],
        failure_path="실패 경로",
        revision_question="무엇을 바꿀 것인가?",
        confidence=0.8,
    )


@pytest.mark.parametrize(
    ("insufficient", "risks", "analysis_incomplete", "expected"),
    [
        (0, [risk(Severity.CRITICAL)], False, Decision.HOLD),
        (3, [], False, Decision.HOLD),
        (0, [risk(Severity.HIGH)], False, Decision.REVISE),
        (1, [], False, Decision.REVISE),
        (0, [], False, Decision.GO),
        (0, [], True, Decision.HOLD),
    ],
)
def test_decision_policy_table(insufficient, risks, analysis_incomplete, expected):
    samples = [sample(language, index >= insufficient) for index, language in enumerate(Language)]
    decision, reason = decide(samples, risks, analysis_incomplete=analysis_incomplete)
    assert decision == expected
    assert reason


def test_closed_policy_version_and_severity():
    assert POLICY_VERSION == "1.0"
    assert expected_severity(RiskCategory.DOUBLE_GACHA) == Severity.HIGH
    assert expected_severity(RiskCategory.EXPIRING_CURRENCY) == Severity.MEDIUM
    assert expected_severity(RiskCategory.FAIRNESS) is None
```

- [ ] **Step 2: 테스트가 정책 모듈 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_policy.py -v
```

Expected: `ModuleNotFoundError: No module named 'policy'`.

- [ ] **Step 3: 기존 두 에이전트의 정책 상수와 판정 함수를 `policy.py`로 이동**

Create these declarations in `policy.py`, and move the current `RISK_SPECS` and `REVISION_SPECS` mappings into the same file without changing their Korean copy:

```python
from contracts import Decision, LanguageSample, RiskCategory, RiskItem, Severity

POLICY_VERSION = "1.0"
MIN_GENERAL_SAMPLE = 100
MIN_MECHANISM_SAMPLE = 15
MIN_PERSONA_EVIDENCE = 15
MIN_RISK_CONFIDENCE = 0.5

CLOSED_RISK_SEVERITY = {
    RiskCategory.DOUBLE_GACHA: Severity.HIGH,
    RiskCategory.FRAGMENTED_FLOW: Severity.HIGH,
    RiskCategory.OPAQUE_PROGRESS: Severity.HIGH,
    RiskCategory.RANDOM_BONUS: Severity.HIGH,
    RiskCategory.EXPIRING_CURRENCY: Severity.MEDIUM,
}


def expected_severity(category: RiskCategory) -> Severity | None:
    return CLOSED_RISK_SEVERITY.get(category)


def decide(
    samples: list[LanguageSample],
    risks: list[RiskItem],
    *,
    analysis_incomplete: bool = False,
) -> tuple[Decision, str]:
    if analysis_incomplete:
        return Decision.HOLD, "새 자료의 AI 해석이 완료되지 않아 판단을 보류한다."
    if any(risk.severity == Severity.CRITICAL for risk in risks):
        return Decision.HOLD, "검증된 Critical 위험이 있어 출시 판단을 보류한다."
    insufficient = sum(not sample.sufficient for sample in samples)
    if insufficient >= 3:
        return Decision.HOLD, "세 언어권 이상이 최소 표본에 미달해 판단 근거가 부족하다."
    if any(risk.severity == Severity.HIGH for risk in risks):
        return Decision.REVISE, "검증된 High 위험을 수정한 뒤 재검토해야 한다."
    if insufficient:
        return Decision.REVISE, "일부 언어권 표본을 보강한 뒤 출시 판단을 갱신해야 한다."
    return Decision.GO, "필수 표본을 충족했고 High 이상 검증 위험이 없다."
```

- [ ] **Step 4: 두 에이전트가 중앙 정책만 사용하도록 변경**

In `agents/event_redteam/agent.py`, import `RISK_SPECS` from `policy` and delete the local mapping.

In `agents/audit_strategy/agent.py`, import `MIN_RISK_CONFIDENCE`, `REVISION_SPECS`, and `decide`; replace `0.5` with `MIN_RISK_CONFIDENCE`, delete the local mapping and inline decision branch, then call:

```python
decision, reason = decide(bundle.samples, validated)
```

- [ ] **Step 5: 정책과 기존 에이전트 테스트 실행**

Run:

```bash
uv run pytest tests/test_policy.py tests/test_agents.py -v
```

Expected: 모든 정책 조합과 기존 `Revise`·`Hold` 테스트가 통과한다.

- [ ] **Step 6: 커밋**

```bash
git add policy.py tests/test_policy.py agents/event_redteam/agent.py agents/audit_strategy/agent.py
git commit -m "Centralize deterministic risk policy"
```

---

### Task 3: 입력 경로와 근거 의미 무결성을 계약으로 강제

**Files:**
- Modify: `contracts.py:48-54,177-193,237-241,270-305`
- Modify: `evaluation/fixtures.py:98-109`
- Modify: `agents/collector/agent.py:24-37,50-145`
- Modify: `agents/audit_strategy/agent.py:80-139`
- Modify: `tests/test_contracts.py`
- Modify: `tests/test_agents.py`

**Interfaces:**
- Consumes: `FeedbackBundle.evidence`, `RiskAssessment.risks`, `policy.expected_severity`
- Produces: `InputMode.FIXTURE|LIVE|IMPORT`, `FeedbackBundle.input_mode`, `ExploratoryInsight`, Pydantic 내부 참조 검증

- [ ] **Step 1: dangling 참조와 의미 불일치를 거부하는 실패 테스트 작성**

Append to `tests/test_contracts.py`:

```python
from contracts import EvidencePack, InputMode, ValidatedDecision
from agents.audit_strategy import AuditStrategyAgent
from agents.event_redteam import EventRedteamAgent
from agents.evidence_rag import EvidenceRagAgent


def test_feedback_bundle_identifies_fixture_input(feedback):
    assert feedback.input_mode == InputMode.FIXTURE


def test_evidence_pack_rejects_dangling_internal_evidence_refs(feedback):
    pack = EvidenceRagAgent().run(feedback)
    issue = pack.issues[0].model_copy(update={"evidence_ids": ["missing-id"]})
    payload = pack.model_dump()
    payload["issues"][0] = issue.model_dump()
    with pytest.raises(ValidationError, match="unknown evidence"):
        EvidencePack.model_validate(payload)


def test_evidence_pack_rejects_issue_without_matching_mechanism_tag(feedback):
    pack = EvidenceRagAgent().run(feedback)
    wrong = next(item for item in pack.evidence if pack.issues[0].category.value not in item.mechanism_tags)
    payload = pack.model_dump()
    payload["issues"][0]["evidence_ids"] = [wrong.evidence_id]
    with pytest.raises(ValidationError, match="category does not match evidence tags"):
        EvidencePack.model_validate(payload)


def test_validated_decision_rejects_revision_for_unvalidated_risk(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    risks = EventRedteamAgent().run(event, pack)
    decision = AuditStrategyAgent().run(feedback, pack, risks)
    payload = decision.model_dump()
    payload["priority_revisions"][0]["addresses_risk_ids"] = ["rejected-risk"]
    with pytest.raises(ValidationError, match="revision references unvalidated risk"):
        ValidatedDecision.model_validate(payload)
```

Append to `tests/test_agents.py`:

```python
def test_audit_rejects_existing_but_semantically_unrelated_evidence(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    target = assessment.risks[0]
    unrelated = next(
        item for item in pack.evidence if target.category.value not in item.mechanism_tags
    )
    changed = target.model_copy(update={"evidence_ids": [unrelated.evidence_id]})
    decision = AuditStrategyAgent().run(
        feedback,
        pack,
        assessment.model_copy(update={"risks": [changed, *assessment.risks[1:]]}),
    )
    assert changed.risk_id in {item.risk_id for item in decision.rejected_risks}


def test_audit_rejects_risk_outside_closed_policy(event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    unsupported = assessment.risks[0].model_copy(
        update={"risk_id": "risk-fairness", "category": RiskCategory.FAIRNESS}
    )
    decision = AuditStrategyAgent().run(
        feedback,
        pack,
        assessment.model_copy(update={"risks": [unsupported]}),
    )
    assert decision.validated_risks == []
    assert decision.rejected_risks[0].risk_id == "risk-fairness"
```

- [ ] **Step 2: 새 계약 테스트가 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_contracts.py tests/test_agents.py -v
```

Expected: `InputMode` import 실패 또는 새 의미 검증 assertion 실패.

- [ ] **Step 3: 입력 모드와 탐색 인사이트 계약 추가**

Add to `contracts.py`:

```python
class InputMode(StrEnum):
    FIXTURE = "fixture"
    LIVE = "live"
    IMPORT = "import"


class ExploratoryInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
```

Add `input_mode: InputMode` to `FeedbackBundle`, and add
`exploratory_insights: list[ExploratoryInsight] = Field(default_factory=list)` to both
`EvidencePack` and `DecisionBrief`.

Set `InputMode.FIXTURE` in `load_feedback_fixture()`. Add this property to
`CollectionOptions` and use it when constructing the non-fixture bundle:

```python
@property
def input_mode(self) -> InputMode:
    if self.use_fixture:
        return InputMode.FIXTURE
    if self.steam_app_id or self.use_x:
        return InputMode.LIVE
    return InputMode.IMPORT
```

In `AuditStrategyAgent.to_brief()`, carry the accepted exploratory items into the final
brief without rewriting them:

```python
exploratory_insights=pack.exploratory_insights,
```

- [ ] **Step 4: `EvidencePack`와 `ValidatedDecision` 내부 참조 validator 구현**

Add an `after` validator to `EvidencePack` that builds `evidence_by_id`, rejects every
unknown ID used by issues, language insights, personas, or exploratory insights, and requires
every issue-linked evidence item to contain `issue.category.value` in `mechanism_tags`.

Use this exact validation rule:

```python
linked = [*self.issues, *self.language_insights, *self.personas, *self.exploratory_insights]
for item in linked:
    unknown = set(item.evidence_ids) - evidence_by_id.keys()
    if unknown:
        raise ValueError(f"unknown evidence: {', '.join(sorted(unknown))}")
for issue in self.issues:
    if any(issue.category.value not in evidence_by_id[item_id].mechanism_tags for item_id in issue.evidence_ids):
        raise ValueError("issue category does not match evidence tags")
```

Add an `after` validator to `ValidatedDecision`:

```python
validated_ids = {risk.risk_id for risk in self.validated_risks}
for revision in self.priority_revisions:
    if not set(revision.addresses_risk_ids) <= validated_ids:
        raise ValueError("revision references unvalidated risk")
```

- [ ] **Step 5: 감사 단계에 의미·닫힌 정책 검사를 추가**

Before accepting a risk, require all four conditions:

```python
expected = expected_severity(risk.category)
linked = [evidence_by_id[item_id] for item_id in risk.evidence_ids if item_id in evidence_by_id]
grounded = len(linked) == len(risk.evidence_ids) and all(
    risk.category.value in item.mechanism_tags for item in linked
)
if expected is None:
    rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="MVP 닫힌 위험 분류표 외 범주"))
elif not grounded:
    rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="위험 범주와 연결 근거 불일치"))
elif risk.severity != expected:
    rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="정책 위험 등급 불일치"))
elif risk.confidence < MIN_RISK_CONFIDENCE:
    rejected.append(RejectedRisk(risk_id=risk.risk_id, reason="근거 신뢰도 0.5 미만"))
else:
    validated.append(risk)
```

- [ ] **Step 6: 계약·에이전트·기존 종단 테스트 실행**

Run:

```bash
uv run pytest tests/test_contracts.py tests/test_agents.py tests/test_orchestrator.py -v
```

Expected: fixture는 `InputMode.FIXTURE`, 잘못된 참조와 의미 불일치는 거부되고 기존 종단 실행은 `Revise`다.

- [ ] **Step 7: 커밋**

```bash
git add contracts.py evaluation/fixtures.py agents/collector/agent.py \
  agents/audit_strategy/agent.py tests/test_contracts.py tests/test_agents.py
git commit -m "Enforce evidence semantics and input modes"
```

---

### Task 4: 근거 분석 에이전트의 LLM 출력을 설명 후보로 제한

**Files:**
- Modify: `agents/evidence_rag/agent.py:1-201`
- Modify: `agents/evidence_rag/prompt.md`
- Modify: `tests/test_agents.py`

**Interfaces:**
- Consumes: 결정론적 `EvidencePack`, `parse_structured()`, 실제 evidence ID 집합
- Produces: `EvidenceNarrative`, `EvidenceRagAgent.run_deterministic(bundle)`, 검증된 설명이 병합된 `EvidencePack`

- [ ] **Step 1: LLM 문장이 핵심 범주와 근거를 바꾸지 못하는 실패 테스트 작성**

Append to `tests/test_agents.py` using `SimpleNamespace` and `monkeypatch`:

```python
from types import SimpleNamespace

from agents.evidence_rag import agent as evidence_module


def test_evidence_llm_enriches_text_without_changing_core(monkeypatch, feedback):
    deterministic = EvidenceRagAgent().run(feedback)
    target = deterministic.issues[0]

    def fake_parse_structured(**_kwargs):
        return evidence_module.EvidenceNarrative(
            issues=[
                evidence_module.IssueNarrative(
                    category=target.category,
                    title="AI가 정리한 제목",
                    summary="AI가 근거 범위 안에서 정리한 설명",
                    evidence_ids=target.evidence_ids[:2],
                )
            ],
            personas=[],
            exploratory_insights=[],
        )

    monkeypatch.setattr(evidence_module, "parse_structured", fake_parse_structured)
    monkeypatch.setattr(evidence_module, "embedding_rank", lambda _q, evidence, **_k: evidence)
    enriched = EvidenceRagAgent(use_llm=True, client=SimpleNamespace()).run(feedback)

    assert enriched.issues[0].title == "AI가 정리한 제목"
    assert enriched.issues[0].category == target.category
    assert enriched.issues[0].evidence_ids == target.evidence_ids
    assert enriched.issues[0].confidence == target.confidence


def test_evidence_llm_rejects_unknown_evidence(monkeypatch, feedback):
    target = EvidenceRagAgent().run(feedback).issues[0]

    def fake_parse_structured(**_kwargs):
        return evidence_module.EvidenceNarrative(
            issues=[
                evidence_module.IssueNarrative(
                    category=target.category,
                    title="제목",
                    summary="설명",
                    evidence_ids=["invented-id"],
                )
            ],
            personas=[],
            exploratory_insights=[],
        )

    monkeypatch.setattr(evidence_module, "parse_structured", fake_parse_structured)
    monkeypatch.setattr(evidence_module, "embedding_rank", lambda _q, evidence, **_k: evidence)
    with pytest.raises(StructuredModelError, match="unknown evidence"):
        EvidenceRagAgent(use_llm=True, client=SimpleNamespace()).run(feedback)
```

Also import `StructuredModelError` at the top of the test file.

- [ ] **Step 2: 새 테스트가 제한된 응답 타입 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_agents.py::test_evidence_llm_enriches_text_without_changing_core \
  tests/test_agents.py::test_evidence_llm_rejects_unknown_evidence -v
```

Expected: `EvidenceNarrative` 또는 `run_deterministic` 부재로 실패.

- [ ] **Step 3: 제한된 Pydantic 응답 타입을 에이전트 파일에 추가**

Add models with `ConfigDict(extra="forbid")`:

```python
class IssueNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: RiskCategory
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class PersonaNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: PersonaKind
    motivations: list[str] = Field(min_length=1)
    churn_triggers: list[str] = Field(min_length=1)
    play_constraints: list[str] = Field(min_length=1)
    payment_sensitivity: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class EvidenceNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[IssueNarrative]
    personas: list[PersonaNarrative]
    exploratory_insights: list[ExploratoryInsight]
```

- [ ] **Step 4: 결정론적 핵심을 먼저 만들고 LLM 설명만 병합**

Expose the existing deterministic path as:

```python
def run_deterministic(self, bundle: FeedbackBundle) -> EvidencePack:
    return self._deterministic(bundle)
```

Change `run()` to build `base = self.run_deterministic(bundle)`, rank the supplied evidence,
parse `EvidenceNarrative`, and call `_merge_narrative(base, narrative)`. The merge must:

- find official issues by `RiskCategory` and personas by `PersonaKind`;
- require every proposed ID to exist and belong to that base issue or persona;
- copy only title, summary, motivations, churn triggers, play constraints, and payment sensitivity;
- preserve category, official evidence IDs, confidence, sample gates, and language conclusions;
- validate exploratory insight IDs against `base.evidence` before adding them.

Raise this exact normalized error on invalid proposal references:

```python
raise StructuredModelError(ErrorCode.SCHEMA_INVALID, "LLM narrative references unknown evidence")
```

- [ ] **Step 5: 프롬프트에서 금지 필드를 명시**

Replace `agents/evidence_rag/prompt.md` with instructions that require supplied evidence IDs and explicitly state:

```text
Return only EvidenceNarrative. You may rewrite issue and persona explanations and propose
exploratory insights. You must not choose schema metadata, sample sufficiency, official risk
severity, final decisions, or replacement evidence IDs. Every cited ID must exist in the
supplied deterministic EvidencePack.
```

- [ ] **Step 6: 근거 에이전트와 구조화 출력 테스트 실행**

Run:

```bash
uv run pytest tests/test_agents.py tests/test_structured_api.py tests/test_retrieval.py -v
```

Expected: 허용 문장은 반영되지만 공식 범주·근거·신뢰도는 결정론적 결과와 같다.

- [ ] **Step 7: 커밋**

```bash
git add agents/evidence_rag/agent.py agents/evidence_rag/prompt.md tests/test_agents.py
git commit -m "Constrain evidence LLM to grounded narratives"
```

---

### Task 5: 레드팀과 감사 LLM이 정책 필드를 덮어쓰지 못하게 제한

**Files:**
- Modify: `agents/event_redteam/agent.py:1-106`
- Modify: `agents/event_redteam/prompt.md`
- Modify: `agents/audit_strategy/agent.py:1-187`
- Modify: `agents/audit_strategy/prompt.md`
- Modify: `tests/test_agents.py`

**Interfaces:**
- Consumes: 중앙 `policy.py`, 결정론적 `RiskAssessment`와 `ValidatedDecision`
- Produces: `RedteamNarrative`, `AuditNarrative`, `run_deterministic()` 메서드, 텍스트만 보강된 산출물

- [ ] **Step 1: 서로 다른 LLM 문장이 정책 소유 필드를 바꾸지 못하는 실패 테스트 작성**

Add these imports and helpers to `tests/test_agents.py`:

```python
from agents.audit_strategy import agent as audit_module
from agents.event_redteam import agent as redteam_module


def risk_core(assessment):
    return [
        (risk.category, risk.severity, tuple(risk.evidence_ids), tuple(risk.affected_personas))
        for risk in assessment.risks
    ]


def decision_core(decision):
    return (
        decision.decision,
        tuple(risk.risk_id for risk in decision.validated_risks),
        tuple(risk.risk_id for risk in decision.rejected_risks),
        tuple(
            (tuple(action.addresses_risk_ids), action.priority)
            for action in decision.priority_revisions
        ),
    )


def test_redteam_llm_text_cannot_override_core(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    base = EventRedteamAgent().run(event, pack)
    target = base.risks[0]
    responses = iter(
        [
            redteam_module.RedteamNarrative(
                risks=[
                    redteam_module.RiskNarrative(
                        category=target.category,
                        title="첫 번째 설명",
                        failure_path="첫 번째 실패 경로",
                        revision_question="첫 번째 질문",
                        evidence_ids=target.evidence_ids[:1],
                    )
                ]
            ),
            redteam_module.RedteamNarrative(
                risks=[
                    redteam_module.RiskNarrative(
                        category=target.category,
                        title="두 번째 설명",
                        failure_path="두 번째 실패 경로",
                        revision_question="두 번째 질문",
                        evidence_ids=target.evidence_ids[-1:],
                    )
                ]
            ),
        ]
    )
    monkeypatch.setattr(redteam_module, "parse_structured", lambda **_kwargs: next(responses))
    agent = EventRedteamAgent(use_llm=True, client=object())
    first = agent.run(event, pack)
    second = agent.run(event, pack)
    assert first.risks[0].title != second.risks[0].title
    assert risk_core(first) == risk_core(second) == risk_core(base)


def test_audit_llm_text_cannot_override_decision_or_links(monkeypatch, event, feedback):
    pack = EvidenceRagAgent().run(feedback)
    assessment = EventRedteamAgent().run(event, pack)
    base = AuditStrategyAgent().run(feedback, pack, assessment)
    category = base.validated_risks[0].category
    responses = iter(
        [
            audit_module.AuditNarrative(
                decision_reason="첫 번째 설명",
                revisions=[
                    audit_module.RevisionNarrative(
                        category=category,
                        title="첫 수정안",
                        change="첫 변경 문장",
                        success_metric="첫 지표 문장",
                    )
                ],
            ),
            audit_module.AuditNarrative(
                decision_reason="두 번째 설명",
                revisions=[
                    audit_module.RevisionNarrative(
                        category=category,
                        title="둘째 수정안",
                        change="둘째 변경 문장",
                        success_metric="둘째 지표 문장",
                    )
                ],
            ),
        ]
    )
    monkeypatch.setattr(audit_module, "parse_structured", lambda **_kwargs: next(responses))
    agent = AuditStrategyAgent(use_llm=True, client=object())
    first = agent.run(feedback, pack, assessment)
    second = agent.run(feedback, pack, assessment)
    assert first.decision_reason != second.decision_reason
    assert decision_core(first) == decision_core(second) == decision_core(base)
```

- [ ] **Step 2: 테스트가 현재 전체 Artifact LLM 분기 때문에 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_agents.py -k "llm and (redteam or audit)" -v
```

Expected: 제한된 narrative 타입 또는 deterministic merge 부재로 실패.

- [ ] **Step 3: 레드팀 응답을 설명 필드로 제한**

Add:

```python
class RiskNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: RiskCategory
    title: str = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class RedteamNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risks: list[RiskNarrative]
```

Expose the current rule path as `run_deterministic(event, pack)`. In LLM mode, parse
`RedteamNarrative`, match by category, require proposed IDs to be a non-empty subset of the
official risk IDs, and copy only the three text fields. Preserve severity, affected personas,
affected languages, official evidence IDs, and confidence.

- [ ] **Step 4: 감사 응답을 판정 설명과 수정 문장으로 제한**

Add:

```python
class RevisionNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: RiskCategory
    title: str = Field(min_length=1)
    change: str = Field(min_length=1)
    success_metric: str = Field(min_length=1)


class AuditNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_reason: str = Field(min_length=1)
    revisions: list[RevisionNarrative]
```

Expose the current policy path as `run_deterministic(bundle, pack, assessment)`. In LLM mode,
parse `AuditNarrative`, match revision text by the validated risk category, and preserve
`decision`, `validated_risks`, `rejected_risks`, revision priority, and
`addresses_risk_ids`.

- [ ] **Step 5: 두 프롬프트를 제한된 역할에 맞게 수정**

The redteam prompt must say it cannot choose severity, official evidence IDs, or final
decision. The audit prompt must say it cannot approve/reject risks, set decision, change
priority, or change risk links. Both must require the supplied category key.

- [ ] **Step 6: 에이전트와 종단 테스트 실행**

Run:

```bash
uv run pytest tests/test_agents.py tests/test_orchestrator.py -v
```

Expected: LLM 문구가 달라도 정책 소유 필드는 동일하며 기존 fixture는 `Revise`다.

- [ ] **Step 7: 커밋**

```bash
git add agents/event_redteam/agent.py agents/event_redteam/prompt.md \
  agents/audit_strategy/agent.py agents/audit_strategy/prompt.md tests/test_agents.py
git commit -m "Keep redteam and audit decisions deterministic"
```

---

### Task 6: LLM 재시도와 입력별 안전 경로를 오케스트레이터에 구현

**Files:**
- Modify: `agents/structured.py:18-49`
- Modify: `agents/audit_strategy/agent.py`
- Modify: `orchestrator.py:28-176`
- Modify: `tests/test_structured_api.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: 각 에이전트의 `run()`과 `run_deterministic()`, `FeedbackBundle.input_mode`
- Produces: `fallback_used: bool`, `analysis_incomplete: bool`, 저장 fixture 안전 경로,
  실시간·가져오기 자료의 안전한 `Hold`

- [ ] **Step 1: Pydantic 출력 오류 정규화 실패 테스트 작성**

Append to `tests/test_structured_api.py`:

```python
import pytest

from agents.structured import StructuredModelError
from contracts import ErrorCode


def test_invalid_parsed_payload_becomes_structured_schema_error(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")

    class Responses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed={"wrong": "shape"})

    client = SimpleNamespace(responses=Responses())
    with pytest.raises(StructuredModelError) as error:
        parse_structured(
            model="gpt-5.6-luna",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=client,
        )
    assert error.value.code == ErrorCode.SCHEMA_INVALID
```

- [ ] **Step 2: 오케스트레이터의 재시도·fallback 경계 실패 테스트 작성**

Add to `tests/test_orchestrator.py`:

```python
from agents.structured import StructuredModelError
from contracts import Decision, ErrorCode, InputMode


def test_fixture_llm_refusal_retries_once_then_uses_deterministic_fallback(event):
    class RefusingRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, _bundle, on_event=None):
            self.calls += 1
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

    rag = RefusingRag()
    result = EventPreflightOrchestrator(evidence_rag=rag).run(event, CollectionOptions())
    assert rag.calls == 2
    assert result.brief.decision == Decision.REVISE
    assert result.fallback_used is True


def test_contract_violation_stops_without_retry_or_fallback(event):
    class BrokenRag(EvidenceRagAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, bundle, on_event=None):
            self.calls += 1
            return self.run_deterministic(bundle).model_copy(update={"producer": Producer.COLLECTOR})

    broken = BrokenRag()
    with pytest.raises(PipelineStopped, match="SCHEMA_INVALID"):
        EventPreflightOrchestrator(evidence_rag=broken).run(event, CollectionOptions())
    assert broken.calls == 1


def test_live_llm_failure_returns_hold_without_loading_fixture(event):
    class RefusingRag(EvidenceRagAgent):
        def run(self, _bundle, on_event=None):
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "refused")

    class FakeSteam:
        def fetch_reviews(self, _app_id, language, cutoff_at, limit=100):
            return []

    result = EventPreflightOrchestrator(
        collector=CollectorAgent(steam=FakeSteam()),
        evidence_rag=RefusingRag(),
    ).run(event, CollectionOptions(use_fixture=False, steam_app_id=578080))
    assert result.feedback.input_mode == InputMode.LIVE
    assert result.brief.decision == Decision.HOLD
    assert result.analysis_incomplete is True
    assert result.brief.evidence == []
```

Import `CollectorAgent` and `InputMode` for the live test.

Replace the old `test_schema_violation_retries_once` expectation: producer/run ID/input ref
contract violations now stop after one call. Keep a separate LLM refusal test as the only
retry case.

- [ ] **Step 3: 테스트가 현재 중단 동작과 재시도 규칙 때문에 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_structured_api.py tests/test_orchestrator.py -v
```

Expected: fixture fallback assertion and contract one-call assertion fail.

- [ ] **Step 4: 구조화 출력의 모든 검증 오류를 `SCHEMA_INVALID`로 정규화**

Wrap both the SDK call and final `output_type.model_validate()` in `parse_structured()`:

```python
try:
    response = client.responses.parse(...)
    if response.output_parsed is None:
        raise StructuredModelError(ErrorCode.LLM_REFUSAL, "model returned no parsed output")
    return output_type.model_validate(response.output_parsed)
except StructuredModelError:
    raise
except Exception as exc:
    raise StructuredModelError(ErrorCode.SCHEMA_INVALID, str(exc)) from exc
```

- [ ] **Step 5: 재시도 대상과 계약 위반을 분리**

In `_stage()`, retry only `StructuredModelError` with `SCHEMA_INVALID` or `LLM_REFUSAL`.
Move `ValidationError` and `ContractViolation` to an immediate `failed` event followed by
`PipelineStopped`; do not retry them.

- [ ] **Step 6: 입력 모드별 최소 안전 경로 구현**

Add `fallback_used: bool = False` and `analysis_incomplete: bool = False` to
`PipelineResult`. Keep `_stage()` responsible only for two LLM attempts and contract checks;
let `run()` catch the exhausted `StructuredModelError` at each of the three LLM-capable
stages.

- For `FIXTURE`, call that same agent's `run_deterministic(...)`, pass the normal contract
  check, set `fallback_used=True`, and continue. If the failing stage is audit, pass the
  default `analysis_incomplete=False`.
- For `LIVE` or `IMPORT`, never load fixture data and never reuse an artifact from an older
  run. Continue with each current agent's deterministic path over the current run's collected
  bundle, but set `analysis_incomplete=True` as soon as any LLM stage exhausts retries.
- Call `AuditStrategyAgent.run_deterministic(..., analysis_incomplete=True)` so `policy.decide`
  returns `Decision.HOLD` with the reason "새 자료의 AI 해석이 완료되지 않아 판단을
  보류한다." The resulting brief must contain only current-run evidence.
- If a deterministic artifact itself fails its Pydantic/producer/run ID/input-ref contract,
  raise `PipelineStopped`; a contract failure must never be converted into a brief.

Use one private `_deterministic_stage(name, args...)` branch for the three current agents;
do not add a fallback interface or registry.

Update the audit signature in `agents/audit_strategy/agent.py`:

```python
def run_deterministic(
    self,
    bundle: FeedbackBundle,
    pack: EvidencePack,
    assessment: RiskAssessment,
    *,
    analysis_incomplete: bool = False,
) -> ValidatedDecision:
    # keep the existing validation/revision body
    decision, reason = decide(
        bundle.samples,
        validated,
        analysis_incomplete=analysis_incomplete,
    )
```

- [ ] **Step 7: fallback 테스트와 전체 종단 테스트 실행**

Run:

```bash
uv run pytest tests/test_structured_api.py tests/test_orchestrator.py tests/test_agents.py -v
```

Expected: fixture LLM 거절은 두 번 호출 뒤 안전 경로로 `Revise`, live LLM 거절은
현재 실행의 빈 근거로 `Hold`, 계약 위반은 한 번에 중단한다.

- [ ] **Step 8: 커밋**

```bash
git add agents/structured.py agents/audit_strategy/agent.py orchestrator.py \
  tests/test_structured_api.py tests/test_orchestrator.py
git commit -m "Add controlled LLM fallback boundaries"
```

---

### Task 7: 재현성 버전·입력 해시·핵심 결과 비교를 기록

**Files:**
- Modify: `contracts.py:96-108,298-305`
- Modify: `orchestrator.py:1-117`
- Modify: `evaluation/verify_success.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_success_gate.py`

**Interfaces:**
- Consumes: 정규화된 `EventBrief`, `FeedbackBundle`, `POLICY_VERSION`
- Produces: `input_snapshot_hash`, `policy_version`, `core_outcome(result) -> tuple`, `SuccessReport.reproducible_core`

- [ ] **Step 1: 동일 입력과 변경 입력의 해시 실패 테스트 작성**

Append to `tests/test_orchestrator.py`:

```python
def core_outcome(result):
    return (
        result.brief.decision,
        tuple(
            (risk.category, risk.severity, tuple(sorted(risk.evidence_ids)))
            for risk in result.brief.top_risks
        ),
        tuple(risk.risk_id for risk in result.validated.validated_risks),
        tuple(risk.risk_id for risk in result.validated.rejected_risks),
        tuple(
            (tuple(action.addresses_risk_ids), action.priority)
            for action in result.brief.revision_plan
        ),
        result.brief.schema_version,
        result.brief.policy_version,
        result.brief.input_snapshot_hash,
    )


def test_same_fixture_produces_same_core_outcome_across_run_ids():
    first_event = load_demo_event("first-run")
    second_event = load_demo_event("second-run")
    first = EventPreflightOrchestrator().run(first_event, CollectionOptions())
    second = EventPreflightOrchestrator().run(second_event, CollectionOptions())
    assert core_outcome(first) == core_outcome(second)


def test_input_snapshot_hash_changes_when_normalized_input_changes(event):
    first = EventPreflightOrchestrator().run(event, CollectionOptions())
    changed = event.model_copy(update={"goal": f"{event.goal} 변경"})
    second = EventPreflightOrchestrator().run(changed, CollectionOptions())
    assert first.brief.input_snapshot_hash != second.brief.input_snapshot_hash
```

Import `load_demo_event` in the test file.

- [ ] **Step 2: 테스트가 메타데이터 필드 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_orchestrator.py -k "same_fixture or snapshot_hash" -v
```

Expected: `policy_version` 또는 `input_snapshot_hash` attribute 부재.

- [ ] **Step 3: 산출물에 버전과 입력 해시 추가**

Add to `Artifact`:

```python
policy_version: str = "1.0"
input_snapshot_hash: str = Field(default="pending", pattern=r"^(pending|[0-9a-f]{64})$")
```

Do not include `run_id`, producer, input refs, status, errors, search `requested_at`, or LLM
narrative text in the input hash. In `orchestrator.py`, implement with only stdlib:

```python
def _input_snapshot_hash(event: EventBrief, feedback: FeedbackBundle) -> str:
    event_body = event.model_dump(
        mode="json",
        exclude={"run_id", "producer", "input_refs", "status", "errors", "input_snapshot_hash"},
    )
    evidence = [
        {
            "evidence_id": item.evidence_id,
            "source": item.source.value,
            "source_id": item.source_id,
            "language": item.language.value,
            "observed_at": item.observed_at.isoformat(),
            "summary": item.summary,
            "mechanism_tags": sorted(item.mechanism_tags),
            "relevance": item.relevance,
        }
        for item in sorted(feedback.evidence, key=lambda item: item.evidence_id)
    ]
    payload = {"event": event_body, "input_mode": feedback.input_mode.value, "evidence": evidence}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
```

After collection, update the feedback metadata with `POLICY_VERSION` and this hash; propagate
the same values into every later artifact before `_check()` and JSONL write.

- [ ] **Step 4: 성공 게이트에 두 번 실행 비교 추가**

Add these fields to `SuccessReport`:

```python
reproducible_core: bool
semantic_links_valid: bool
input_snapshot_hash: str
```

Run the same fixture with a second `run_id`, compare the same core projection used above,
and include these conditions in `passed`:

```python
reproducible_core = core_outcome(first) == core_outcome(second)
semantic_links_valid = backtest.evidence_link_rate == 1 and backtest.sampled_claim_support_rate >= 0.9
```

Update `tests/test_success_gate.py` to assert the three new fields and a 64-character hash.

- [ ] **Step 5: 재현성 및 성공 게이트 실행**

Run:

```bash
uv run pytest tests/test_orchestrator.py tests/test_success_gate.py -v
uv run python -m evaluation.verify_success
```

Expected: 서로 다른 `run_id`의 core 결과가 같고, 입력이 달라지면 해시가 달라지며 성공 게이트가 통과한다.

- [ ] **Step 6: 커밋**

```bash
git add contracts.py orchestrator.py evaluation/verify_success.py \
  tests/test_orchestrator.py tests/test_success_gate.py
git commit -m "Record reproducible pipeline outcomes"
```

---

### Task 8: 에이전트 내부 노드 실행 이벤트와 순서를 기록

**Files:**
- Create: `execution.py`
- Modify: `orchestrator.py:28-176`
- Modify: `agents/collector/agent.py:50-145`
- Modify: `agents/evidence_rag/agent.py`
- Modify: `agents/event_redteam/agent.py`
- Modify: `agents/audit_strategy/agent.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: 각 에이전트의 현재 순차 처리 단계
- Produces: `ExecutionState`, `ExecutionEvent`, `EventCallback`, `PipelineResult.events`

- [ ] **Step 1: 성공·재시도·실패 이벤트 불변조건 테스트 작성**

Append to `tests/test_orchestrator.py`:

```python
from execution import AGENT_ORDER, ExecutionState


def test_success_events_include_internal_nodes_in_pipeline_order(event):
    result = EventPreflightOrchestrator().run(event, CollectionOptions())
    assert [item.agent for item in result.events[:4]] == list(AGENT_ORDER)
    assert all(item.state == ExecutionState.WAITING for item in result.events[:4])
    completed = [item.agent for item in result.events if item.state == ExecutionState.COMPLETE]
    assert completed[:4] == list(AGENT_ORDER)
    required_nodes = {
        "collection": ["source_selected", "cutoff_checked", "anonymized", "samples_counted", "bundle_ready"],
        "evidence_rag_personas": ["deduplicated", "issues_grouped", "language_gate_checked", "personas_built", "pack_ready"],
        "event_redteam": ["event_reviewed", "failure_paths_built", "impact_linked", "risks_graded", "assessment_ready"],
        "audit_strategy": ["evidence_checked", "risks_validated", "sample_gate_applied", "decision_fixed", "revisions_built"],
    }
    for agent, nodes in required_nodes.items():
        observed = [item.node for item in result.events if item.agent == agent]
        positions = [observed.index(node) for node in nodes]
        assert positions == sorted(positions)


def test_failure_event_never_starts_downstream_agents(event):
    class BrokenRag(EvidenceRagAgent):
        def run(self, bundle, on_event=None):
            result = self.run_deterministic(bundle)
            return result.model_copy(update={"producer": Producer.COLLECTOR})

    events = []
    with pytest.raises(PipelineStopped):
        EventPreflightOrchestrator(evidence_rag=BrokenRag()).run(
            event,
            CollectionOptions(),
            on_event=events.append,
        )
    assert not any(
        item.agent in {"event_redteam", "audit_strategy"} and item.state == ExecutionState.RUNNING
        for item in events
    )
```

- [ ] **Step 2: 테스트가 실행 이벤트 타입과 기록 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_orchestrator.py -k "events" -v
```

Expected: `execution` 모듈 또는 `on_event` 인자 부재.

- [ ] **Step 3: 최소 실행 이벤트 계약 생성**

Create `execution.py`:

```python
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

AGENT_ORDER = ("collection", "evidence_rag_personas", "event_redteam", "audit_strategy")


class ExecutionState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETE = "complete"
    RETRYING = "retrying"
    FAILED = "failed"


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    agent: str
    node: str
    state: ExecutionState
    message: str = Field(min_length=1)
    metrics: dict[str, int | float | str | bool] = Field(default_factory=dict)


EventCallback = Callable[[ExecutionEvent], None]
```

- [ ] **Step 4: 오케스트레이터가 이벤트를 한 곳에서 기록하고 전달**

Change the public signature to:

```python
def run(
    self,
    event: EventBrief,
    options: CollectionOptions | None = None,
    *,
    on_event: EventCallback | None = None,
    log_path: Path | None = None,
) -> PipelineResult:
```

Add `events: list[ExecutionEvent]` to `PipelineResult`. At run start emit one `WAITING` event
for every entry in `AGENT_ORDER`. Use one local `emit(agent, node, state, message, metrics={})`
closure that assigns `sequence=len(events)`, appends to `events`, calls `on_event`, and writes
the event JSON line when `log_path` is set.

Remove the old `(stage, status, message)` callback rather than maintaining two interfaces.

- [ ] **Step 5: 각 에이전트가 실제 내부 경계에서 이벤트 발생**

Add optional `on_event: Callable[[str, str, dict], None] | None = None` to each agent `run`
and `run_deterministic`. Emit the exact required node names from Step 1 only after the
corresponding calculation finishes. For example, collector emits:

```python
notify("source_selected", "저장된 검증 데이터를 선택했습니다.", {"input_mode": options.input_mode.value})
notify("cutoff_checked", "기준 시점 이후 자료를 제외했습니다.", {"remaining": len(evidence)})
notify("anonymized", "원문을 저장하지 않고 비식별 근거를 만들었습니다.", {"evidence": len(evidence)})
notify("samples_counted", "언어권별 표본을 집계했습니다.", {"insufficient": sum(not item.sufficient for item in samples)})
notify("bundle_ready", "FeedbackBundle 계약을 통과했습니다.", {"evidence": len(evidence)})
```

The orchestrator adapts these node callbacks into `ExecutionEvent` with the current agent and
`RUNNING`; `_stage` emits agent-level `COMPLETE`, `RETRYING`, or `FAILED`.

- [ ] **Step 6: 이벤트 순서와 기존 종단 테스트 실행**

Run:

```bash
uv run pytest tests/test_orchestrator.py -v
```

Expected: 네 waiting 이벤트로 시작하고, 내부 노드와 완료 이벤트가 고정 순서로 남으며 실패 후 downstream 실행이 없다.

- [ ] **Step 7: 커밋**

```bash
git add execution.py orchestrator.py agents tests/test_orchestrator.py
git commit -m "Expose multi-agent execution events"
```

---

### Task 9: 실행 중 전체 펼침과 완료 후 결과 중심 UI 구현

**Files:**
- Create: `ui_state.py`
- Create: `tests/test_ui_state.py`
- Modify: `streamlit_app.py:18-225`
- Modify: `tests/test_streamlit_app.py`

**Interfaces:**
- Consumes: `ExecutionEvent`, `PipelineResult`, `FeedbackBundle.input_mode`
- Produces: `AgentView`, `PipelineView`, `build_pipeline_view()`, `begin_run()`, `store_success()`, `store_failure()`

- [ ] **Step 1: 화면 상태 전환 실패 테스트 작성**

Create `tests/test_ui_state.py`:

```python
from execution import AGENT_ORDER, ExecutionEvent, ExecutionState
from ui_state import begin_run, build_pipeline_view, store_failure, store_success


def event(sequence, agent, node, state):
    return ExecutionEvent(
        sequence=sequence,
        agent=agent,
        node=node,
        state=state,
        message=f"{agent}:{node}",
    )


def waiting_events():
    return [
        event(index, agent, "waiting", ExecutionState.WAITING)
        for index, agent in enumerate(AGENT_ORDER)
    ]


def test_running_view_expands_all_agent_cards_and_highlights_latest_node():
    events = [
        *waiting_events(),
        event(4, "collection", "source_selected", ExecutionState.RUNNING),
    ]
    view = build_pipeline_view(events, finished=False)
    assert view.show_decision is False
    assert all(agent.expanded for agent in view.agents)
    assert view.agents[0].current_node == "source_selected"
    assert view.agents[0].state == ExecutionState.RUNNING


def test_completed_view_collapses_agent_cards_and_uses_decision_view():
    events = waiting_events() + [
        event(index + 4, agent, "complete", ExecutionState.COMPLETE)
        for index, agent in enumerate(AGENT_ORDER)
    ]
    view = build_pipeline_view(events, finished=True)
    assert view.show_decision is True
    assert all(not agent.expanded for agent in view.agents)


def test_failed_view_marks_failed_agent_and_keeps_downstream_waiting():
    events = waiting_events() + [
        event(4, "collection", "bundle_ready", ExecutionState.COMPLETE),
        event(5, "evidence_rag_personas", "pack_ready", ExecutionState.FAILED),
    ]
    view = build_pipeline_view(events, finished=False, error="SCHEMA_INVALID")
    assert view.agents[1].state == ExecutionState.FAILED
    assert view.agents[1].expanded is True
    assert all(agent.state == ExecutionState.WAITING for agent in view.agents[2:])


def test_new_run_clears_stale_result_but_preserves_fixture_backup():
    state = {
        "preflight_result": "stale",
        "preflight_error": "old",
        "fixture_backup_result": "safe",
    }
    begin_run(state, "live")
    assert "preflight_result" not in state
    assert "preflight_error" not in state
    assert state["fixture_backup_result"] == "safe"
    store_failure(state, "network down")
    assert state["fixture_backup_result"] == "safe"
    store_success(state, "fixture-result", input_mode="fixture")
    assert state["fixture_backup_result"] == "fixture-result"
```

- [ ] **Step 2: 테스트가 UI 상태 모듈 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_ui_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'ui_state'`.

- [ ] **Step 3: 순수 화면 상태 모델과 세션 전환 함수 구현**

Create `ui_state.py`:

```python
from dataclasses import dataclass
from typing import Any, MutableMapping

from execution import AGENT_ORDER, ExecutionEvent, ExecutionState


@dataclass(frozen=True, slots=True)
class AgentView:
    agent: str
    state: ExecutionState
    current_node: str
    messages: tuple[str, ...]
    metrics: dict[str, int | float | str | bool]
    expanded: bool


@dataclass(frozen=True, slots=True)
class PipelineView:
    agents: tuple[AgentView, ...]
    show_decision: bool
    error: str | None


def build_pipeline_view(
    events: list[ExecutionEvent],
    *,
    finished: bool,
    error: str | None = None,
) -> PipelineView:
    views = []
    for agent in AGENT_ORDER:
        observed = [item for item in events if item.agent == agent]
        latest = observed[-1]
        views.append(
            AgentView(
                agent=agent,
                state=latest.state,
                current_node=latest.node,
                messages=tuple(item.message for item in observed if item.state != ExecutionState.WAITING),
                metrics=dict(latest.metrics),
                expanded=not finished or latest.state == ExecutionState.FAILED,
            )
        )
    return PipelineView(tuple(views), show_decision=finished and error is None, error=error)


def begin_run(state: MutableMapping[str, Any], input_mode: str) -> None:
    state.pop("preflight_result", None)
    state.pop("preflight_error", None)
    state["execution_events"] = []
    state["active_input_mode"] = input_mode


def store_success(state: MutableMapping[str, Any], result: Any, *, input_mode: str) -> None:
    state["preflight_result"] = result
    state.pop("preflight_error", None)
    if input_mode == "fixture":
        state["fixture_backup_result"] = result


def store_failure(state: MutableMapping[str, Any], message: str) -> None:
    state.pop("preflight_result", None)
    state["preflight_error"] = message
```

- [ ] **Step 4: 완료 화면의 결과 우선순위와 네 추적 항목 AppTest 작성**

Replace `tests/test_streamlit_app.py` with the existing fixture test plus:

```python
def run_fixture():
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=20)
    assert not app.exception
    app.button[0].click().run(timeout=20)
    assert not app.exception
    return app


def test_completed_fixture_prioritizes_decision_and_has_four_collapsed_agent_traces():
    app = run_fixture()
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["최종 판정"] == "Revise"
    labels = [item.label for item in app.expander]
    assert labels == [
        "1. 수집 에이전트",
        "2. 근거 분석 에이전트",
        "3. 레드팀 에이전트",
        "4. 감사·전략 에이전트",
    ]
    assert all(not item.expanded for item in app.expander)


def test_agent_trace_contains_intermediate_outputs_and_evidence():
    app = run_fixture()
    text = "\n".join(item.value for item in app.markdown)
    assert "FeedbackBundle" in text
    assert "EvidencePack" in text
    assert "RiskAssessment" in text
    assert "ValidatedDecision" in text
    assert "근거 ID" in text
```

- [ ] **Step 5: Streamlit을 세 가지 입력 경로와 두 화면 상태로 재구성**

Use these radio labels in `streamlit_app.py`:

```python
SOURCE_MODES = {
    "검증된 저장 데이터": "fixture",
    "Steam 실시간 갱신": "live",
    "승인 CSV 가져오기": "import",
}
```

Give the radio `key="source_mode"` so the recovery button can select the fixture value before
`st.rerun()`.

Use the native form submit button; `st.form_submit_button` has no separate key parameter:

```python
submitted = st.form_submit_button(
    "사전검증 실행", type="primary", use_container_width=True
)
```

Before constructing `EventBrief`, call `begin_run(st.session_state, input_mode)` so a failed
new run cannot display a stale brief. Keep `fixture_backup_result` untouched.

Create one `st.empty()` pipeline placeholder before the orchestrator call. The `on_event`
callback appends the event to `st.session_state["execution_events"]`, builds a running view,
and replaces the placeholder contents with four expanded agent containers. Each card shows:

- Korean agent label and current node;
- state badge for waiting/running/complete/retrying/failed;
- all received user-facing messages;
- the latest structured metrics;
- the expected output contract name.

After success call `store_success(...)`, replace the pipeline area with the decision-first
view, and render exactly four collapsed `st.expander` containers. Map each artifact:

```python
TRACE_ARTIFACTS = (
    ("1. 수집 에이전트", "FeedbackBundle", lambda result: result.feedback),
    ("2. 근거 분석 에이전트", "EvidencePack", lambda result: result.evidence),
    ("3. 레드팀 에이전트", "RiskAssessment", lambda result: result.risks),
    ("4. 감사·전략 에이전트", "ValidatedDecision", lambda result: result.validated),
)
```

Inside each expander, show the contract name, input refs, errors, event messages and a compact
table of evidence/risk IDs. Do not render raw chain-of-thought or raw community text.

On failure call `store_failure(...)`, render the failed agent expanded, keep later agents
waiting, and show a `저장 데이터로 다시 실행` button. Its click sets
`st.session_state["source_mode"] = "검증된 저장 데이터"`, marks a
`rerun_fixture_requested` flag, and calls `st.rerun()`. At the next render, the flag invokes
the same submit handler once. It must start a fresh pipeline run rather than display
`fixture_backup_result` as the new result.

- [ ] **Step 6: UI 상태와 Streamlit AppTest 실행**

Run:

```bash
uv run pytest tests/test_ui_state.py tests/test_streamlit_app.py -v
```

Expected: 실행 중 view는 네 카드 모두 expanded, 완료 view는 최종 판정 `Revise`와 네 collapsed expander를 갖는다.

- [ ] **Step 7: 커밋**

```bash
git add ui_state.py streamlit_app.py tests/test_ui_state.py tests/test_streamlit_app.py
git commit -m "Visualize live multi-agent execution"
```

---

### Task 10: Steam 실시간 갱신과 저장 입력을 완전히 격리

**Files:**
- Modify: `agents/collector/agent.py:50-192`
- Modify: `connectors/steam/client.py:1-75`
- Modify: `orchestrator.py`
- Create: `scripts/smoke_steam.py`
- Modify: `tests/test_connectors.py`
- Modify: `tests/test_agents.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `InputMode`, `SteamClient.fetch_reviews()`, 저장 fixture 안전 경로
- Produces: 순서 독립 `evidence_id`, `scripts/smoke_steam.py`, live 실패 후 정상 fixture 재실행

- [ ] **Step 1: 실시간 경로가 fixture를 섞지 않는 실패 테스트 작성**

Append to `tests/test_agents.py`:

```python
from datetime import timedelta

from agents.collector import CollectionOptions, CollectorAgent
from connectors import RawFeedback
from contracts import InputMode, SourceType


def test_collector_never_loads_fixture_in_live_mode(monkeypatch, event):
    monkeypatch.setattr(
        "agents.collector.agent.load_feedback_fixture",
        lambda _event: (_ for _ in ()).throw(AssertionError("fixture must not load")),
    )

    class FakeSteam:
        def fetch_reviews(self, _app_id, language, cutoff_at, limit=100):
            return [
                RawFeedback(
                    source=SourceType.STEAM,
                    source_url="https://steamcommunity.com/app/578080/reviews/",
                    source_id=f"anonymous-{language.value}",
                    language=language,
                    observed_at=cutoff_at - timedelta(days=1),
                    text="double gacha is confusing",
                )
            ]

    bundle = CollectorAgent(steam=FakeSteam()).run(
        event,
        CollectionOptions(use_fixture=False, steam_app_id=578080),
    )
    assert bundle.input_mode == InputMode.LIVE
    assert bundle.evidence
    assert all(not item.synthetic for item in bundle.evidence)
```

- [ ] **Step 2: API 반환 순서와 무관한 근거 ID 실패 테스트 작성**

Append to `tests/test_agents.py`:

```python
def test_live_evidence_ids_do_not_depend_on_api_order(event):
    items = [
        RawFeedback(
            source=SourceType.STEAM,
            source_url="https://steamcommunity.com/app/578080/reviews/",
            source_id=f"anonymous-{index}",
            language=Language.ENGLISH,
            observed_at=event.cutoff_at - timedelta(days=index + 1),
            text="double gacha is confusing",
        )
        for index in range(2)
    ]
    forward = _summarize_without_persisting_raw(items)
    backward = _summarize_without_persisting_raw(list(reversed(items)))
    assert {item.evidence_id for item in forward} == {item.evidence_id for item in backward}
```

Import `_summarize_without_persisting_raw` from `agents.collector.agent` and `Language`.

- [ ] **Step 3: live 실패 후 같은 오케스트레이터의 fixture 경로가 정상인지 테스트**

Append to `tests/test_orchestrator.py`:

```python
from connectors import ConnectorError


def test_fixture_run_still_succeeds_after_live_collection_failure(event):
    class FailingSteam:
        def fetch_reviews(self, *_args, **_kwargs):
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "network down")

    orchestrator = EventPreflightOrchestrator(collector=CollectorAgent(steam=FailingSteam()))
    with pytest.raises(PipelineStopped):
        orchestrator.run(
            event,
            CollectionOptions(use_fixture=False, steam_app_id=578080),
        )
    recovered = orchestrator.run(event, CollectionOptions(use_fixture=True))
    assert recovered.brief.decision == Decision.REVISE
    assert all(item.synthetic for item in recovered.feedback.evidence)
```

- [ ] **Step 4: 새 테스트가 순서 의존 ID 또는 격리 동작 때문에 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_agents.py tests/test_orchestrator.py -k "live or fixture_run_still" -v
```

Expected: 현재 `live-...-{index}` ID 비교가 실패한다.

- [ ] **Step 5: 실시간 ID를 익명 source ID에서 안정적으로 생성**

Replace the current index-based expression in `_summarize_without_persisting_raw()`:

```python
evidence_id=f"live-{item.source.value}-{item.source_id}"
```

Deduplicate by `(source, source_id)` before creating `EvidenceItem`; do not persist raw text.

- [ ] **Step 6: 실제 Steam 조회 smoke 스크립트 작성**

Create `scripts/smoke_steam.py`:

```python
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from connectors.steam import SteamClient
from contracts import Language


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int, default=578080)
    parser.add_argument("--language", choices=[item.value for item in Language], default="en")
    parser.add_argument("--limit", type=int, choices=range(1, 101), default=10)
    args = parser.parse_args()
    items = SteamClient().fetch_reviews(
        args.app_id,
        Language(args.language),
        datetime.now(UTC) + timedelta(seconds=1),
        limit=args.limit,
    )
    if not items:
        raise SystemExit("Steam returned no reviews")
    if any(len(item.source_id) < 8 for item in items):
        raise SystemExit("Steam review IDs were not anonymized")
    print(f"Steam smoke passed: {len(items)} anonymized reviews")


if __name__ == "__main__":
    main()
```

The script prints only an aggregate count; it must not print raw review text or IDs.

- [ ] **Step 7: mock 기반 connector와 격리 테스트 실행**

Run:

```bash
uv run pytest tests/test_connectors.py tests/test_agents.py tests/test_orchestrator.py -v
```

Expected: 자동 테스트는 네트워크 없이 통과하고 fixture와 live evidence가 섞이지 않는다.

- [ ] **Step 8: 실제 Steam smoke를 명시적으로 실행**

Run:

```bash
uv run python scripts/smoke_steam.py --app-id 578080 --language en --limit 10
```

Expected: `Steam smoke passed: N anonymized reviews`, where `N >= 1`. Steam 공식 GetReviews가 unavailable이면 자동 테스트를 실패시키지 말고 실행 시각과 오류를 발표 체크리스트에 기록한다.

- [ ] **Step 9: README에 실시간 검증 명령과 의미 추가**

Append:

```markdown
### 실시간 갱신 확인

`uv run python scripts/smoke_steam.py --app-id 578080 --language en --limit 10`

이 명령은 Steam의 현재 리뷰를 메모리에서 읽고 비식별화 여부만 확인합니다. 원문과
사용자 식별자는 저장하지 않습니다. 네트워크 장애 시 저장된 검증 데이터 시연은
계속 사용할 수 있습니다.
```

- [ ] **Step 10: 커밋**

```bash
git add agents/collector/agent.py connectors/steam/client.py orchestrator.py \
  scripts/smoke_steam.py tests/test_connectors.py tests/test_agents.py \
  tests/test_orchestrator.py README.md
git commit -m "Isolate live Steam refresh from fixture runs"
```

---

### Task 11: 최종 성공 게이트·CI·발표 런북 완성

**Files:**
- Modify: `evaluation/verify_success.py`
- Modify: `tests/test_success_gate.py`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/demo/2026-08-12-controlled-hybrid-demo-runbook.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 재현성 결과, 의미 검증, 실행 이벤트, fixture `Revise`, 부족 자료 `Hold`
- Produces: `SuccessReport.event_sequence_valid`, CI 필수 게이트, 발표 복구 절차

- [ ] **Step 1: 성공 게이트가 이벤트 순서까지 요구하도록 실패 테스트 추가**

Append to `tests/test_success_gate.py`:

```python
assert report.reproducible_core
assert report.semantic_links_valid
assert report.event_sequence_valid
assert len(report.input_snapshot_hash) == 64
```

- [ ] **Step 2: 테스트가 `event_sequence_valid` 부재로 실패하는지 확인**

Run:

```bash
uv run pytest tests/test_success_gate.py -v
```

Expected: `SuccessReport`에 `event_sequence_valid`가 없어 실패.

- [ ] **Step 3: 성공 보고서에 실행 순서 검증 추가**

Add `event_sequence_valid: bool` to `SuccessReport`. Compute it without duplicating the entire
event list:

```python
complete_order = [
    item.agent for item in result.events
    if item.state == ExecutionState.COMPLETE and item.agent in AGENT_ORDER
]
event_sequence_valid = complete_order[:4] == list(AGENT_ORDER)
```

Include it in the `passed` conjunction and return payload.

- [ ] **Step 4: CI가 editable package discovery에 의존하지 않게 고정**

Use this exact test portion in `.github/workflows/ci.yml`:

```yaml
      - run: python -m pip install -r requirements.txt
      - run: python -m pip install 'pytest>=8,<10'
      - run: python -m pytest
      - run: python -m evaluation.verify_success
      - run: python -c "import streamlit_app"
```

Do not call `scripts/smoke_steam.py` in CI; it is an opt-in pre-demo network check.

- [ ] **Step 5: 발표 런북 작성**

Create `docs/demo/2026-08-12-controlled-hybrid-demo-runbook.md` with these exact sections and checks:

```markdown
# 게임체인저 발표 런북

## 발표 전 자동 확인

1. `uv sync --extra dev --locked`
2. `uv run pytest`
3. `uv run python -m evaluation.verify_success`
4. `uv run python scripts/smoke_steam.py --app-id 578080 --language en --limit 10`

Steam이 실패하면 오류와 확인 시각을 기록하고 저장 데이터 경로로 진행한다.

## 기본 시연

1. `uv run streamlit run streamlit_app.py`
2. `검증된 저장 데이터`를 선택한다.
3. 네 에이전트 카드가 모두 펼쳐지고 현재 내부 노드가 바뀌는지 확인한다.
4. 완료 후 `최종 판정: Revise`가 먼저 보이는지 확인한다.
5. 네 에이전트 추적 항목을 하나씩 펼쳐 계약과 근거 ID를 보여준다.
6. 같은 입력을 다시 실행하고 핵심 위험·근거·판정이 같은지 설명한다.

## 예외 시연

1. 근거 부족 fixture로 `Hold`를 보여준다.
2. LLM 설명 실패 시 규칙 기반 안전 경로 표시를 보여준다.
3. Steam 실시간 갱신 실패가 저장 데이터 결과를 덮어쓰지 않음을 보여준다.

## 강사 설명

> AI는 비정형 의견을 읽고 설명 후보를 만드는 분석가이고, 프로그램은 실제 근거와
> 고정 기준을 확인해 최종 판정을 내리는 심사위원·감사자입니다.

## 백업

- 1순위: 배포본
- 2순위: 로컬 실행본
- 3순위: 같은 시나리오의 화면 녹화본
```

- [ ] **Step 6: 전체 자동 검증 실행**

Run:

```bash
uv run pytest
uv run python -m evaluation.verify_success
uv run python -c "import streamlit_app"
```

Expected: 전체 테스트 통과, 성공 보고서 `passed: true`, import 성공.

- [ ] **Step 7: 로컬 UI 수동 확인**

Run:

```bash
uv run streamlit run streamlit_app.py
```

Check in the browser:

- 실행 중 네 카드가 동시에 보이고 현재 노드만 강조된다.
- 완료 후 `Revise`와 핵심 위험이 카드보다 먼저 보인다.
- 네 에이전트 추적은 기본으로 접혀 있고 선택하면 근거가 보인다.
- fixture 실행은 인위적인 지연 없이 끝난다.
- 실시간 실행 오류 뒤 이전 결과가 현재 실행 결과처럼 남지 않는다.

- [ ] **Step 8: 최종 변경 범위와 금지 데이터 확인**

Run:

```bash
git diff --check
git status --short
git ls-files .data .streamlit/secrets.toml .env
git diff --name-only origin/main...HEAD -- .claude hy jelly res seungjinbae TEAM.md
```

Expected: whitespace 오류 없음, secrets·실행 로그 출력 없음, 멤버 전용 경로 변경 없음.

- [ ] **Step 9: 최종 문서·게이트 커밋**

```bash
git add evaluation/verify_success.py tests/test_success_gate.py \
  .github/workflows/ci.yml docs/demo/2026-08-12-controlled-hybrid-demo-runbook.md README.md
git commit -m "Finalize controlled hybrid MVP success gate"
```

- [ ] **Step 10: 브랜치를 원격에 올리고 PR 확인**

Run:

```bash
git push -u origin feat/20260812-res-controlled-hybrid-mvp
gh pr create \
  --base main \
  --head feat/20260812-res-controlled-hybrid-mvp \
  --title "Build controlled hybrid multi-agent MVP" \
  --body-file .github/pull_request_template.md
gh pr checks --watch
```

Expected: PR URL이 생성되고 필수 CI가 통과한다. PR 본문 체크리스트는 실제 변경 범위에 맞게 GitHub에서 확인·완성한다.

---

## Optional Follow-up After MVP Acceptance

다음 항목은 Task 1~11과 발표 리허설이 모두 끝난 뒤에만 별도 설계·계획으로 진행한다.

- 두 번째 PUBG 이벤트 fixture와 전문가 평가표
- PUBG 패치용 입력 계약
- 다른 게임 이벤트
- X 실제 연동
- 실행 이력 비교 화면

MVP 완료 조건에 이 항목들을 포함하지 않는다.
