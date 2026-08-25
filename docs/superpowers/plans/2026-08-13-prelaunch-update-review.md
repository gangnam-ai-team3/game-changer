# 출시 전 업데이트 점검 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 이벤트 점검을 보존하면서, Dragunov 확률 피해 제거 사례를 기본 저장 데이터로 사용하는 출시 전 업데이트 점검 모드를 FastAPI·React 서비스에 추가한다.

**Architecture:** 기존 `Artifact`·`ExecutionEvent`·Claude 구조화 출력 런타임은 재사용하고, 이벤트 계약과 판정 정책은 수정하지 않는다. 업데이트 전용 계약과 4단계 파이프라인을 `update_review/` 패키지에 두고, 코드가 근거 ID·기간·위험·최종 판정을 고정하며 Claude는 연결된 한국어 설명만 보강한다. FastAPI는 업데이트 전용 실행·SSE 엔드포인트를 제공하고, Next.js는 상단 모드 선택과 전용 입력·결과를 추가한다.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, Anthropic SDK, pytest, Next.js 16.3.0, React 19.2.0, TypeScript 5.7.2, native CSS

**Spec:** `docs/superpowers/specs/2026-08-13-prelaunch-update-review-design.md`

## Global Constraints

- 기존 `EventBrief → DecisionBrief` 계약, `policy.py`, `/api/runs`, Black Market·Weekly Supply 경로는 그대로 보존한다.
- 기본 시연은 외부 API가 없어도 완주하는 `dragunov_random_damage_removal` 합성 저장 사례를 사용한다.
- 합성 의견은 모두 `synthetic=true`, `period=comparable_reference`로 저장하고 실제 사후 여론으로 표현하지 않는다.
- `before`, `after`, `comparable_reference`를 데이터·API·UI에서 구분하고, `after`가 없으면 실제 반응 영역을 숨긴다.
- 코드가 업데이트 유형별 필수 입력, 근거 참조, 위험 승인·기각, 검증 지표 연결, `Go|Revise|Test|Hold` 판정을 소유한다.
- Claude는 코드가 만든 구조의 ID 범위 안에서 한국어 자연어만 보강한다. 구조 오류는 전체 3회 요청 한도 안에서 최대 1회 재시도하고, 한도가 없거나 재시도도 실패하면 저장 사례는 결정론적 안전 경로로 전환한다.
- Claude 예산 가드는 기존 `CLAUDE_MAX_USD=5`, `CLAUDE_MAX_REQUESTS=3`, `CLAUDE_MAX_OUTPUT_TOKENS=1400`을 재사용한다.
- 기본 모델은 변경 영향 분석에 `claude-sonnet-4-6`, 레드팀·검증 설명에 `claude-haiku-4-5`를 사용한다.
- 실시간 Steam·X는 사용자가 명시적으로 선택한 때만 호출하고, 실패·표본 부족 시 저장 사례로 자동 대체하지 않는다.
- 외부 자료는 HTTPS URL·비식별 `source_id`를 필수로 하고, 원문·사용자명·계정 ID·API 키를 artifact·SSE·JSONL에 저장하지 않는다.
- 예측 문장은 `예상`, `가능성`, `확인 필요` 표현을 포함하고, 사용자 표시 문구는 한국어를 기본으로 한다.
- 새 외부 패키지를 추가하지 않고, 현재 설치된 Pydantic·FastAPI·Anthropic·React·native CSS만 사용한다.
- 외부 API 호출은 전부 fake client로 테스트하고, 실제 Claude·Steam·X 요금을 테스트에서 사용하지 않는다.
- 프론트엔드 수정 전 `frontend/node_modules/next/dist/docs/` 안의 현재 Next 16 관련 문서를 읽고, `frontend/AGENTS.md`를 준수한다.

---

## File Structure

### Create

- `update_review/__init__.py`: 업데이트 점검의 공개 계약·오케스트레이터 export.
- `update_review/contracts.py`: 업데이트 유형, 기간, 감정, 신호, 영향, 위험, 판정 artifact 계약과 참조 검증.
- `update_review/policy.py`: 폐쇄형 위험 정책, 표본 게이트, `Go|Revise|Test|Hold` 결정.
- `update_review/fixtures.py`: Dragunov 기본 `UpdateBrief`와 합성 저장 자료 loader.
- `update_review/collector.py`: 저장·CSV·Steam·X 입력을 `UpdateFeedbackBundle`로 정규화하고 원문을 즉시 폐기.
- `update_review/evidence.py`: 변경 요소별 긍정·부정 신호, 반응 분기 조건, 이용자 유형 영향 생성.
- `update_review/redteam.py`: 예상 영향, 실패 경로, 출시 후 검증 지표 생성.
- `update_review/audit.py`: 근거·위험·지표 참조를 검증하고 코드 정책으로 판정·최종 brief 생성.
- `update_review/orchestrator.py`: 4개 에이전트 순차 실행, 계약 검증, Claude 재시도·안전 경로, SSE 이벤트 연결.
- `update_review/prompts/evidence.md`: Sonnet이 근거 ID를 바꾸지 않고 한국어 신호·이용자 영향 설명을 보강하는 프롬프트.
- `update_review/prompts/collector.md`: live 원문을 복사하지 않고 감정·태그·비식별 한국어 요약으로 변환하는 Haiku 프롬프트.
- `update_review/prompts/redteam.md`: Haiku가 코드가 연 위험·지표 ID 안에서 실패 경로를 보강하는 프롬프트.
- `update_review/prompts/audit.md`: Haiku가 고정 판정을 바꾸지 않고 요약·권고문을 보강하는 프롬프트.
- `fixtures/dragunov_random_damage_removal.jsonl`: 5개 언어권·감정·메커니즘을 담은 비식별 합성 저장 자료.
- `evaluation/verify_update_success.py`: Dragunov 사례의 재현성·참조·판정·사후 반응 미표시 성공 게이트.
- `frontend/app/components/AgentPipeline.tsx`: 이벤트·업데이트가 공유하는 4행 에이전트/노드 실행 시각화.
- `frontend/app/components/UpdateReview.tsx`: 업데이트 유형별 입력, 소스 선택, SSE 실행, 출시 전 결과 UI.
- `tests/test_update_contracts.py`: 유형별 필수값, 기간·감정, cutoff, 근거 참조 계약 테스트.
- `tests/test_update_pipeline.py`: 저장 사례 재현성, 4단계 산출물, 안전 판정, Claude 병합 테스트.
- `tests/test_update_sources.py`: CSV·Steam·X 기간 필터, 비식별, 실패 시 미대체 테스트.
- `tests/test_update_api.py`: 업데이트 REST·SSE 요청/응답 테스트.
- `tests/test_frontend_update_contract.py`: 모드 선택·한국어 판정·사후 반응 조건부 표시의 정적 계약 테스트.
- `tests/test_update_success_gate.py`: 업데이트 성공 게이트와 사후 반응 누출 실패 테스트.

### Modify

- `connectors/steam/client.py`: 기존 시그니처를 보존한 선택 `start_at` 기간 필터 추가.
- `connectors/x/client.py`: 기존 시그니처를 보존한 선택 `start_at` 기간 필터 추가.
- `agents/structured.py`: Claude가 구조화 도구를 반환하지 않은 경우를 `LLM_REFUSAL`로 정규화.
- `backend/app/schemas.py`: 업데이트 입력 유형별 request union과 소스 검증 추가.
- `backend/app/main.py`: `/api/update-runs`, `/api/update-runs/stream` 추가; 기존 엔드포인트 보존.
- `backend/.env.example`: 업데이트 전용 Claude 모델명 예시 추가.
- `frontend/app/page.tsx`: 기존 이벤트 화면을 보존하고 검토 대상 모드 선택과 공유 파이프라인 import 추가.
- `frontend/app/globals.css`: 모드 선택, 업데이트 유형 카드, 긍정·부정·검증 지표 레이아웃 추가.
- `README.md`: 업데이트 점검 범위·안전 문구·검증 명령 추가.

### Reuse without changing

- `contracts.Artifact`, `contracts.ArtifactStatus`, `contracts.ErrorCode`, `contracts.InputMode`, `contracts.Language`, `contracts.LanguageSample`, `contracts.PersonaKind`, `contracts.PipelineError`, `contracts.Producer`, `contracts.SearchRecord`, `contracts.Severity`, `contracts.SourceType`
- `execution.AGENT_ORDER`, `execution.ExecutionEvent`, `execution.ExecutionState`, `execution.EventCallback`
- `connectors.RawFeedback`, `connectors.ConnectorError`, `connectors.x.ProjectBudget`

---

### Task 1: 업데이트 전용 계약과 판정 정책

**Files:**
- Create: `update_review/__init__.py`
- Create: `update_review/contracts.py`
- Create: `update_review/policy.py`
- Create: `tests/test_update_contracts.py`

**Interfaces:**
- Consumes: `contracts.Artifact`, `LanguageSample`, `PersonaKind`, `Producer`, `Severity`, `SourceType`
- Produces: `UpdateBrief`, `UpdateFeedbackBundle`, `UpdateEvidencePack`, `UpdateImpactAssessment`, `UpdateValidatedDecision`, `UpdateDecisionBrief`
- Produces: `decide_update(samples: list[LanguageSample], risks: list[UpdateRiskItem], *, metrics_complete: bool, analysis_incomplete: bool = False) -> tuple[UpdateDecision, str]`

- [ ] **Step 1: 유형별 필수 입력과 반응 기간 계약의 실패 테스트를 작성한다**

`tests/test_update_contracts.py`에 다음 factory와 테스트를 작성한다.

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from contracts import ArtifactStatus, Language, PersonaKind, Producer, Severity, SourceType
from update_review.contracts import (
    EvidencePeriod,
    ReactionSignal,
    Sentiment,
    UpdateBrief,
    UpdateEvidencePack,
    UpdateEvidenceItem,
    UpdateFeedbackBundle,
    UpdateRiskCategory,
    UpdateRiskItem,
    UpdateType,
    UiUxDetails,
    WeaponBalanceDetails,
    SystemRulesDetails,
)


NOW = datetime(2026, 8, 13, tzinfo=UTC)


def weapon_brief(**updates) -> UpdateBrief:
    values = {
        "run_id": "update-run",
        "status": ArtifactStatus.COMPLETE,
        "producer": Producer.USER,
        "game": "PUBG: BATTLEGROUNDS",
        "update_name": "Dragunov 확률 피해 제거",
        "update_type": UpdateType.WEAPON_BALANCE,
        "current_state": "기본 58, 최대 73의 확률형 피해",
        "change_summary": "피해를 60으로 고정",
        "goal": "결과 예측 가능성을 높인다.",
        "expected_benefits": ["공정성 인식 개선"],
        "concerns": ["실제 전투 성능은 확인 필요"],
        "scope": "일반 매칭",
        "planned_at": NOW + timedelta(days=7),
        "cutoff_at": NOW,
        "official_context": "PUBG Update 25.2에서 이용자 피드백을 바탕으로 확률형 피해를 제거했다는 공식 변경 맥락",
        "official_context_url": "https://pubg.com/en/news/6616",
        "details": WeaponBalanceDetails(
            target_weapon="Dragunov",
            damage="58~73 확률 → 60 고정",
            recoil="현행 유지",
            rate_of_fire="해당 없음",
            ammunition="7.62mm",
            spawn_and_modes="일반 매칭",
        ),
    }
    values.update(updates)
    return UpdateBrief(**values)


def evidence(evidence_id: str = "fx-dragunov-ko-001", **updates) -> UpdateEvidenceItem:
    values = {
        "evidence_id": evidence_id,
        "source": SourceType.SYNTHETIC,
        "source_url": "https://pubg.com/en/news/6616",
        "source_id": f"synthetic-{evidence_id}",
        "language": Language.KOREAN,
        "observed_at": NOW - timedelta(days=1),
        "period": EvidencePeriod.COMPARABLE_REFERENCE,
        "sentiment": Sentiment.POSITIVE,
        "summary": "합성 관점에서 고정 피해가 결과 예측 가능성을 높일 가능성이 있음.",
        "mechanism_tags": ["predictability"],
        "relevance": 0.9,
        "synthetic": True,
    }
    values.update(updates)
    return UpdateEvidenceItem(**values)


def test_weapon_details_accept_explicit_not_applicable():
    assert weapon_brief().details.rate_of_fire == "해당 없음"


def test_update_type_must_match_discriminated_details():
    with pytest.raises(ValidationError, match="details kind must match update_type"):
        weapon_brief(update_type=UpdateType.UI_UX)


def test_ui_ux_requires_every_type_specific_field_but_accepts_not_applicable():
    with pytest.raises(ValidationError, match="possible_errors"):
        UiUxDetails(
            changed_screen="상점",
            user_journey="상품 선택 → 결제",
            exposed_information="확률",
            possible_errors="",
        )
    assert UiUxDetails(
        changed_screen="상점",
        user_journey="상품 선택 → 결제",
        exposed_information="확률",
        possible_errors="해당 없음",
    ).possible_errors == "해당 없음"


def test_system_rules_requires_existing_user_impact():
    with pytest.raises(ValidationError, match="existing_user_impact"):
        SystemRulesDetails(
            participation_conditions="레벨 10 이상",
            rewards="BP",
            restrictions="주 1회",
            exception_rules="해당 없음",
            existing_user_impact="",
        )


def test_feedback_rejects_cutoff_leakage():
    brief = weapon_brief()
    with pytest.raises(ValidationError, match="cutoff leakage"):
        UpdateFeedbackBundle(
            run_id=brief.run_id,
            producer=Producer.COLLECTOR,
            input_refs=[brief.ref],
            input_mode="fixture",
            cutoff_at=brief.cutoff_at,
            search_log=[],
            samples=[],
            evidence=[evidence(observed_at=brief.cutoff_at)],
        )


def test_comparable_reference_is_not_actual_after_reaction():
    item = evidence()
    assert item.period is EvidencePeriod.COMPARABLE_REFERENCE
    assert item.period is not EvidencePeriod.AFTER


def test_reaction_signal_rejects_unknown_evidence_reference():
    with pytest.raises(ValueError, match="unknown evidence"):
        ReactionSignal(
            signal_id="positive-predictability",
            title="예측 가능성 상승",
            summary="고정 피해가 공정성 인식을 높일 가능성이 있음.",
            sentiment=Sentiment.POSITIVE,
            evidence_ids=["missing-id"],
            confidence=0.8,
        ).validate_refs({"known-id"})


def test_evidence_pack_rejects_sentiment_label_mismatch():
    with pytest.raises(ValidationError, match="positive signal references non-positive evidence"):
        UpdateEvidencePack(
            run_id="update-run",
            producer=Producer.EVIDENCE_RAG,
            input_refs=["collector:update-run"],
            positive_signals=[ReactionSignal(
                signal_id="positive-predictability",
                title="예측 가능성 상승",
                summary="결과를 예측하기 쉬워질 가능성이 있음.",
                sentiment=Sentiment.POSITIVE,
                evidence_ids=["fx-negative"],
                confidence=0.8,
            )],
            negative_signals=[],
            split_conditions=[],
            persona_impacts=[],
            language_insights=[],
            evidence=[evidence("fx-negative", sentiment=Sentiment.NEGATIVE)],
        )
```

- [ ] **Step 2: 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_contracts.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'update_review'`.

- [ ] **Step 3: 업데이트 계약을 최소 구현한다**

`update_review/contracts.py`에 다음 공개 타입과 검증을 구현한다. 문장 필드는 `Field(min_length=1)`로 두어 `"해당 없음"`은 유효하고 빈 문자열은 거절한다.

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import (
    Artifact,
    InputMode,
    Language,
    LanguageSample,
    PersonaKind,
    SearchRecord,
    Severity,
    SourceType,
)


class UpdateType(StrEnum):
    WEAPON_BALANCE = "weapon_balance"
    UI_UX = "ui_ux"
    SYSTEM_RULES = "system_rules"


class EvidencePeriod(StrEnum):
    BEFORE = "before"
    AFTER = "after"
    COMPARABLE_REFERENCE = "comparable_reference"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class UpdateDecision(StrEnum):
    GO = "Go"
    REVISE = "Revise"
    TEST = "Test"
    HOLD = "Hold"


class UpdateRiskCategory(StrEnum):
    BALANCE_REGRESSION = "balance_regression"
    FAIRNESS_REGRESSION = "fairness_regression"
    INFORMATION_CLARITY = "information_clarity"
    FLOW_DISRUPTION = "flow_disruption"
    RULE_EXCEPTION = "rule_exception"
    LEARNING_BURDEN = "learning_burden"


class WeaponBalanceDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["weapon_balance"] = "weapon_balance"
    target_weapon: str = Field(min_length=1)
    damage: str = Field(min_length=1)
    recoil: str = Field(min_length=1)
    rate_of_fire: str = Field(min_length=1)
    ammunition: str = Field(min_length=1)
    spawn_and_modes: str = Field(min_length=1)


class UiUxDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ui_ux"] = "ui_ux"
    changed_screen: str = Field(min_length=1)
    user_journey: str = Field(min_length=1)
    exposed_information: str = Field(min_length=1)
    possible_errors: str = Field(min_length=1)


class SystemRulesDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["system_rules"] = "system_rules"
    participation_conditions: str = Field(min_length=1)
    rewards: str = Field(min_length=1)
    restrictions: str = Field(min_length=1)
    exception_rules: str = Field(min_length=1)
    existing_user_impact: str = Field(min_length=1)


UpdateDetails = Annotated[
    WeaponBalanceDetails | UiUxDetails | SystemRulesDetails,
    Field(discriminator="kind"),
]


class UpdateBrief(Artifact):
    game: str = Field(min_length=1)
    update_name: str = Field(min_length=1)
    update_type: UpdateType
    current_state: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_benefits: list[str] = Field(min_length=1)
    concerns: list[str] = Field(min_length=1)
    scope: str = Field(min_length=1)
    planned_at: datetime
    cutoff_at: datetime
    official_context: str | None = Field(default=None, min_length=1)
    official_context_url: str | None = Field(default=None, pattern=r"^https://")
    details: UpdateDetails

    @model_validator(mode="after")
    def validate_update(self) -> UpdateBrief:
        if self.cutoff_at > self.planned_at:
            raise ValueError("cutoff_at must not be later than planned_at")
        if self.cutoff_at.tzinfo is None or self.planned_at.tzinfo is None:
            raise ValueError("update datetimes must be timezone-aware")
        if self.details.kind != self.update_type.value:
            raise ValueError("details kind must match update_type")
        return self


class UpdateEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    source: SourceType
    source_url: str = Field(pattern=r"^https://")
    source_id: str = Field(min_length=8)
    language: Language
    observed_at: datetime
    period: EvidencePeriod
    sentiment: Sentiment
    summary: str = Field(min_length=8, max_length=500)
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)
    synthetic: bool = False
    contains_personal_data: Literal[False] = False


class UpdateFeedbackBundle(Artifact):
    input_mode: InputMode
    cutoff_at: datetime
    search_log: list[SearchRecord]
    samples: list[LanguageSample]
    evidence: list[UpdateEvidenceItem]

    @model_validator(mode="after")
    def validate_bundle(self) -> UpdateFeedbackBundle:
        if len({sample.language for sample in self.samples}) != len(self.samples):
            raise ValueError("language samples must be unique")
        leaked = [item.evidence_id for item in self.evidence if item.observed_at >= self.cutoff_at]
        if leaked:
            raise ValueError(f"cutoff leakage: {', '.join(leaked[:3])}")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return self


class ReactionSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    sentiment: Sentiment
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    def validate_refs(self, evidence_ids: set[str]) -> ReactionSignal:
        unknown = set(self.evidence_ids) - evidence_ids
        if unknown:
            raise ValueError(f"unknown evidence: {', '.join(sorted(unknown))}")
        return self


class SplitCondition(ReactionSignal):
    sentiment: Literal[Sentiment.MIXED] = Sentiment.MIXED


class UpdateLanguageInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Language
    conclusion: str | None
    hidden_reason: str | None = None
    sentiment_counts: dict[Sentiment, int]
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def explain_hidden_conclusion(self) -> UpdateLanguageInsight:
        if self.conclusion is None and not self.hidden_reason:
            raise ValueError("a hidden conclusion requires hidden_reason")
        return self


class UpdatePersonaImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: PersonaKind
    expected_reaction: str = Field(min_length=1)
    positive_signal_ids: list[str]
    negative_signal_ids: list[str]
    split_signal_ids: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class UpdateEvidencePack(Artifact):
    positive_signals: list[ReactionSignal]
    negative_signals: list[ReactionSignal]
    split_conditions: list[SplitCondition]
    persona_impacts: list[UpdatePersonaImpact]
    language_insights: list[UpdateLanguageInsight]
    evidence: list[UpdateEvidenceItem]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateEvidencePack:
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        evidence_ids = set(evidence_by_id)
        signals = [*self.positive_signals, *self.negative_signals, *self.split_conditions]
        if any(item.sentiment is not Sentiment.POSITIVE for item in self.positive_signals):
            raise ValueError("positive_signals must use positive sentiment")
        if any(item.sentiment is not Sentiment.NEGATIVE for item in self.negative_signals):
            raise ValueError("negative_signals must use negative sentiment")
        signal_ids = {item.signal_id for item in signals}
        for signal in signals:
            signal.validate_refs(evidence_ids)
        for signal in self.positive_signals:
            if any(evidence_by_id[item_id].sentiment is not Sentiment.POSITIVE for item_id in signal.evidence_ids):
                raise ValueError("positive signal references non-positive evidence")
        for signal in self.negative_signals:
            if any(evidence_by_id[item_id].sentiment is not Sentiment.NEGATIVE for item_id in signal.evidence_ids):
                raise ValueError("negative signal references non-negative evidence")
        for signal in self.split_conditions:
            if any(evidence_by_id[item_id].sentiment is not Sentiment.MIXED for item_id in signal.evidence_ids):
                raise ValueError("split condition references non-mixed evidence")
        for impact in self.persona_impacts:
            if not set(impact.evidence_ids) <= evidence_ids:
                raise ValueError("persona impact references unknown evidence")
            if not set(impact.positive_signal_ids + impact.negative_signal_ids + impact.split_signal_ids) <= signal_ids:
                raise ValueError("persona impact references unknown signal")
        for insight in self.language_insights:
            if not set(insight.evidence_ids) <= evidence_ids:
                raise ValueError("language insight references unknown evidence")
        return self


class ExpectedImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    impact_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    affected_personas: list[PersonaKind] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class UpdateRiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: str = Field(min_length=1)
    category: UpdateRiskCategory
    title: str = Field(min_length=1)
    severity: Severity
    affected_personas: list[PersonaKind] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ValidationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    success_condition: str = Field(min_length=1)
    addresses_risk_ids: list[str] = Field(min_length=1)


class UpdateImpactAssessment(Artifact):
    expected_positive: list[ExpectedImpact]
    expected_negative: list[ExpectedImpact]
    risks: list[UpdateRiskItem]
    validation_metrics: list[ValidationMetric]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateImpactAssessment:
        risk_ids = {item.risk_id for item in self.risks}
        evidence_ids = {evidence_id for item in [*self.expected_positive, *self.expected_negative, *self.risks] for evidence_id in item.evidence_ids}
        if not evidence_ids and not self.errors:
            raise ValueError("impact assessment requires evidence")
        for metric in self.validation_metrics:
            if not set(metric.addresses_risk_ids) <= risk_ids:
                raise ValueError("metric references unknown risk")
        if risk_ids and not all(any(risk_id in metric.addresses_risk_ids for metric in self.validation_metrics) for risk_id in risk_ids):
            raise ValueError("every risk requires a validation metric")
        return self


class RejectedUpdateRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class UpdateRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: int = Field(ge=1)
    title: str = Field(min_length=1)
    action: str = Field(min_length=1)
    addresses_risk_ids: list[str] = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class UpdateValidatedDecision(Artifact):
    decision: UpdateDecision
    decision_reason: str = Field(min_length=1)
    validated_risks: list[UpdateRiskItem]
    rejected_risks: list[RejectedUpdateRisk]
    recommendations: list[UpdateRecommendation]
    validation_metrics: list[ValidationMetric]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateValidatedDecision:
        risk_ids = {item.risk_id for item in self.validated_risks}
        metric_ids = {item.metric_id for item in self.validation_metrics}
        for item in self.recommendations:
            if not set(item.addresses_risk_ids) <= risk_ids:
                raise ValueError("recommendation references unknown risk")
            if not set(item.validation_metric_ids) <= metric_ids:
                raise ValueError("recommendation references unknown metric")
        return self


class UpdateDecisionBrief(Artifact):
    decision: UpdateDecision
    executive_summary: str = Field(min_length=1)
    official_context: str | None = Field(default=None, min_length=1)
    official_context_url: str | None = Field(default=None, pattern=r"^https://")
    expected_positive: list[ExpectedImpact]
    expected_negative: list[ExpectedImpact]
    split_conditions: list[SplitCondition]
    persona_impacts: list[UpdatePersonaImpact]
    language_insights: list[UpdateLanguageInsight]
    top_risks: list[UpdateRiskItem]
    validation_metrics: list[ValidationMetric]
    evidence: list[UpdateEvidenceItem]
    recommendations: list[UpdateRecommendation]

    @model_validator(mode="after")
    def validate_refs(self) -> UpdateDecisionBrief:
        evidence_ids = {item.evidence_id for item in self.evidence}
        risk_ids = {item.risk_id for item in self.top_risks}
        metric_ids = {item.metric_id for item in self.validation_metrics}
        for item in [*self.expected_positive, *self.expected_negative, *self.top_risks, *self.split_conditions, *self.persona_impacts, *self.language_insights]:
            if not set(item.evidence_ids) <= evidence_ids:
                raise ValueError("brief references unknown evidence")
        for metric in self.validation_metrics:
            if not set(metric.addresses_risk_ids) <= risk_ids:
                raise ValueError("brief metric references unknown risk")
        for item in self.recommendations:
            if not set(item.addresses_risk_ids) <= risk_ids or not set(item.validation_metric_ids) <= metric_ids:
                raise ValueError("brief recommendation references unknown data")
        return self
```

`update_review/__init__.py`에서 외부가 쓸 계약만 export한다.

```python
from update_review.contracts import (
    UpdateBrief,
    UpdateDecision,
    UpdateDecisionBrief,
    UpdateFeedbackBundle,
    UpdateType,
)

__all__ = [
    "UpdateBrief",
    "UpdateDecision",
    "UpdateDecisionBrief",
    "UpdateFeedbackBundle",
    "UpdateType",
]
```

- [ ] **Step 4: 계약 테스트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_update_contracts.py -v`

Expected: PASS for the eight tests above.

- [ ] **Step 5: 판정 정책의 실패 테스트를 추가한다**

`tests/test_update_contracts.py`에 다음을 추가한다.

```python
from contracts import LanguageSample
from update_review.contracts import UpdateDecision
from update_review.policy import decide_update


def samples(insufficient: int = 0) -> list[LanguageSample]:
    languages = list(Language)
    return [
        LanguageSample(
            language=language,
            general_count=0 if index < insufficient else 100,
            mechanism_count=0 if index < insufficient else 15,
        )
        for index, language in enumerate(languages)
    ]


def risk(category=UpdateRiskCategory.BALANCE_REGRESSION, severity=Severity.MEDIUM):
    return UpdateRiskItem(
        risk_id=f"risk-{category.value}",
        category=category,
        title="성능 역전 가능성",
        severity=severity,
        affected_personas=[PersonaKind.CORE_GAMEPLAY],
        evidence_ids=["fx-dragunov-ko-001"],
        failure_path="고정 피해와 반동의 조합으로 메타가 쏠릴 가능성이 있음.",
        revision_question="테스트 서버에서 승률과 평균 피해를 확인할 수 있는가?",
        confidence=0.8,
    )


@pytest.mark.parametrize(
    ("risks", "insufficient", "metrics_complete", "analysis_incomplete", "expected"),
    [
        ([], 0, True, False, UpdateDecision.GO),
        ([risk()], 0, True, False, UpdateDecision.TEST),
        ([risk(UpdateRiskCategory.FAIRNESS_REGRESSION, Severity.HIGH)], 0, True, False, UpdateDecision.REVISE),
        ([], 3, True, False, UpdateDecision.HOLD),
        ([], 0, False, False, UpdateDecision.HOLD),
        ([], 0, True, True, UpdateDecision.HOLD),
    ],
)
def test_update_decision_policy(risks, insufficient, metrics_complete, analysis_incomplete, expected):
    decision, reason = decide_update(
        samples(insufficient),
        risks,
        metrics_complete=metrics_complete,
        analysis_incomplete=analysis_incomplete,
    )
    assert decision is expected
    assert reason
```

- [ ] **Step 6: 판정 정책 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_contracts.py::test_update_decision_policy -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'update_review.policy'`.

- [ ] **Step 7: 폐쇄형 위험 정책과 판정 순서를 구현한다**

`update_review/policy.py`를 다음과 같이 작성한다.

```python
from contracts import LanguageSample, Severity
from update_review.contracts import UpdateDecision, UpdateRiskCategory, UpdateRiskItem


POLICY_VERSION = "1.0"
MIN_RISK_CONFIDENCE = 0.5

CLOSED_UPDATE_RISK_SEVERITY = {
    UpdateRiskCategory.BALANCE_REGRESSION: Severity.MEDIUM,
    UpdateRiskCategory.FAIRNESS_REGRESSION: Severity.HIGH,
    UpdateRiskCategory.INFORMATION_CLARITY: Severity.HIGH,
    UpdateRiskCategory.FLOW_DISRUPTION: Severity.HIGH,
    UpdateRiskCategory.RULE_EXCEPTION: Severity.HIGH,
    UpdateRiskCategory.LEARNING_BURDEN: Severity.MEDIUM,
}

TEST_REQUIRED = {
    UpdateRiskCategory.BALANCE_REGRESSION,
    UpdateRiskCategory.LEARNING_BURDEN,
}

UPDATE_RISK_TAGS = {category: category.value for category in CLOSED_UPDATE_RISK_SEVERITY}


def expected_severity(category: UpdateRiskCategory) -> Severity:
    return CLOSED_UPDATE_RISK_SEVERITY[category]


def decide_update(
    samples: list[LanguageSample],
    risks: list[UpdateRiskItem],
    *,
    metrics_complete: bool,
    analysis_incomplete: bool = False,
) -> tuple[UpdateDecision, str]:
    if analysis_incomplete:
        return UpdateDecision.HOLD, "새 자료의 AI 해석이 완료되지 않아 판정을 보류한다."
    if not metrics_complete:
        return UpdateDecision.HOLD, "모든 위험에 연결된 출시 후 확인 지표가 없어 판정을 보류한다."
    if any(item.severity == Severity.CRITICAL for item in risks):
        return UpdateDecision.HOLD, "검증된 Critical 위험이 있어 출시 판정을 보류한다."
    insufficient = sum(not sample.sufficient for sample in samples)
    if insufficient >= 3:
        return UpdateDecision.HOLD, "세 언어권 이상이 최소 표본에 미달해 판정 근거가 부족하다."
    if any(item.severity == Severity.HIGH for item in risks):
        return UpdateDecision.REVISE, "검증된 High 위험을 수정한 뒤 출시해야 한다."
    if insufficient or any(item.category in TEST_REQUIRED for item in risks):
        return UpdateDecision.TEST, "남은 불확실성을 테스트 서버·제한 공개로 확인한 뒤 출시해야 한다."
    return UpdateDecision.GO, "필수 표본과 확인 지표를 갖추고 High 이상 위험이 없다."
```

- [ ] **Step 8: 계약·정책 테스트와 기존 계약 회귀를 확인한다**

Run: `uv run pytest tests/test_update_contracts.py tests/test_contracts.py tests/test_policy.py -v`

Expected: PASS.

- [ ] **Step 9: Task 1을 커밋한다**

```bash
git add update_review/__init__.py update_review/contracts.py update_review/policy.py tests/test_update_contracts.py
git commit -m "feat: add update review contracts and policy"
```

---

### Task 2: Dragunov 합성 저장 사례와 자료 수집 에이전트

**Files:**
- Create: `fixtures/dragunov_random_damage_removal.jsonl`
- Create: `update_review/fixtures.py`
- Create: `update_review/collector.py`
- Modify: `tests/test_update_pipeline.py`

**Interfaces:**
- Consumes: `UpdateBrief`, `UpdateFeedbackBundle`, `UpdateEvidenceItem`
- Produces: `load_dragunov_brief(run_id: str) -> UpdateBrief`
- Produces: `load_update_feedback_fixture(brief: UpdateBrief, case: str = "dragunov_random_damage_removal") -> UpdateFeedbackBundle`
- Produces: `UpdateCollectionOptions` and `UpdateCollectorAgent.run(brief: UpdateBrief, options: UpdateCollectionOptions, on_event: NodeCallback | None = None) -> UpdateFeedbackBundle`

- [ ] **Step 1: 저장 사례의 출처·기간·감정 표시 테스트를 작성한다**

`tests/test_update_pipeline.py`를 다음으로 시작한다.

```python
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import EvidencePeriod, Sentiment, UpdateType
from update_review.fixtures import load_dragunov_brief, load_update_feedback_fixture


def test_dragunov_fixture_is_synthetic_comparable_reference():
    brief = load_dragunov_brief("dragunov-fixture")
    bundle = load_update_feedback_fixture(brief)
    assert brief.update_type is UpdateType.WEAPON_BALANCE
    assert brief.details.damage == "기본 58·최대 73 확률 → 60 고정"
    assert "공식 변경 맥락" in brief.official_context
    assert brief.official_context_url == "https://pubg.com/en/news/6616"
    assert len(bundle.evidence) == 75
    assert len(bundle.samples) == 5
    assert all(item.synthetic for item in bundle.evidence)
    assert {item.period for item in bundle.evidence} == {EvidencePeriod.COMPARABLE_REFERENCE}
    assert {item.sentiment for item in bundle.evidence} == set(Sentiment)
    assert all(item.source_url.startswith("https://") for item in bundle.evidence)
    assert all(item.observed_at < brief.cutoff_at for item in bundle.evidence)


def test_fixture_collector_emits_five_named_nodes():
    brief = load_dragunov_brief("dragunov-nodes")
    nodes = []
    bundle = UpdateCollectorAgent().run(
        brief,
        UpdateCollectionOptions(),
        on_event=lambda node, message, metrics: nodes.append((node, message, metrics)),
    )
    assert bundle.input_refs == [brief.ref]
    assert [node for node, _, _ in nodes] == [
        "source_selected",
        "period_checked",
        "anonymized",
        "samples_counted",
        "bundle_ready",
    ]
    assert all(message for _, message, _ in nodes)
```

- [ ] **Step 2: 저장 사례 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'update_review.collector'`.

- [ ] **Step 3: 5개 언어권 합성 자료를 작성한다**

`fixtures/dragunov_random_damage_removal.jsonl`을 다음 5개 JSONL 행으로 작성한다. loader는 각 행의 `templates`를 순환해 언어별 15개, 전체 75개 근거를 만든다.

```jsonl
{"language":"en","general_count":100,"mechanism_count":15,"templates":[{"sentiment":"positive","tag":"predictability","text":"Synthetic viewpoint: fixed damage may make combat outcomes easier to predict."},{"sentiment":"positive","tag":"skill_fairness","text":"Synthetic viewpoint: removing random damage may feel more aligned with player skill and fairness."},{"sentiment":"negative","tag":"balance_regression","text":"Synthetic viewpoint: fixed damage may feel too weak or too strong when recoil and fire rate are considered."},{"sentiment":"neutral","tag":"validation_needed","text":"Synthetic viewpoint: usage rate, win rate, and average damage need test-server confirmation."},{"sentiment":"mixed","tag":"validation_needed","text":"Synthetic viewpoint: fairness may improve, while the resulting weapon meta still needs confirmation."}]}
{"language":"ko","general_count":100,"mechanism_count":15,"templates":[{"sentiment":"positive","tag":"predictability","text":"합성 관점: 피해를 고정하면 전투 결과를 예측하기 쉬워질 가능성이 있음."},{"sentiment":"positive","tag":"skill_fairness","text":"합성 관점: 확률 피해 제거가 실력 중심 전투와 공정성 인식에 더 부합할 가능성이 있음."},{"sentiment":"negative","tag":"balance_regression","text":"합성 관점: 반동과 연사 속도를 함께 보면 고정 피해가 너무 낮거나 높게 체감될 가능성이 있음."},{"sentiment":"neutral","tag":"validation_needed","text":"합성 관점: 사용률·승률·평균 피해는 테스트 서버에서 확인 필요."},{"sentiment":"mixed","tag":"validation_needed","text":"합성 관점: 공정성은 개선될 수 있지만 무기 메타 변화는 확인 필요."}]}
{"language":"zh-CN","general_count":100,"mechanism_count":15,"templates":[{"sentiment":"positive","tag":"predictability","text":"合成观点：固定伤害可能让战斗结果更容易预测。"},{"sentiment":"positive","tag":"skill_fairness","text":"合成观点：移除随机伤害可能更符合技巧和公平性。"},{"sentiment":"negative","tag":"balance_regression","text":"合成观点：结合后坐力和射速后，固定伤害可能显得过弱或过强。"},{"sentiment":"neutral","tag":"validation_needed","text":"合成观点：使用率、胜率和平均伤害需要在测试服验证。"},{"sentiment":"mixed","tag":"validation_needed","text":"合成观点：公平性可能改善，但武器环境变化仍需确认。"}]}
{"language":"es","general_count":100,"mechanism_count":15,"templates":[{"sentiment":"positive","tag":"predictability","text":"Perspectiva sintética: el daño fijo puede hacer más predecibles los resultados del combate."},{"sentiment":"positive","tag":"skill_fairness","text":"Perspectiva sintética: quitar el daño aleatorio puede alinearse mejor con la habilidad y la equidad."},{"sentiment":"negative","tag":"balance_regression","text":"Perspectiva sintética: el daño fijo puede sentirse demasiado bajo o alto junto con el retroceso y la cadencia."},{"sentiment":"neutral","tag":"validation_needed","text":"Perspectiva sintética: el uso, la victoria y el daño medio requieren validación en el servidor de pruebas."},{"sentiment":"mixed","tag":"validation_needed","text":"Perspectiva sintética: la equidad puede mejorar, pero el cambio del meta aún debe comprobarse."}]}
{"language":"pt-BR","general_count":100,"mechanism_count":15,"templates":[{"sentiment":"positive","tag":"predictability","text":"Perspectiva sintética: o dano fixo pode tornar o resultado do combate mais previsível."},{"sentiment":"positive","tag":"skill_fairness","text":"Perspectiva sintética: remover o dano aleatório pode se alinhar melhor com habilidade e justiça."},{"sentiment":"negative","tag":"balance_regression","text":"Perspectiva sintética: o dano fixo pode parecer baixo ou alto demais junto do recuo e da cadência."},{"sentiment":"neutral","tag":"validation_needed","text":"Perspectiva sintética: uso, vitórias e dano médio precisam de confirmação no servidor de testes."},{"sentiment":"mixed","tag":"validation_needed","text":"Perspectiva sintética: a justiça pode melhorar, mas a mudança do meta ainda precisa ser confirmada."}]}
```

- [ ] **Step 4: Dragunov brief와 fixture loader를 구현한다**

`update_review/fixtures.py`에 다음 함수를 구현한다.

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from contracts import ArtifactStatus, InputMode, Language, LanguageSample, Producer, SearchRecord, SourceType
from update_review.contracts import (
    EvidencePeriod,
    Sentiment,
    UpdateBrief,
    UpdateEvidenceItem,
    UpdateFeedbackBundle,
    UpdateType,
    WeaponBalanceDetails,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FILES = {"dragunov_random_damage_removal": "dragunov_random_damage_removal.jsonl"}
OFFICIAL_URL = "https://pubg.com/en/news/6616"


def load_dragunov_brief(run_id: str) -> UpdateBrief:
    return UpdateBrief(
        run_id=run_id,
        status=ArtifactStatus.COMPLETE,
        producer=Producer.USER,
        input_refs=[],
        game="PUBG: BATTLEGROUNDS",
        update_name="Dragunov 확률 피해 제거",
        update_type=UpdateType.WEAPON_BALANCE,
        current_state="기본 피해 58, 최대 피해 73의 확률형 구조",
        change_summary="확률형 피해를 제거하고 피해를 60으로 고정",
        goal="운에 따른 결과 편차를 줄이고 전투 결과 예측 가능성을 높인다.",
        expected_benefits=["피해 결과 예측 가능성", "실력 중심 전투와의 정합성", "공정성 인식 개선"],
        concerns=["반동·연사력을 포함한 실제 성능", "사용률 급등 또는 하락", "코어 전투 이용자의 메타 반응"],
        scope="일반 매칭의 Dragunov 사용 경험",
        planned_at=datetime(2026, 8, 20, tzinfo=UTC),
        cutoff_at=datetime(2026, 8, 13, tzinfo=UTC),
        official_context="PUBG Update 25.2에서 이용자 피드백을 바탕으로 확률형 피해를 제거했다는 공식 변경 맥락",
        official_context_url=OFFICIAL_URL,
        details=WeaponBalanceDetails(
            target_weapon="Dragunov",
            damage="기본 58·최대 73 확률 → 60 고정",
            recoil="현행 반동 유지, 실제 조합 확인 필요",
            rate_of_fire="해당 없음",
            ammunition="7.62mm",
            spawn_and_modes="일반 매칭",
        ),
    )


def load_update_feedback_fixture(
    brief: UpdateBrief,
    case: str = "dragunov_random_damage_removal",
) -> UpdateFeedbackBundle:
    try:
        path = ROOT / "fixtures" / FIXTURE_FILES[case]
    except KeyError as exc:
        raise ValueError(f"unknown update fixture case: {case}") from exc
    evidence: list[UpdateEvidenceItem] = []
    samples: list[LanguageSample] = []
    search_log: list[SearchRecord] = []
    for row_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        row = json.loads(line)
        language = Language(row["language"])
        samples.append(LanguageSample(language=language, general_count=row["general_count"], mechanism_count=row["mechanism_count"]))
        for index in range(row["mechanism_count"]):
            template = row["templates"][index % len(row["templates"])]
            suffix = f"{language.value.replace('-', '').lower()}-{index + 1:03d}"
            evidence.append(
                UpdateEvidenceItem(
                    evidence_id=f"fx-dragunov-{suffix}",
                    source=SourceType.SYNTHETIC,
                    source_url=OFFICIAL_URL,
                    source_id=f"synthetic-dragunov-{suffix}",
                    language=language,
                    observed_at=brief.cutoff_at - timedelta(days=(row_index * 15) + index + 1),
                    period=EvidencePeriod.COMPARABLE_REFERENCE,
                    sentiment=Sentiment(template["sentiment"]),
                    summary=template["text"],
                    mechanism_tags=[template["tag"]],
                    relevance=0.9,
                    synthetic=True,
                )
            )
        search_log.append(
            SearchRecord(
                source=SourceType.SYNTHETIC,
                language=language,
                query=f"{brief.update_name} synthetic comparable reference",
                requested_at=brief.cutoff_at - timedelta(days=1),
                result_count=row["mechanism_count"],
            )
        )
    return UpdateFeedbackBundle(
        run_id=brief.run_id,
        producer=Producer.COLLECTOR,
        input_refs=[brief.ref],
        input_mode=InputMode.FIXTURE,
        cutoff_at=brief.cutoff_at,
        search_log=search_log,
        samples=samples,
        evidence=evidence,
    )
```

- [ ] **Step 5: 기본 저장 경로의 수집 에이전트를 구현한다**

`update_review/collector.py`에 확장 가능한 옵션 계약과 기본 fixture 실행을 작성한다. 이 Task의 `run`은 `use_fixture=True`인 저장 경로만 받고, 외부 소스 분기는 Task 5에서 같은 메서드에 추가한다.

```python
from __future__ import annotations

from collections.abc import Callable
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from contracts import InputMode
from update_review.contracts import UpdateBrief, UpdateFeedbackBundle
from update_review.fixtures import load_update_feedback_fixture


NodeCallback = Callable[[str, str, dict], None]


@dataclass(slots=True)
class UpdateCollectionOptions:
    use_fixture: bool = True
    fixture_case: str = "dragunov_random_damage_removal"
    imported_csv: bytes | None = None
    steam_app_id: int | None = None
    use_x: bool = False
    x_query: str = "PUBG Dragunov damage"
    period_start: datetime | None = None
    period_end: datetime | None = None
    x_estimated_total_cost_usd: float = 0.0

    @property
    def input_mode(self) -> InputMode:
        if self.use_fixture:
            return InputMode.FIXTURE
        if self.steam_app_id or self.use_x:
            return InputMode.LIVE
        return InputMode.IMPORT


class UpdateCollectorAgent:
    def run(
        self,
        brief: UpdateBrief,
        options: UpdateCollectionOptions,
        on_event: NodeCallback | None = None,
    ) -> UpdateFeedbackBundle:
        if not options.use_fixture:
            raise ValueError("fixture source is required until an external update source is selected")
        notify = on_event or (lambda _node, _message, _metrics: None)
        result = load_update_feedback_fixture(brief, options.fixture_case)
        notify("source_selected", "출시 전 예상을 위한 저장 비교 자료를 선택했습니다.", {"input_mode": options.input_mode.value})
        notify("period_checked", "모든 자료를 실제 사후 반응이 아닌 비교 참고로 구분했습니다.", {"comparable_reference": len(result.evidence)})
        notify("anonymized", "원문과 사용자 식별자 없이 합성 요약만 불러왔습니다.", {"evidence": len(result.evidence)})
        notify("samples_counted", "언어권별 관련 표본을 집계했습니다.", {"insufficient": sum(not item.sufficient for item in result.samples)})
        notify("bundle_ready", "UpdateFeedbackBundle 계약 검증을 통과했습니다.", {"evidence": len(result.evidence)})
        return result
```

- [ ] **Step 6: 저장 사례와 노드 이벤트가 통과하는지 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py -v`

Expected: PASS for the two tests above.

- [ ] **Step 7: Task 2를 커밋한다**

```bash
git add fixtures/dragunov_random_damage_removal.jsonl update_review/fixtures.py update_review/collector.py tests/test_update_pipeline.py
git commit -m "feat: add Dragunov update review fixture"
```

---

### Task 3: 결정론적 4에이전트 업데이트 파이프라인

**Files:**
- Create: `update_review/evidence.py`
- Create: `update_review/redteam.py`
- Create: `update_review/audit.py`
- Create: `update_review/orchestrator.py`
- Modify: `update_review/__init__.py`
- Modify: `tests/test_update_pipeline.py`

**Interfaces:**
- Consumes: `UpdateCollectorAgent.run(...) -> UpdateFeedbackBundle`
- Produces: `UpdateEvidenceAgent.run_deterministic(bundle, on_event=None) -> UpdateEvidencePack`
- Produces: `UpdateRedteamAgent.run_deterministic(brief, pack, on_event=None) -> UpdateImpactAssessment`
- Produces: `UpdateAuditAgent.run_deterministic(bundle, pack, assessment, *, analysis_incomplete=False, on_event=None) -> UpdateValidatedDecision`
- Produces: `UpdateAuditAgent.to_brief(brief, pack, decision) -> UpdateDecisionBrief`
- Produces: `UpdateReviewOrchestrator.run(brief, options=None, *, on_event=None, log_path=None) -> UpdatePipelineResult`

- [ ] **Step 1: 파이프라인 산출물·재현성·노드 순서 실패 테스트를 추가한다**

`tests/test_update_pipeline.py`에 다음을 추가한다.

```python
from update_review.contracts import UpdateDecision
from update_review.orchestrator import UpdateReviewOrchestrator


EXPECTED_AGENTS = [
    "collection",
    "evidence_rag_personas",
    "event_redteam",
    "audit_strategy",
]


def test_dragunov_pipeline_is_reproducible_and_requires_test():
    first = UpdateReviewOrchestrator().run(load_dragunov_brief("stable-run"))
    second = UpdateReviewOrchestrator().run(load_dragunov_brief("stable-run"))
    assert first.brief == second.brief
    assert first.brief.decision is UpdateDecision.TEST
    assert first.feedback.ref in first.evidence.input_refs
    assert first.evidence.ref in first.impact.input_refs
    assert first.impact.ref in first.validated.input_refs
    assert {item.sentiment.value for item in first.evidence.positive_signals} == {"positive"}
    assert {item.sentiment.value for item in first.evidence.negative_signals} == {"negative"}
    assert all(metric.addresses_risk_ids for metric in first.brief.validation_metrics)
    assert not any(item.period.value == "after" for item in first.brief.evidence)


def test_pipeline_exposes_all_agents_and_internal_node_results():
    result = UpdateReviewOrchestrator().run(load_dragunov_brief("event-run"))
    completed_agents = [
        item.agent
        for item in result.events
        if item.node == "agent" and item.state.value == "complete"
    ]
    assert completed_agents == EXPECTED_AGENTS
    nodes = {item.node for item in result.events}
    assert {
        "source_selected",
        "signals_grouped",
        "personas_linked",
        "change_reviewed",
        "failure_paths_built",
        "metrics_linked",
        "risks_validated",
        "decision_fixed",
        "recommendations_built",
    } <= nodes
    assert all(item.message for item in result.events)


def test_update_contract_violation_stops_the_pipeline():
    class WrongCollector:
        def run(self, brief, options, on_event=None):
            return load_update_feedback_fixture(brief).model_copy(update={"run_id": "changed"})

    with pytest.raises(Exception, match="run_id changed"):
        UpdateReviewOrchestrator(collector=WrongCollector()).run(load_dragunov_brief("expected"))
```

- [ ] **Step 2: 파이프라인 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'update_review.orchestrator'`.

- [ ] **Step 3: 변경 영향 분석 에이전트의 고정 신호·페르소나 규칙을 구현한다**

`update_review/evidence.py`에 근거 태그와 감정으로만 신호를 만드는 고정 규칙을 둔다. 유형에 관계없이 사용할 수 있는 태그만 폐쇄 매핑에 둔다.

```python
from collections import Counter
from collections.abc import Callable

from contracts import ArtifactStatus, Language, PersonaKind, Producer
from update_review.contracts import (
    ReactionSignal,
    Sentiment,
    SplitCondition,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateLanguageInsight,
    UpdatePersonaImpact,
)


SIGNAL_TITLES = {
    "predictability": "결과 예측 가능성 상승",
    "skill_fairness": "실력 중심 공정성 인식",
    "balance_regression": "실제 성능 역전 가능성",
    "validation_needed": "실제 지표 확인 필요",
    "information_clarity": "변경 정보 이해 가능성",
    "flow_disruption": "이용 동선 변화 부담",
    "rule_exception": "예외 규칙 처리 부담",
    "learning_burden": "새 규칙 학습 부담",
}

PERSONA_TAGS = {
    PersonaKind.TIME_CONSTRAINED: {"information_clarity", "flow_disruption", "learning_burden"},
    PersonaKind.VALUE_SEEKING: {"predictability", "skill_fairness", "rule_exception"},
    PersonaKind.COLLECTOR: {"information_clarity", "rule_exception", "learning_burden"},
    PersonaKind.CORE_GAMEPLAY: {"predictability", "skill_fairness", "balance_regression", "validation_needed"},
}


class UpdateEvidenceAgent:
    def run_deterministic(
        self,
        bundle: UpdateFeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateEvidencePack:
        notify = on_event or (lambda _node, _message, _metrics: None)
        deduplicated = list({(item.source, item.source_id): item for item in bundle.evidence}.values())
        notify("deduplicated", "중복 비식별 근거를 하나로 합쳤습니다.", {"evidence": len(deduplicated)})

        def signals(sentiment: Sentiment) -> list[ReactionSignal]:
            rows = []
            for tag, title in SIGNAL_TITLES.items():
                items = [item for item in deduplicated if item.sentiment is sentiment and tag in item.mechanism_tags]
                if items:
                    rows.append(ReactionSignal(
                        signal_id=f"{sentiment.value}-{tag}",
                        title=title,
                        summary=f"{len(items)}개 비식별 근거에서 {title} 반응이 나타날 가능성이 있음.",
                        sentiment=sentiment,
                        evidence_ids=[item.evidence_id for item in items],
                        confidence=sum(item.relevance for item in items) / len(items),
                    ))
            return rows

        positive = signals(Sentiment.POSITIVE)
        negative = signals(Sentiment.NEGATIVE)
        mixed = [
            SplitCondition(**item.model_dump())
            for item in signals(Sentiment.MIXED)
        ]
        notify("signals_grouped", "긍정·부정·혼합 반응 신호를 변경 요소별로 묶었습니다.", {"positive": len(positive), "negative": len(negative), "mixed": len(mixed)})
        signal_ids = {item.signal_id for item in [*positive, *negative, *mixed]}
        personas = []
        for persona, tags in PERSONA_TAGS.items():
            items = [item for item in deduplicated if tags.intersection(item.mechanism_tags)]
            if not items:
                continue
            positive_ids = [item.signal_id for item in positive if item.signal_id.split("-", 1)[1] in tags]
            negative_ids = [item.signal_id for item in negative if item.signal_id.split("-", 1)[1] in tags]
            personas.append(UpdatePersonaImpact(
                persona=persona,
                expected_reaction="연결된 긍정·부정 신호에 따라 반응이 갈릴 가능성이 있음.",
                positive_signal_ids=[value for value in positive_ids if value in signal_ids],
                negative_signal_ids=[value for value in negative_ids if value in signal_ids],
                split_signal_ids=[item.signal_id for item in mixed if item.signal_id.split("-", 1)[1] in tags],
                evidence_ids=[item.evidence_id for item in items[:15]],
                confidence=sum(item.relevance for item in items[:15]) / len(items[:15]),
            ))
        notify("personas_linked", "이용자 유형별로 다르게 나타날 신호와 근거를 연결했습니다.", {"personas": len(personas)})
        samples = {item.language: item for item in bundle.samples}
        language_insights = []
        for language in Language:
            items = [item for item in deduplicated if item.language is language]
            sample = samples.get(language)
            counts = Counter(item.sentiment for item in items)
            sufficient = bool(sample and sample.sufficient)
            language_insights.append(UpdateLanguageInsight(
                language=language,
                conclusion="언어권별 긍정·부정·혼합 반응이 갈릴 가능성이 있음." if sufficient else None,
                hidden_reason=None if sufficient else "일반 100건·관련 15건 최소 표본 미달",
                sentiment_counts={sentiment: counts[sentiment] for sentiment in Sentiment},
                evidence_ids=[item.evidence_id for item in items],
                confidence=sum(item.relevance for item in items) / len(items) if sufficient and items else 0,
            ))
        notify("language_gate_checked", "최소 표본을 충족한 언어권만 반응 비율을 공개합니다.", {"visible": sum(item.conclusion is not None for item in language_insights)})
        result = UpdateEvidencePack(
            run_id=bundle.run_id,
            status=ArtifactStatus.PARTIAL if bundle.errors else ArtifactStatus.COMPLETE,
            producer=Producer.EVIDENCE_RAG,
            input_refs=[bundle.ref],
            errors=list(bundle.errors),
            positive_signals=positive,
            negative_signals=negative,
            split_conditions=mixed,
            persona_impacts=personas,
            language_insights=language_insights,
            evidence=deduplicated,
        )
        notify("pack_ready", "UpdateEvidencePack 계약 검증을 통과했습니다.", {"signals": len(positive) + len(negative) + len(mixed)})
        return result
```

- [ ] **Step 4: 업데이트 레드팀의 폐쇄형 위험·검증 지표를 구현한다**

`update_review/redteam.py`에 아래 매핑을 두고, negative/mixed 신호 태그에서만 위험을 연다. Dragunov의 `balance_regression`은 `Medium`이고 테스트 지표가 필요하므로 Task 1 정책에서 `Test`가 된다.

```python
from collections.abc import Callable

from contracts import ArtifactStatus, PersonaKind, Producer
from update_review.contracts import (
    ExpectedImpact,
    Sentiment,
    UpdateBrief,
    UpdateEvidencePack,
    UpdateImpactAssessment,
    UpdateRiskCategory,
    UpdateRiskItem,
    ValidationMetric,
)
from update_review.policy import expected_severity


RISK_BY_TAG = {
    "balance_regression": UpdateRiskCategory.BALANCE_REGRESSION,
    "fairness_regression": UpdateRiskCategory.FAIRNESS_REGRESSION,
    "information_clarity": UpdateRiskCategory.INFORMATION_CLARITY,
    "flow_disruption": UpdateRiskCategory.FLOW_DISRUPTION,
    "rule_exception": UpdateRiskCategory.RULE_EXCEPTION,
    "learning_burden": UpdateRiskCategory.LEARNING_BURDEN,
}

RISK_COPY = {
    UpdateRiskCategory.BALANCE_REGRESSION: ("실제 전투 성능 역전", "고정 피해와 반동·연사력의 조합으로 사용률이 쏠릴 가능성이 있음.", "테스트 서버에서 사용률·승률·평균 피해를 확인할 수 있는가?"),
    UpdateRiskCategory.FAIRNESS_REGRESSION: ("공정성 인식 역전", "변경 결과가 특정 이용자에게만 유리하게 체감될 가능성이 있음.", "숙련도별 성과 편차를 비교할 수 있는가?"),
    UpdateRiskCategory.INFORMATION_CLARITY: ("변경 정보 이해 부족", "변경 전·후 차이를 알지 못해 잘못된 행동을 할 가능성이 있음.", "한 화면에서 변경 전·후를 설명할 수 있는가?"),
    UpdateRiskCategory.FLOW_DISRUPTION: ("사용 동선 분절", "새 화면과 절차가 작업 흐름을 끊을 가능성이 있음.", "핵심 작업을 기존 단계 안에서 끝낼 수 있는가?"),
    UpdateRiskCategory.RULE_EXCEPTION: ("예외 규칙 누락", "기존 이용자와 경계 상황에서 다른 결과가 나올 가능성이 있음.", "경계값·기존 상태·예외 사용자를 모두 테스트했는가?"),
    UpdateRiskCategory.LEARNING_BURDEN: ("새 규칙 학습 부담", "기존 습관을 다시 배워야 해 이탈할 가능성이 있음.", "첫 사용에서 별도 설명 없이 완료할 수 있는가?"),
}


class UpdateRedteamAgent:
    def run_deterministic(self, brief: UpdateBrief, pack: UpdateEvidencePack, on_event: Callable[[str, str, dict], None] | None = None) -> UpdateImpactAssessment:
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify("change_reviewed", "현재 상태와 변경안의 차이를 확인했습니다.", {"update_type": brief.update_type.value})
        positives = [ExpectedImpact(impact_id=f"impact-{item.signal_id}", title=item.title, summary=item.summary, affected_personas=[impact.persona for impact in pack.persona_impacts if item.signal_id in impact.positive_signal_ids] or [PersonaKind.CORE_GAMEPLAY], evidence_ids=item.evidence_ids, confidence=item.confidence) for item in pack.positive_signals]
        negatives = [ExpectedImpact(impact_id=f"impact-{item.signal_id}", title=item.title, summary=item.summary, affected_personas=[impact.persona for impact in pack.persona_impacts if item.signal_id in impact.negative_signal_ids] or [PersonaKind.CORE_GAMEPLAY], evidence_ids=item.evidence_ids, confidence=item.confidence) for item in pack.negative_signals]
        risks = []
        for item in [*pack.negative_signals, *pack.split_conditions]:
            tag = item.signal_id.split("-", 1)[1]
            category = RISK_BY_TAG.get(tag)
            if category is None:
                continue
            title, failure_path, question = RISK_COPY[category]
            risks.append(UpdateRiskItem(risk_id=f"risk-{category.value}", category=category, title=title, severity=expected_severity(category), affected_personas=[impact.persona for impact in pack.persona_impacts if item.signal_id in impact.positive_signal_ids + impact.negative_signal_ids + impact.split_signal_ids] or [PersonaKind.CORE_GAMEPLAY], evidence_ids=item.evidence_ids, failure_path=failure_path, revision_question=question, confidence=item.confidence))
        notify("failure_paths_built", "부정·혼합 신호에서 실패 경로를 만들었습니다.", {"risks": len(risks)})
        metrics = [ValidationMetric(metric_id=f"metric-{risk.category.value}", title=f"{risk.title} 확인 지표", measurement="업데이트 직접 언급 의견의 감정 비율과 관련 행동 지표를 비교", success_condition="부정 반응이 사전 경계값을 넘지 않고 행동 지표의 악화가 없음", addresses_risk_ids=[risk.risk_id]) for risk in risks]
        notify("metrics_linked", "각 위험에 출시 후 확인 지표를 연결했습니다.", {"metrics": len(metrics)})
        result = UpdateImpactAssessment(run_id=brief.run_id, status=ArtifactStatus.PARTIAL if pack.errors else ArtifactStatus.COMPLETE, producer=Producer.EVENT_REDTEAM, input_refs=[brief.ref, pack.ref], errors=list(pack.errors), expected_positive=positives, expected_negative=negatives, risks=risks, validation_metrics=metrics)
        notify("assessment_ready", "UpdateImpactAssessment 계약 검증을 통과했습니다.", {"risks": len(risks)})
        return result
```

- [ ] **Step 5: 검증·전략 에이전트와 최종 brief 조립을 구현한다**

`update_review/audit.py`에서 실재 근거 ID, 폐쇄 위험 등급, 0.5 신뢰도, 지표 연결을 검증한다. 정책 통과 위험만 `decide_update`에 넘긴다.

```python
from collections.abc import Callable

from contracts import ArtifactStatus, Producer, Severity
from update_review.contracts import (
    RejectedUpdateRisk,
    UpdateBrief,
    UpdateDecision,
    UpdateDecisionBrief,
    UpdateEvidencePack,
    UpdateFeedbackBundle,
    UpdateImpactAssessment,
    UpdateRecommendation,
    UpdateValidatedDecision,
)
from update_review.policy import MIN_RISK_CONFIDENCE, UPDATE_RISK_TAGS, decide_update, expected_severity


class UpdateAuditAgent:
    def run_deterministic(self, bundle: UpdateFeedbackBundle, pack: UpdateEvidencePack, assessment: UpdateImpactAssessment, *, analysis_incomplete: bool = False, on_event: Callable[[str, str, dict], None] | None = None) -> UpdateValidatedDecision:
        notify = on_event or (lambda _node, _message, _metrics: None)
        evidence_ids = {item.evidence_id for item in pack.evidence}
        validated = []
        rejected = []
        for risk in assessment.risks:
            linked = [item for item in pack.evidence if item.evidence_id in risk.evidence_ids]
            if len(linked) != len(risk.evidence_ids):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="실재 근거 ID와 연결되지 않음"))
            elif any(UPDATE_RISK_TAGS[risk.category] not in item.mechanism_tags for item in linked):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="위험 범주와 연결 근거 태그가 다름"))
            elif risk.severity != expected_severity(risk.category):
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="정책 위험 등급과 다름"))
            elif risk.confidence < MIN_RISK_CONFIDENCE:
                rejected.append(RejectedUpdateRisk(risk_id=risk.risk_id, reason="근거 신뢰도 0.5 미만"))
            else:
                validated.append(risk)
        notify("risks_validated", "근거 ID·정책 등급·신뢰도로 위험을 검증했습니다.", {"validated": len(validated), "rejected": len(rejected)})
        metrics = [item for item in assessment.validation_metrics if set(item.addresses_risk_ids) <= {risk.risk_id for risk in validated}]
        metrics_complete = all(any(risk.risk_id in item.addresses_risk_ids for item in metrics) for risk in validated)
        decision, reason = decide_update(bundle.samples, validated, metrics_complete=metrics_complete, analysis_incomplete=analysis_incomplete)
        notify("sample_gate_applied", "언어권 표본과 검증 지표 충족 여부를 판정에 적용했습니다.", {"metrics_complete": metrics_complete})
        notify("decision_fixed", "코드 정책으로 출시 판정을 고정했습니다.", {"decision": decision.value})
        recommendations = [UpdateRecommendation(priority=index, title=f"{risk.title} 사전 테스트", action=risk.revision_question, addresses_risk_ids=[risk.risk_id], validation_metric_ids=[item.metric_id for item in metrics if risk.risk_id in item.addresses_risk_ids]) for index, risk in enumerate(validated, start=1)]
        notify("recommendations_built", "위험과 검증 지표를 연결한 실행 권고를 만들었습니다.", {"recommendations": len(recommendations)})
        return UpdateValidatedDecision(run_id=assessment.run_id, status=ArtifactStatus.PARTIAL if assessment.errors else ArtifactStatus.COMPLETE, producer=Producer.AUDIT_STRATEGY, input_refs=[bundle.ref, pack.ref, assessment.ref], errors=list(assessment.errors), decision=decision, decision_reason=reason, validated_risks=validated, rejected_risks=rejected, recommendations=recommendations, validation_metrics=metrics)

    def to_brief(self, brief: UpdateBrief, pack: UpdateEvidencePack, impact: UpdateImpactAssessment, decision: UpdateValidatedDecision) -> UpdateDecisionBrief:
        rank = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}
        top_risks = sorted(decision.validated_risks, key=lambda item: (rank[item.severity], item.confidence), reverse=True)
        label = {UpdateDecision.GO: "출시 가능", UpdateDecision.REVISE: "일부 수정 후 출시", UpdateDecision.TEST: "테스트 후 출시", UpdateDecision.HOLD: "판정 보류"}[decision.decision]
        return UpdateDecisionBrief(run_id=brief.run_id, status=decision.status, producer=Producer.ORCHESTRATOR, input_refs=[brief.ref, pack.ref, impact.ref, decision.ref], errors=list(decision.errors), decision=decision.decision, executive_summary=f"{brief.update_name}: {label}. {decision.decision_reason}", official_context=brief.official_context, official_context_url=brief.official_context_url, expected_positive=impact.expected_positive, expected_negative=impact.expected_negative, split_conditions=pack.split_conditions, persona_impacts=pack.persona_impacts, language_insights=pack.language_insights, top_risks=top_risks, validation_metrics=decision.validation_metrics, evidence=pack.evidence, recommendations=decision.recommendations)
```

- [ ] **Step 6: 업데이트 오케스트레이터와 스냅샷 해시를 구현한다**

`update_review/orchestrator.py`는 기존 `ExecutionEvent`와 `Producer`를 재사용하되 이벤트 orchestrator를 수정하지 않는다. 이 Task에서는 결정론적 실행만 구현하고, Claude 재시도·fallback은 Task 4에서 같은 class에 추가한다.

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from contracts import Artifact, ArtifactStatus, Producer
from execution import EventCallback, ExecutionEvent, ExecutionState
from orchestrator import ContractViolation, PipelineStopped
from update_review.audit import UpdateAuditAgent
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent
from update_review.contracts import UpdateBrief, UpdateDecisionBrief, UpdateEvidencePack, UpdateFeedbackBundle, UpdateImpactAssessment, UpdateValidatedDecision
from update_review.evidence import UpdateEvidenceAgent
from update_review.redteam import UpdateRedteamAgent


@dataclass(slots=True)
class UpdatePipelineResult:
    feedback: UpdateFeedbackBundle
    evidence: UpdateEvidencePack
    impact: UpdateImpactAssessment
    validated: UpdateValidatedDecision
    brief: UpdateDecisionBrief
    events: list[ExecutionEvent]
    fallback_used: bool = False
    analysis_incomplete: bool = False
    llm_provider: str = "deterministic"
    llm_requested: bool = False


class UpdateReviewOrchestrator:
    def __init__(self, *, collector=None, evidence=None, redteam=None, audit=None, use_llm: bool = False, llm_client=None) -> None:
        self.collector = collector or UpdateCollectorAgent()
        self.evidence_agent = evidence or UpdateEvidenceAgent()
        self.redteam = redteam or UpdateRedteamAgent()
        self.audit = audit or UpdateAuditAgent()
        self.use_llm = use_llm
        self.llm_client = llm_client

    def run(self, brief: UpdateBrief, options: UpdateCollectionOptions | None = None, *, on_event: EventCallback | None = None, log_path: Path | None = None) -> UpdatePipelineResult:
        if brief.producer != Producer.USER:
            raise PipelineStopped("UpdateBrief producer must be user")
        options = options or UpdateCollectionOptions()
        events: list[ExecutionEvent] = []

        def emit(agent, node, state, message, metrics=None):
            item = ExecutionEvent(sequence=len(events), agent=agent, node=node, state=state, message=message, metrics=metrics or {})
            events.append(item)
            if on_event:
                on_event(item)
            self._write(item, log_path)

        def nodes(agent):
            return lambda node, message, metrics: emit(agent, node, ExecutionState.RUNNING, message, metrics)

        def stage(agent, call, output_type, producer, refs):
            emit(agent, "agent", ExecutionState.RUNNING, "업데이트 점검 단계를 시작했습니다.")
            result = self._check(call(), output_type, producer, brief.run_id, refs)
            if result.status == ArtifactStatus.FAILED:
                raise PipelineStopped(f"{agent} returned failed status")
            emit(agent, "agent", ExecutionState.COMPLETE, "업데이트 점검 단계를 완료했습니다.")
            self._write(result, log_path)
            return result

        feedback = stage("collection", lambda: self.collector.run(brief, options, nodes("collection")), UpdateFeedbackBundle, Producer.COLLECTOR, {brief.ref})
        metadata = {"input_snapshot_hash": _input_snapshot_hash(brief, feedback)}
        feedback = feedback.model_copy(update=metadata)
        evidence = stage("evidence_rag_personas", lambda: self.evidence_agent.run_deterministic(feedback, nodes("evidence_rag_personas")).model_copy(update=metadata), UpdateEvidencePack, Producer.EVIDENCE_RAG, {feedback.ref})
        impact = stage("event_redteam", lambda: self.redteam.run_deterministic(brief, evidence, nodes("event_redteam")).model_copy(update=metadata), UpdateImpactAssessment, Producer.EVENT_REDTEAM, {brief.ref, evidence.ref})
        validated = stage("audit_strategy", lambda: self.audit.run_deterministic(feedback, evidence, impact, on_event=nodes("audit_strategy")).model_copy(update=metadata), UpdateValidatedDecision, Producer.AUDIT_STRATEGY, {feedback.ref, evidence.ref, impact.ref})
        final = self.audit.to_brief(brief, evidence, impact, validated).model_copy(update=metadata)
        final = self._check(final, UpdateDecisionBrief, Producer.ORCHESTRATOR, brief.run_id, {brief.ref, evidence.ref, impact.ref, validated.ref})
        self._write(final, log_path)
        return UpdatePipelineResult(feedback, evidence, impact, validated, final, events)

    @staticmethod
    def _check(result: Artifact, output_type, producer: Producer, run_id: str, refs: set[str]):
        checked = output_type.model_validate(result.model_dump(mode="python"))
        if checked.run_id != run_id:
            raise ContractViolation("run_id changed between stages")
        if checked.producer != producer:
            raise ContractViolation(f"expected producer {producer.value}, got {checked.producer.value}")
        if not refs <= set(checked.input_refs):
            raise ContractViolation("required input_refs are missing")
        return checked

    @staticmethod
    def _write(value: Artifact | ExecutionEvent, log_path: Path | None) -> None:
        if log_path is None:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _input_snapshot_hash(brief: UpdateBrief, feedback: UpdateFeedbackBundle) -> str:
    payload = {
        "brief": brief.model_dump(mode="json", exclude={"run_id", "producer", "input_refs", "status", "errors", "input_snapshot_hash"}),
        "input_mode": feedback.input_mode.value,
        "samples": sorted((item.language.value, item.general_count, item.mechanism_count) for item in feedback.samples),
        "evidence": sorted((item.evidence_id, item.source_id, item.period.value, item.sentiment.value, item.summary, sorted(item.mechanism_tags)) for item in feedback.evidence),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
```

`update_review/__init__.py`에 `UpdatePipelineResult`, `UpdateReviewOrchestrator`를 export한다.

- [ ] **Step 7: 결정론적 파이프라인 테스트와 기존 오케스트레이터 회귀를 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py tests/test_orchestrator.py -v`

Expected: PASS.

- [ ] **Step 8: Task 3을 커밋한다**

```bash
git add update_review/__init__.py update_review/evidence.py update_review/redteam.py update_review/audit.py update_review/orchestrator.py tests/test_update_pipeline.py
git commit -m "feat: add deterministic update review pipeline"
```

---

### Task 4: Claude 한국어 자연어 보강과 통제된 결정론 fallback

**Files:**
- Create: `update_review/prompts/evidence.md`
- Create: `update_review/prompts/redteam.md`
- Create: `update_review/prompts/audit.md`
- Modify: `update_review/evidence.py`
- Modify: `update_review/redteam.py`
- Modify: `update_review/audit.py`
- Modify: `update_review/orchestrator.py`
- Modify: `agents/structured.py`
- Create: `update_review/prompts/collector.md`
- Modify: `backend/.env.example`
- Modify: `tests/test_update_pipeline.py`
- Modify: `tests/test_structured_api.py`

**Interfaces:**
- Consumes: `parse_claude_structured(...)`, `ClaudeBudget`, `StructuredModelError`, `require_korean_text`
- Produces: `UpdateEvidenceAgent.run(...)`, `UpdateRedteamAgent.run(...)`, `UpdateAuditAgent.run(...)`; 각 `run_deterministic(...)`은 그대로 보존
- Preserves: `UpdateValidatedDecision.decision`, risk IDs, evidence IDs, validation metric IDs

- [ ] **Step 1: Claude가 판정·ID를 바꾸지 못하고 재시도 후 fallback하는 실패 테스트를 추가한다**

`tests/test_update_pipeline.py`에 실제 SDK를 호출하지 않는 fake Claude client를 추가한다. fake response는 `messages.create` 호출 순서대로 세 번의 tool input을 반환한다.

```python
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from connectors import RawFeedback
from contracts import Language, SourceType


class FakeClaudeMessages:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=payload)])


class FakeClaude:
    def __init__(self, payloads):
        self.messages = FakeClaudeMessages(payloads)


def test_claude_changes_only_korean_narrative_not_core_decision():
    baseline = UpdateReviewOrchestrator().run(load_dragunov_brief("claude-run"))
    risk = baseline.impact.risks[0]
    metric = baseline.impact.validation_metrics[0]
    positive = baseline.evidence.positive_signals[0]
    fake = FakeClaude([
        {"signals": [{"signal_id": positive.signal_id, "title": "예측 가능성 개선 예상", "summary": "고정 피해로 결과 예측 가능성이 높아질 가능성이 있음.", "evidence_ids": positive.evidence_ids}]},
        {"risks": [{"risk_id": risk.risk_id, "title": "전투 성능 재확인 필요", "failure_path": "실제 특성 조합에서 메타가 쏠릴 가능성이 있음.", "revision_question": "테스트 서버 지표를 확인할 수 있는가?", "evidence_ids": risk.evidence_ids, "validation_metric_ids": [metric.metric_id]}]},
        {"executive_summary": "결과 예측 가능성은 개선될 수 있으나 전투 지표는 테스트로 확인 필요.", "recommendations": [{"risk_id": risk.risk_id, "title": "테스트 서버 확인", "action": "사용률·승률·평균 피해를 확인한다.", "validation_metric_ids": [metric.metric_id]}]},
    ])
    result = UpdateReviewOrchestrator(use_llm=True, llm_client=fake).run(load_dragunov_brief("claude-run"))
    assert result.brief.decision == baseline.brief.decision == UpdateDecision.TEST
    assert [item.risk_id for item in result.brief.top_risks] == [item.risk_id for item in baseline.brief.top_risks]
    assert [item.evidence_ids for item in result.brief.top_risks] == [item.evidence_ids for item in baseline.brief.top_risks]
    assert result.llm_provider == "claude"
    assert result.llm_requested is True
    assert result.fallback_used is False
    assert [call["model"] for call in fake.messages.calls] == ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-haiku-4-5"]


def test_invalid_claude_reference_retries_then_uses_fixture_safe_path():
    invalid = {"signals": [{"signal_id": "unknown", "title": "한국어 제목", "summary": "한국어 설명을 제공함.", "evidence_ids": ["missing"]}]}
    fake = FakeClaude([invalid, invalid])
    result = UpdateReviewOrchestrator(use_llm=True, llm_client=fake).run(load_dragunov_brief("fallback-run"))
    assert result.brief.decision is UpdateDecision.TEST
    assert result.fallback_used is True
    assert result.analysis_incomplete is False
    assert len(fake.messages.calls) == 2
    assert any(item.state.value == "retrying" for item in result.events)


def test_fixture_without_claude_key_uses_deterministic_path(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = UpdateReviewOrchestrator(use_llm=True).run(load_dragunov_brief("no-key-run"))
    assert result.brief.decision is UpdateDecision.TEST
    assert result.fallback_used is True
    assert result.analysis_incomplete is False


def test_live_classifier_returns_only_sanitized_structured_evidence():
    raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="anonymous-source-001",
        language=Language.KOREAN,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text="원문에는 사용자가 작성한 상세 반응이 있다.",
    )
    fake = FakeClaude([{
        "items": [{
            "source_id": raw.source_id,
            "sentiment": "negative",
            "summary": "고정 피해의 실제 성능은 테스트로 확인 필요.",
            "mechanism_tags": ["balance_regression"],
            "relevance": 0.9,
        }]
    }])
    output = UpdateCollectorAgent(use_llm=True, client=fake).classify_raw([raw], load_dragunov_brief("live-classify"))
    assert output[0].source_id == raw.source_id
    assert output[0].summary != raw.text
    assert "text" not in output[0].model_dump()
    assert json.dumps(output[0].model_dump(mode="json"), ensure_ascii=False).find(raw.text) == -1
```

`tests/test_structured_api.py`에는 Claude가 tool block을 반환하지 않을 때 공용 parser가 명시적인 거절 오류로 정규화하는 회귀 테스트도 추가한다.

```python
def test_claude_missing_tool_output_becomes_refusal(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return TinyOutput", encoding="utf-8")

    class Messages:
        def create(self, **_kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="cannot comply")])

    with pytest.raises(StructuredModelError) as error:
        parse_claude_structured(
            model="claude-haiku-4-5",
            prompt_path=prompt,
            output_type=TinyOutput,
            payload={"input": "fixture"},
            client=SimpleNamespace(messages=Messages()),
            budget=ClaudeBudget(max_requests=1),
        )
    assert error.value.code is ErrorCode.LLM_REFUSAL
```

- [ ] **Step 2: Claude 병합 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py -k claude -v`

Expected: FAIL because the update agents do not have LLM `run(...)` paths yet.

- [ ] **Step 2A: 공용 Claude parser의 도달 불가능한 거절 처리를 바로잡는다**

`agents/structured.py::parse_claude_structured`의 `for` loop 뒤에 거절 오류를 두고, 현재 `return` 뒤의 도달 불가능한 줄을 제거한다. 유효한 tool block은 기존처럼 즉시 반환한다.

```python
        for block in response.content:
            block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if block_type != "tool_use":
                continue
            value = block.get("input") if isinstance(block, dict) else getattr(block, "input", None)
            if value is not None:
                return output_type.model_validate(value)
        raise StructuredModelError(ErrorCode.LLM_REFUSAL, "Claude가 구조화된 결과를 반환하지 않았습니다.")
```

- [ ] **Step 3: live 원문 분류를 단일 Claude 요청으로 목록화하고 즉시 폐기한다**

`update_review/collector.py`에 `ClassifiedRawItem`, `ClassifiedRawBatch`와 `classify_raw`를 추가한다. 모든 raw를 언어권 구분 없이 한 번의 tool call로 보내어 추가 비용을 1회로 제한한다. 이 요청은 live 경로에서만 발생하므로, 오케스트레이터는 live에서 collector 분류 1회 + 영향 분석 Sonnet 1회 + 레드팀 Haiku 1회만 실행하고 audit은 결정론적 설명을 사용해 `CLAUDE_MAX_REQUESTS=3`을 넘지 않는다.

```python
class ClassifiedRawItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    sentiment: Sentiment
    summary: str = Field(min_length=8, max_length=500)
    mechanism_tags: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)


class ClassifiedRawBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ClassifiedRawItem]


class UpdateCollectorAgent:
    prompt_path = Path(__file__).with_name("prompts") / "collector.md"

    def __init__(self, steam=None, x_client=None, *, use_llm=False, client=None, budget=None) -> None:
        self.steam = steam or SteamClient()
        self.x_client = x_client or XClient(os.getenv("X_BEARER_TOKEN"), ProjectBudget(cap_usd=10))
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def classify_raw(self, raw: list[RawFeedback], brief: UpdateBrief) -> list[UpdateEvidenceItem]:
        if not raw:
            return []
        if not self.use_llm:
            raise StructuredModelError(ErrorCode.LLM_REFUSAL, "live raw classification requires Claude")
        by_id = {item.source_id: item for item in raw}
        payload = {
            "update": brief.model_dump(mode="json"),
            "feedback": [{"source_id": item.source_id, "language": item.language.value, "observed_at": item.observed_at.isoformat(), "text": item.text} for item in raw],
        }
        batch = parse_claude_structured(model=os.getenv("CLAUDE_UPDATE_COLLECTOR_MODEL", "claude-haiku-4-5"), prompt_path=self.prompt_path, output_type=ClassifiedRawBatch, payload=payload, client=self.client, budget=self.budget)
        require_korean_text([item.summary for item in batch.items])
        output = []
        for item in batch.items:
            original = by_id.get(item.source_id)
            if original is None or not set(item.mechanism_tags) <= APPROVED_UPDATE_TAGS or not any(word in item.summary for word in ("예상", "가능성", "확인 필요")):
                raise StructuredModelError(ErrorCode.SCHEMA_INVALID, "Claude classifier returned unknown source or tag")
            output.append(UpdateEvidenceItem(evidence_id=f"live-update-{original.source.value}-{original.source_id}", source=original.source, source_url=original.source_url, source_id=original.source_id, language=original.language, observed_at=original.observed_at, period=EvidencePeriod.BEFORE, sentiment=item.sentiment, summary=item.summary, mechanism_tags=item.mechanism_tags, relevance=item.relevance))
        return output
```

`update_review/prompts/collector.md`에 원문 복사 금지, 개인정보 제거, 제공된 `source_id`만 반환, 폐쇄 `APPROVED_UPDATE_TAGS`만 사용, 반드시 `예상/가능성/확인 필요` 중 하나를 포함한 비식별 한국어 요약 규칙을 작성한다.

- [ ] **Step 4: 영향 분석 내러티브 계약과 근거 부분 병합을 추가한다**

`update_review/evidence.py`에 아래 출력 계약을 추가한다. `signal_id`와 `evidence_ids`가 고정 결과의 부분집할 때만 `title`, `summary`를 교체한다.

```python
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import ClaudeBudget, StructuredModelError, parse_claude_structured, require_korean_text
from contracts import ErrorCode


class SignalNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class EvidenceNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signals: list[SignalNarrative]


class UpdateEvidenceAgent:
    prompt_path = Path(__file__).with_name("prompts") / "evidence.md"

    def __init__(self, use_llm: bool = False, client=None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def run(self, bundle, on_event=None):
        base = self.run_deterministic(bundle, on_event=on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify("claude_narrative", "Claude Sonnet이 고정된 근거 범위에서 반응 설명을 보강합니다.", {"provider": "claude"})
        narrative = parse_claude_structured(model=os.getenv("CLAUDE_UPDATE_EVIDENCE_MODEL", "claude-sonnet-4-6"), prompt_path=self.prompt_path, output_type=EvidenceNarrative, payload=base, client=self.client, budget=self.budget)
        require_korean_text([text for item in narrative.signals for text in (item.title, item.summary)])
        signals = {item.signal_id: item for item in [*base.positive_signals, *base.negative_signals, *base.split_conditions]}
        for proposal in narrative.signals:
            official = signals.get(proposal.signal_id)
            if official is None or not set(proposal.evidence_ids) <= set(official.evidence_ids):
                raise StructuredModelError(ErrorCode.SCHEMA_INVALID, "Claude narrative references unknown signal evidence")
            signals[proposal.signal_id] = official.model_copy(update={"title": proposal.title, "summary": proposal.summary})
        notify("claude_output_checked", "Claude 설명의 신호·근거 ID를 확인했습니다.", {"provider": "claude"})
        return base.model_copy(update={
            "positive_signals": [signals[item.signal_id] for item in base.positive_signals],
            "negative_signals": [signals[item.signal_id] for item in base.negative_signals],
            "split_conditions": [signals[item.signal_id] for item in base.split_conditions],
        })
```

- [ ] **Step 5: 레드팀 내러티브 계약과 위험·지표 부분 병합을 추가한다**

`update_review/redteam.py`에 `RiskNarrative`, `RedteamNarrative`, `__init__`, `run` 및 `_merge_narrative`를 추가한다. 현재 `run_deterministic`은 수정하지 않는다.

```python
class RiskNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: str
    title: str = Field(min_length=1)
    failure_path: str = Field(min_length=1)
    revision_question: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class RedteamNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risks: list[RiskNarrative]


class UpdateRedteamAgent:
    prompt_path = Path(__file__).with_name("prompts") / "redteam.md"

    def __init__(self, use_llm: bool = False, client=None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def run(self, brief, pack, on_event=None):
        base = self.run_deterministic(brief, pack, on_event=on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify("claude_narrative", "Claude Haiku가 고정된 위험과 확인 지표 범위에서 설명을 보강합니다.", {"provider": "claude"})
        narrative = parse_claude_structured(model=os.getenv("CLAUDE_UPDATE_REDTEAM_MODEL", "claude-haiku-4-5"), prompt_path=self.prompt_path, output_type=RedteamNarrative, payload=base, client=self.client, budget=self.budget)
        require_korean_text([text for item in narrative.risks for text in (item.title, item.failure_path, item.revision_question)])
        risks = {item.risk_id: (index, item) for index, item in enumerate(base.risks)}
        metric_ids = {item.metric_id for item in base.validation_metrics}
        output = list(base.risks)
        for proposal in narrative.risks:
            official = risks.get(proposal.risk_id)
            if official is None or not set(proposal.evidence_ids) <= set(official[1].evidence_ids) or not set(proposal.validation_metric_ids) <= metric_ids:
                raise StructuredModelError(ErrorCode.SCHEMA_INVALID, "Claude narrative references unknown risk data")
            index, risk = official
            output[index] = risk.model_copy(update={"title": proposal.title, "failure_path": proposal.failure_path, "revision_question": proposal.revision_question})
        notify("claude_output_checked", "Claude 설명의 위험·근거·지표 ID를 확인했습니다.", {"provider": "claude"})
        return base.model_copy(update={"risks": output})
```

- [ ] **Step 6: 검증 내러티브 계약을 추가하되 판정 필드는 제외한다**

`update_review/audit.py`의 Claude 출력은 요약과 권고 문구만 포함한다. `UpdateDecision`을 포함하지 않는 것이 핵심이다.

```python
class RecommendationNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: str
    title: str = Field(min_length=1)
    action: str = Field(min_length=1)
    validation_metric_ids: list[str] = Field(min_length=1)


class AuditNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executive_summary: str = Field(min_length=1)
    recommendations: list[RecommendationNarrative]


class UpdateAuditAgent:
    prompt_path = Path(__file__).with_name("prompts") / "audit.md"

    def __init__(self, use_llm: bool = False, client=None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget
        self._executive_summary: str | None = None

    def run(self, bundle, pack, assessment, *, analysis_incomplete=False, on_event=None):
        base = self.run_deterministic(bundle, pack, assessment, analysis_incomplete=analysis_incomplete, on_event=on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify("claude_narrative", "Claude Haiku가 고정된 판정의 요약과 권고만 보강합니다.", {"provider": "claude"})
        narrative = parse_claude_structured(model=os.getenv("CLAUDE_UPDATE_AUDIT_MODEL", "claude-haiku-4-5"), prompt_path=self.prompt_path, output_type=AuditNarrative, payload=base, client=self.client, budget=self.budget)
        require_korean_text([narrative.executive_summary] + [text for item in narrative.recommendations for text in (item.title, item.action)])
        risks = {item.risk_id for item in base.validated_risks}
        metrics = {item.metric_id for item in base.validation_metrics}
        proposals = {item.risk_id: item for item in narrative.recommendations}
        recommendations = []
        for item in base.recommendations:
            risk_id = item.addresses_risk_ids[0]
            proposal = proposals.get(risk_id)
            if proposal is None:
                recommendations.append(item)
                continue
            if risk_id not in risks or not set(proposal.validation_metric_ids) <= metrics:
                raise StructuredModelError(ErrorCode.SCHEMA_INVALID, "Claude narrative references unknown audit data")
            recommendations.append(item.model_copy(update={"title": proposal.title, "action": proposal.action}))
        self._executive_summary = narrative.executive_summary
        notify("claude_output_checked", "코드 판정을 유지한 채 Claude 요약·권고 연결을 확인했습니다.", {"provider": "claude", "decision": base.decision.value})
        return base.model_copy(update={"recommendations": recommendations})

    def to_brief(self, brief, pack, impact, decision):
        result = self._deterministic_brief(brief, pack, impact, decision)
        return result if self._executive_summary is None else result.model_copy(update={"executive_summary": self._executive_summary})
```

Task 3에서 만든 기존 `to_brief` 본문은 `_deterministic_brief`로 이름만 바꾸고, 새 `to_brief`가 위와 같이 위임하게 한다.

- [ ] **Step 7: 세 분석 프롬프트의 변경 금지 규칙을 작성한다**

`update_review/prompts/evidence.md`, `redteam.md`, `audit.md`에 공통으로 다음 규칙을 넣고, 각 출력 schema의 문장 필드만 한국어로 작성하도록 명시한다.

```markdown
# 업데이트 점검 자연어 보강

당신은 코드가 이미 확정한 구조를 설명하는 역할만 한다.

- ID, enum, 감정, 기간, 신뢰도, 위험 등급, 판정을 새로 만들거나 바꾸지 마라.
- 제공된 evidence_ids·risk_id·validation_metric_ids의 부분집만 반환하라.
- 예측은 `예상`, `가능성`, `확인 필요` 중 하나를 포함하라.
- 한국어 설명을 작성하되 제품명·ID는 원형을 유지하라.
- 실제 이용자 반응으로 단정하지 마라.
- 요구된 structured_output tool로만 응답하라.
```

`evidence.md`는 `signals`, `redteam.md`는 `risks`, `audit.md`는 `executive_summary`/`recommendations`만 반환하라고 각각 마지막 줄에 명시한다.

- [ ] **Step 8: 오케스트레이터에 공유 예산·재시도·결정론 fallback을 추가한다**

`update_review/orchestrator.py::__init__`에서 `use_llm=True`일 때 `ClaudeBudget()` 하나를 만들어 세 에이전트에 공유한다. `run` 내 세 단계는 `run_deterministic`이 아닌 `run`을 호출한다.

```python
budget = ClaudeBudget() if use_llm else None
self.collector = collector or UpdateCollectorAgent(use_llm=use_llm, client=llm_client, budget=budget)
self.evidence_agent = evidence or UpdateEvidenceAgent(use_llm=use_llm, client=llm_client, budget=budget)
self.redteam = redteam or UpdateRedteamAgent(use_llm=use_llm, client=llm_client, budget=budget)
self.audit = audit or UpdateAuditAgent(use_llm=use_llm, client=llm_client, budget=budget)
self.use_llm = use_llm
self.llm_provider = "claude" if use_llm else "deterministic"
self.llm_requested = use_llm
```

`run()`은 fixture/import에서는 evidence → redteam → audit 순서로 Claude를 호출하고, live에서는 raw 분류 → evidence → redteam까지만 Claude를 호출한 뒤 audit의 `run_deterministic`을 사용한다. 이 선택은 agent 객체의 `use_llm` 상태를 바꾸지 말고 호출할 메서드를 고르는 지역 분기로 구현한다. FastAPI는 요청마다 orchestrator를 새로 만들므로 예산·요약 상태가 요청 사이에 공유되지 않는다.

`stage` helper는 `StructuredModelError` 중 `SCHEMA_INVALID`·`LLM_REFUSAL`만, 공유 예산에 요청 여유가 있을 때 1회 재시도한다. `AUTH_FAILED`·`BUDGET_EXCEEDED`는 재시도하지 않고 즉시 결정론 경로로 전환한다. 한 번이라도 재시도나 전환이 필요해지면 남은 단계는 결정론적 메서드로 실행해 전체 요청 수를 3회 이하로 고정하고 `fallback_used=True`를 남긴다. 재시도도 실패하면 fixture/import는 현재 단계부터 결정론적 메서드를 사용한다. live collector 분류가 끝내 실패한 경우에는 raw를 폐기하고 Task 5의 빈 `PARTIAL` bundle → `Hold` 경로로 진행한다. 어느 경우에도 새 자료를 Dragunov fixture로 바꾸지 않는다. 최종 `UpdatePipelineResult`에 `fallback_used`, `analysis_incomplete`, `llm_provider`, `llm_requested`를 실제 값으로 넘긴다.

- [ ] **Step 9: 업데이트 Claude 모델 환경변수 예시를 추가한다**

`backend/.env.example`에 다음 네 줄을 추가하고 실제 키는 기록하지 않는다.

```dotenv
CLAUDE_UPDATE_EVIDENCE_MODEL=claude-sonnet-4-6
CLAUDE_UPDATE_REDTEAM_MODEL=claude-haiku-4-5
CLAUDE_UPDATE_AUDIT_MODEL=claude-haiku-4-5
CLAUDE_UPDATE_COLLECTOR_MODEL=claude-haiku-4-5
```

- [ ] **Step 10: Claude 병합·fallback·기존 structured API 회귀를 확인한다**

Run: `uv run pytest tests/test_update_pipeline.py tests/test_structured_api.py -v`

Expected: PASS; no network call is made.

- [ ] **Step 11: Task 4를 커밋한다**

```bash
git add agents/structured.py update_review/collector.py update_review/evidence.py update_review/redteam.py update_review/audit.py update_review/orchestrator.py update_review/prompts/collector.md update_review/prompts/evidence.md update_review/prompts/redteam.md update_review/prompts/audit.md backend/.env.example tests/test_update_pipeline.py tests/test_structured_api.py
git commit -m "feat: add controlled Claude update analysis"
```

---

### Task 5: 선택적 CSV·Steam·X 소스와 안전 보류

**Files:**
- Modify: `connectors/steam/client.py`
- Modify: `connectors/x/client.py`
- Modify: `update_review/collector.py`
- Create: `tests/test_update_sources.py`

**Interfaces:**
- Consumes: `RawFeedback`, `ConnectorError`, `SteamClient.fetch_reviews(...)`, `XClient.fetch_recent(...)`
- Produces: backward-compatible optional `start_at: datetime | None = None` arguments on both connector methods
- Produces: `import_update_csv(data: bytes | str, cutoff_at: datetime) -> list[UpdateEvidenceItem]`
- Produces: `UpdateCollectorAgent.run(...)` live/import paths with no fixture substitution

- [ ] **Step 1: 기간 필터·CSV 금지 열·연결 실패 미대체 테스트를 작성한다**

`tests/test_update_sources.py`를 다음으로 작성한다. connector fake payload 형태는 기존 `tests/test_connectors.py`의 opener 패턴을 재사용한다.

```python
import json
from datetime import UTC, datetime, timedelta

import pytest

from connectors import ConnectorError
from connectors.steam import SteamClient
from contracts import ArtifactStatus, ErrorCode, Language
from update_review.collector import UpdateCollectionOptions, UpdateCollectorAgent, import_update_csv
from update_review.contracts import EvidencePeriod, Sentiment, UpdateDecision
from update_review.fixtures import load_dragunov_brief
from update_review.orchestrator import UpdateReviewOrchestrator


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_steam_start_at_excludes_older_reviews():
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    payload = {
        "reviews": [
            {"timestamp_created": int((cutoff - timedelta(days=2)).timestamp()), "recommendationid": "inside", "review": "Dragunov fixed damage feels predictable"},
            {"timestamp_created": int((cutoff - timedelta(days=20)).timestamp()), "recommendationid": "old", "review": "old"},
        ],
        "cursor": "",
    }
    rows = SteamClient(opener=lambda *_args, **_kwargs: Response(payload)).fetch_reviews(
        578080,
        Language.ENGLISH,
        cutoff,
        start_at=cutoff - timedelta(days=7),
    )
    assert len(rows) == 1
    assert rows[0].text.startswith("Dragunov")


def test_update_csv_forbids_raw_and_identity_columns():
    with pytest.raises(ConnectorError, match="personal/raw columns are forbidden"):
        import_update_csv(
            "source,source_url,source_id,language,observed_at,period,sentiment,summary,mechanism_tags,username\n",
            datetime(2026, 8, 13, tzinfo=UTC),
        )


def test_update_csv_preserves_declared_period_and_sentiment():
    csv_data = "\n".join([
        "source,source_url,source_id,language,observed_at,period,sentiment,summary,mechanism_tags",
        "reddit,https://www.reddit.com/r/PUBATTLEGROUNDS/comments/abc,public-1,ko,2026-08-12T00:00:00+00:00,before,negative,피해 변경을 테스트해야 한다는 비식별 요약,balance_regression",
    ])
    item = import_update_csv(csv_data, datetime(2026, 8, 13, tzinfo=UTC))[0]
    assert item.period is EvidencePeriod.BEFORE
    assert item.sentiment is Sentiment.NEGATIVE
    assert item.source_id != "public-1"
    assert item.source_url == "https://www.reddit.com"


def test_update_csv_rejects_actual_after_row_for_prelaunch_cutoff():
    csv_data = "\n".join([
        "source,source_url,source_id,language,observed_at,period,sentiment,summary,mechanism_tags",
        "reddit,https://www.reddit.com/r/PUBATTLEGROUNDS/comments/after,public-2,ko,2026-08-12T00:00:00+00:00,after,negative,출시 후 실제 반응이라고 주장하는 요약,balance_regression",
    ])
    with pytest.raises(ConnectorError, match="after period is not allowed in prelaunch import"):
        import_update_csv(csv_data, datetime(2026, 8, 13, tzinfo=UTC))


def test_live_failure_never_substitutes_dragunov_fixture():
    class BrokenSteam:
        def fetch_reviews(self, *args, **kwargs):
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE, "offline")

    collector = UpdateCollectorAgent(steam=BrokenSteam())
    result = UpdateReviewOrchestrator(collector=collector).run(
        load_dragunov_brief("live-failure"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
    )
    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.feedback.evidence == []
    assert result.brief.decision is UpdateDecision.HOLD
    assert result.analysis_incomplete is True
    assert result.fallback_used is False
```

- [ ] **Step 2: 소스 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_sources.py -v`

Expected: FAIL because `start_at` and `import_update_csv` do not exist.

- [ ] **Step 3: 기존 connector 시그니처를 깨지 않고 시작 시간 필터를 추가한다**

`connectors/steam/client.py::fetch_reviews`와 `connectors/x/client.py::fetch_recent`의 마지막 keyword parameter로 `start_at: datetime | None = None`을 추가한다. 기존 호출자는 영향을 받지 않는다.

```python
if start_at is not None:
    if start_at.tzinfo is None or start_at >= cutoff_at:
        raise ValueError("start_at must be timezone-aware and earlier than cutoff_at")
```

각 review/tweet의 `observed_at`을 만든 직후 기존 필터를 다음과 같이 바꾸다.

```python
if observed_at >= cutoff_at or (start_at is not None and observed_at < start_at):
    continue
```

- [ ] **Step 4: 업데이트 전용 승인 CSV importer를 collector 모듈에 추가한다**

`update_review/collector.py`에 stdlib `csv`, `hashlib`, `io`, `urlparse` 기반 importer를 추가한다. 이벤트 importer는 계약이 다르므로 수정하지 않는다.

```python
REQUIRED_UPDATE_COLUMNS = {"source", "source_url", "source_id", "language", "observed_at", "period", "sentiment", "summary", "mechanism_tags"}
FORBIDDEN_COLUMNS = {"username", "user_name", "author", "handle", "raw_text", "text", "content", "account_id"}
APPROVED_HOSTS = {
    "reddit": (SourceType.REDDIT_IMPORT, {"reddit.com", "www.reddit.com"}),
    "threads": (SourceType.THREADS_IMPORT, {"threads.net", "www.threads.net"}),
    "instagram": (SourceType.INSTAGRAM_IMPORT, {"instagram.com", "www.instagram.com"}),
}
APPROVED_UPDATE_TAGS = {"predictability", "skill_fairness", "fairness_regression", "balance_regression", "validation_needed", "information_clarity", "flow_disruption", "rule_exception", "learning_burden"}


def import_update_csv(data: bytes | str, cutoff_at: datetime) -> list[UpdateEvidenceItem]:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    if forbidden := columns & FORBIDDEN_COLUMNS:
        raise ConnectorError(ErrorCode.INVALID_IMPORT, f"personal/raw columns are forbidden: {', '.join(sorted(forbidden))}")
    if missing := REQUIRED_UPDATE_COLUMNS - columns:
        raise ConnectorError(ErrorCode.INVALID_IMPORT, f"missing columns: {', '.join(sorted(missing))}")
    output = []
    for row_number, row in enumerate(reader, start=2):
        try:
            source, hosts = APPROVED_HOSTS[row["source"].strip().lower()]
            parsed = urlparse(row["source_url"].strip())
            if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.port not in (None, 443):
                raise ValueError("source URL is not from an approved host")
            observed_at = datetime.fromisoformat(row["observed_at"]).astimezone(UTC)
            if observed_at >= cutoff_at:
                raise ValueError("row is on or after cutoff_at")
            tags = sorted({value.strip() for value in row["mechanism_tags"].split("|") if value.strip()})
            if not tags or not set(tags) <= APPROVED_UPDATE_TAGS:
                raise ValueError("mechanism_tags must contain only approved update values")
            public_id = row["source_id"].strip()
            period = EvidencePeriod(row["period"].strip())
            if period is EvidencePeriod.AFTER:
                raise ValueError("after period is not allowed in prelaunch import")
            anonymous_id = hashlib.sha256(f"{source.value}:{public_id}".encode()).hexdigest()[:20]
            output.append(UpdateEvidenceItem(
                evidence_id=f"imp-update-{anonymous_id}",
                source=source,
                source_url=f"https://{parsed.hostname}",
                source_id=anonymous_id,
                language=Language(row["language"].strip()),
                observed_at=observed_at,
                period=period,
                sentiment=Sentiment(row["sentiment"].strip()),
                summary=row["summary"].strip(),
                mechanism_tags=tags,
                relevance=1.0,
            ))
        except (KeyError, ValueError) as exc:
            raise ConnectorError(ErrorCode.INVALID_IMPORT, f"row {row_number}: {exc}") from exc
    return output
```

- [ ] **Step 5: live/import 수집 분기와 원문 메모리 폐기를 구현한다**

Task 4에서 만든 `UpdateCollectorAgent.__init__` 시그니처는 유지하고, 기존 connector class 주입을 아래 두 대입으로 연결한다.

```python
self.steam = steam or SteamClient()
self.x_client = x_client or XClient(os.getenv("X_BEARER_TOKEN"), ProjectBudget(cap_usd=10))
```

`run`에서 `use_fixture=False`인 경우만 다음을 실행한다.

1. `options.input_mode == InputMode.LIVE`일 때만 `period_start`, `period_end`를 모두 요구하고 `period_start < period_end <= brief.cutoff_at`을 검증한다. import는 각 행의 `observed_at`과 `brief.cutoff_at`으로 검증한다.
2. CSV는 `import_update_csv`로 즉시 `UpdateEvidenceItem`으로 변환한다.
3. Steam·X는 5개 `Language`을 순회하며 `start_at=period_start`, `cutoff_at=period_end`로 호출한다.
4. 새 live raw는 `classify_raw(raw, brief)`로 즉시 비식별 `UpdateEvidenceItem`으로 바꿔 연결한다. `use_llm=False` 또는 분류 실패이면 raw를 artifact에 싣지 않고 `PipelineError(code=..., message=str(exc), retryable=False)`를 남긴다. 구조 오류·거절은 각각 `SCHEMA_INVALID`·`LLM_REFUSAL`, 키·예산 문제는 원래 `AUTH_FAILED`·`BUDGET_EXCEEDED` 코드를 보존한다.
5. `RawFeedback` list는 분류 직후 `del raw`로 참조를 제거하고 artifact·event·log에 넣지 않는다.
6. 언어권별 `general_count`는 connector에서 수집한 raw 건수, `mechanism_count`는 비식별 분류에 성공한 관련 근거 건수로 계산한다.
7. 오류가 있거나 근거·표본이 부족하면 추적 가능한 `PARTIAL`을 반환한다. 외부 실패를 예외로 중단하거나 `FAILED`로 바꾸지 않는다.

최소 상태 분기는 다음을 사용한다.

```python
status = ArtifactStatus.COMPLETE
if errors or not evidence or any(not sample.sufficient for sample in samples):
    status = ArtifactStatus.PARTIAL
```

- [ ] **Step 6: 불완전한 외부 수집을 안전 `Hold`로 종료하도록 orchestrator를 조정한다**

`update_review/orchestrator.py`에서 외부 `PARTIAL` bundle도 평소와 같은 결정론적 evidence → redteam → audit 경로로 연결한다. 근거가 없으면 빈 신호·위험·지표가 생성되고, Task 1의 `UpdateImpactAssessment` validator는 `errors`가 있는 경우에만 빈 근거를 허용한다. audit에는 아래 지역값을 넘겨 최종 판정을 `Hold`로 고정한다.

```python
analysis_incomplete = options.input_mode != InputMode.FIXTURE and (
    not feedback.evidence or any(not sample.sufficient for sample in feedback.samples)
)
validated = stage(
    "audit_strategy",
    lambda: self.audit.run_deterministic(
        feedback,
        evidence,
        impact,
        analysis_incomplete=analysis_incomplete,
        on_event=nodes("audit_strategy"),
    ).model_copy(update=metadata),
    UpdateValidatedDecision,
    Producer.AUDIT_STRATEGY,
    {feedback.ref, evidence.ref, impact.ref},
)
```

`feedback.errors`는 이후 artifact에 그대로 승계하고, 이 경로에서는 `load_update_feedback_fixture`를 절대 호출하지 않는다.

- [ ] **Step 7: 소스·기존 connector·오케스트레이터 회귀를 확인한다**

Run: `uv run pytest tests/test_update_sources.py tests/test_connectors.py tests/test_importer.py tests/test_update_pipeline.py -v`

Expected: PASS.

- [ ] **Step 8: Task 5를 커밋한다**

```bash
git add connectors/steam/client.py connectors/x/client.py update_review/collector.py update_review/contracts.py update_review/orchestrator.py tests/test_update_sources.py
git commit -m "feat: add safe update review sources"
```

---

### Task 6: FastAPI 업데이트 전용 REST·SSE API

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Create: `tests/test_update_api.py`

**Interfaces:**
- Consumes: `UpdateReviewOrchestrator`, `UpdateCollectionOptions`, `UpdateBrief`
- Produces: `POST /api/update-runs`, `POST /api/update-runs/stream`
- Preserves: `GET /health`, `POST /api/runs`, `POST /api/runs/stream`

- [ ] **Step 1: 요청 검증·fixture 결과·SSE·기존 API 회귀 실패 테스트를 작성한다**

`tests/test_update_api.py`를 다음으로 작성한다.

```python
from fastapi.testclient import TestClient

from backend.app.main import app


def event_payload() -> dict:
    return {
        "game": "PUBG: BATTLEGROUNDS",
        "event_name": "Black Market 2025",
        "goal": "목표 보상까지의 비용과 진행 경로를 명확히 이해할 수 있도록 한다.",
        "target_users": ["복귀 유저"],
        "starts_on": "2025-06-11",
        "ends_on": "2025-07-22",
        "cutoff_on": "2025-06-11",
        "participation_rule": "패스 미션",
        "repeat_rule": "일일 미션",
        "rewards": ["Progressive weapon skin"],
        "currencies": ["G-Coin"],
        "probability_guarantee": "고정 보장 없음",
        "monetization_policy": "확률형 상품 판매",
        "expiration_policy": "종료 후 삭제",
        "source_mode": "fixture",
    }


def payload() -> dict:
    return {
        "game": "PUBG: BATTLEGROUNDS",
        "update_name": "Dragunov 확률 피해 제거",
        "update_type": "weapon_balance",
        "current_state": "기본 58, 최대 73의 확률형 피해",
        "change_summary": "피해를 60으로 고정",
        "goal": "전투 결과 예측 가능성을 높인다.",
        "expected_benefits": ["공정성 인식 개선"],
        "concerns": ["실제 전투 성능은 확인 필요"],
        "scope": "일반 매칭",
        "planned_on": "2026-08-20",
        "cutoff_on": "2026-08-13",
        "official_context_url": "https://pubg.com/en/news/6616",
        "official_context": "PUBG Update 25.2의 확률형 피해 제거 공식 변경 맥락",
        "details": {
            "kind": "weapon_balance",
            "target_weapon": "Dragunov",
            "damage": "기본 58·최대 73 확률 → 60 고정",
            "recoil": "현행 유지",
            "rate_of_fire": "해당 없음",
            "ammunition": "7.62mm",
            "spawn_and_modes": "일반 매칭",
        },
        "source_mode": "fixture",
        "fixture_case": "dragunov_random_damage_removal",
        "use_llm": False,
    }


def test_update_fixture_endpoint_returns_prelaunch_test_decision():
    response = TestClient(app).post("/api/update-runs", json=payload())
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["brief"]["decision"] == "Test"
    assert result["feedback"]["input_mode"] == "fixture"
    assert {item["period"] for item in result["brief"]["evidence"]} == {"comparable_reference"}
    assert all(item["synthetic"] for item in result["brief"]["evidence"])
    assert result["events"]


def test_update_type_details_must_match():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {"update_type": "ui_ux"},
    )
    assert response.status_code == 422
    assert "details kind must match" in response.text


def test_update_live_request_requires_time_window_and_connector():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {"source_mode": "live"},
    )
    assert response.status_code == 422
    assert "live source requires" in response.text


def test_dragunov_fixture_is_available_only_for_weapon_balance():
    response = TestClient(app).post(
        "/api/update-runs",
        json=payload() | {
            "update_type": "ui_ux",
            "details": {"kind": "ui_ux", "changed_screen": "인벤토리", "user_journey": "상품 선택 → 착용", "exposed_information": "능력치", "possible_errors": "해당 없음"},
        },
    )
    assert response.status_code == 422
    assert "Dragunov fixture requires weapon_balance" in response.text


def test_update_stream_emits_agent_nodes_and_result():
    response = TestClient(app).post("/api/update-runs/stream", json=payload())
    assert response.status_code == 200
    assert "event: agent_event" in response.text
    assert '"decision": "Test"' in response.text
    assert "event: done" in response.text


def test_existing_event_endpoint_still_works():
    response = TestClient(app).post("/api/runs", json=event_payload())
    assert response.status_code == 200
    assert response.json()["result"]["brief"]["decision"] == "Revise"
```

기존 이벤트 payload는 위 `event_payload()` 로컬 helper에만 반복하고 테스트 모듈 간 공유 추상화는 만들지 않는다.

- [ ] **Step 2: API 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_api.py -v`

Expected: FAIL with `404 Not Found` for `/api/update-runs`.

- [ ] **Step 3: 유형별 details request 계약과 소스 검증을 추가한다**

`backend/app/schemas.py`에 추가한다. 프론트엔드 payload와 domain 계약이 같은 field를 쓰도록 request details는 `update_review.contracts` 모델을 그대로 재사용한다.

```python
from datetime import datetime
from update_review.contracts import UpdateDetails, UpdateType


class UpdateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game: str = Field(min_length=1)
    update_name: str = Field(min_length=1)
    update_type: UpdateType
    current_state: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_benefits: list[str] = Field(min_length=1)
    concerns: list[str] = Field(min_length=1)
    scope: str = Field(min_length=1)
    planned_on: date
    cutoff_on: date
    official_context_url: str | None = None
    official_context: str | None = Field(default=None, min_length=1)
    details: UpdateDetails
    source_mode: Literal["fixture", "live", "import"] = "fixture"
    fixture_case: Literal["dragunov_random_damage_removal"] = "dragunov_random_damage_removal"
    period_start: datetime | None = None
    period_end: datetime | None = None
    steam_app_id: int | None = Field(default=None, ge=1)
    use_x: bool = False
    x_query: str = "PUBG Dragunov damage"
    x_estimated_total_cost_usd: float = Field(default=0, ge=0, le=10)
    imported_csv: str | None = None
    use_llm: bool = True

    @model_validator(mode="after")
    def validate_update_request(self) -> "UpdateRunRequest":
        if self.details.kind != self.update_type.value:
            raise ValueError("details kind must match update_type")
        if self.source_mode == "fixture" and self.update_type is not UpdateType.WEAPON_BALANCE:
            raise ValueError("Dragunov fixture requires weapon_balance update_type")
        if self.source_mode == "live":
            if not (self.steam_app_id or self.use_x):
                raise ValueError("live source requires steam_app_id or use_x")
            if self.period_start is None or self.period_end is None:
                raise ValueError("live source requires period_start and period_end")
        if self.source_mode == "import" and not self.imported_csv:
            raise ValueError("import source requires imported_csv")
        return self
```

`UpdateDetails`을 외부 import할 수 있도록 `update_review/contracts.py`의 alias를 그대로 유지한다. 별도 response class는 만들지 않고 기존 `PipelineRunResponse`를 재사용한다.

- [ ] **Step 4: request를 domain brief·collection options로 변환하는 두 helper를 추가한다**

`backend/app/main.py`에 다음 helper를 추가한다. 기존 이벤트 API의 base64 `_csv_bytes`는 바꾸지 않고, 업데이트 승인 CSV는 브라우저 textarea의 UTF-8 문자열을 받는 아래 2 MB 제한 helper로 분리한다.

```python
def _update_csv_bytes(value: str | None) -> bytes | None:
    if not value:
        return None
    encoded = value.encode("utf-8")
    if len(encoded) > 2_000_000:
        raise HTTPException(status_code=422, detail="imported_csv is limited to 2 MB")
    return encoded


def _update_brief(request: UpdateRunRequest, run_id: str) -> UpdateBrief:
    return UpdateBrief(
        run_id=run_id,
        producer=Producer.USER,
        game=request.game,
        update_name=request.update_name,
        update_type=request.update_type,
        current_state=request.current_state,
        change_summary=request.change_summary,
        goal=request.goal,
        expected_benefits=request.expected_benefits,
        concerns=request.concerns,
        scope=request.scope,
        planned_at=datetime.combine(request.planned_on, time.min, tzinfo=UTC),
        cutoff_at=datetime.combine(request.cutoff_on, time.min, tzinfo=UTC),
        official_context_url=request.official_context_url,
        official_context=request.official_context,
        details=request.details,
    )


def _run_update(request: UpdateRunRequest, run_id: str, on_event: Callable[[ExecutionEvent], None] | None = None) -> dict:
    brief = _update_brief(request, run_id)
    options = UpdateCollectionOptions(
        use_fixture=request.source_mode == "fixture",
        fixture_case=request.fixture_case,
        imported_csv=_update_csv_bytes(request.imported_csv),
        steam_app_id=request.steam_app_id if request.source_mode == "live" else None,
        use_x=request.use_x if request.source_mode == "live" else False,
        x_query=request.x_query,
        period_start=request.period_start,
        period_end=request.period_end,
        x_estimated_total_cost_usd=request.x_estimated_total_cost_usd,
    )
    result = UpdateReviewOrchestrator(use_llm=request.use_llm).run(
        brief,
        options,
        on_event=on_event,
        log_path=ROOT / ".data" / "runs" / f"{run_id}.jsonl",
    )
    return {
        "brief": result.brief.model_dump(mode="json"),
        "feedback": result.feedback.model_dump(mode="json"),
        "evidence": result.evidence.model_dump(mode="json"),
        "impact": result.impact.model_dump(mode="json"),
        "validated": result.validated.model_dump(mode="json"),
        "events": [item.model_dump(mode="json") for item in result.events],
        "fallback_used": result.fallback_used,
        "analysis_incomplete": result.analysis_incomplete,
        "llm_provider": result.llm_provider,
        "llm_requested": result.llm_requested,
    }
```

- [ ] **Step 5: REST·SSE 엔드포인트를 추가한다**

`backend/app/main.py`의 기존 endpoint 아래에 다음을 추가한다. SSE worker는 기존 `/api/runs/stream`의 queue 패턴을 그대로 사용하되 `_run_update`만 호출한다.

```python
@app.post("/api/update-runs", response_model=PipelineRunResponse)
def create_update_run(request: UpdateRunRequest) -> PipelineRunResponse:
    run_id = str(uuid4())
    try:
        result = _run_update(request, run_id)
    except (ValueError, PipelineStopped) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="업데이트 점검 실행 중 오류가 발생했습니다.") from exc
    return PipelineRunResponse(run_id=run_id, result=result)


@app.post("/api/update-runs/stream")
def stream_update_run(request: UpdateRunRequest) -> StreamingResponse:
    run_id = str(uuid4())
    messages: Queue[tuple[str, dict] | None] = Queue()

    def emit(event: ExecutionEvent) -> None:
        messages.put(("agent_event", {"event": event.model_dump(mode="json")}))

    def worker() -> None:
        try:
            messages.put(("started", {"run_id": run_id}))
            messages.put(("result", {"run_id": run_id, "result": _run_update(request, run_id, emit)}))
        except HTTPException as exc:
            messages.put(("error", {"detail": exc.detail, "status_code": exc.status_code}))
        except (ValueError, PipelineStopped) as exc:
            messages.put(("error", {"detail": str(exc), "status_code": 422}))
        except Exception:
            messages.put(("error", {"detail": "업데이트 점검 실행 중 오류가 발생했습니다.", "status_code": 500}))
        finally:
            messages.put(None)

    Thread(target=worker, daemon=True).start()

    def events():
        while True:
            message = messages.get()
            if message is None:
                yield "event: done\ndata: {}\n\n"
                return
            name, payload = message
            yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

기존 `stream_run`은 수정하지 않는다. 두 endpoint의 중복은 이벤트 API 회귀 위험을 줄이는 의도적 중복이다.

- [ ] **Step 6: 업데이트·기존 API 테스트를 같이 실행한다**

Run: `uv run pytest tests/test_update_api.py tests/test_api.py -v`

Expected: PASS.

- [ ] **Step 7: Task 6을 커밋한다**

```bash
git add backend/app/schemas.py backend/app/main.py tests/test_update_api.py
git commit -m "feat: expose update review API"
```

---

### Task 7: Next.js 모드 선택·업데이트 입력·결과 화면

**Files:**
- Create: `frontend/app/components/AgentPipeline.tsx`
- Create: `frontend/app/components/UpdateReview.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/globals.css`
- Create: `tests/test_frontend_update_contract.py`

**Interfaces:**
- Consumes: `POST /api/update-runs/stream` SSE events `started|agent_event|result|error|done`
- Produces: `AgentPipeline({events, active, mode}: {events: AgentEvent[]; active?: boolean; mode: "event" | "update"})`
- Produces: `UpdateReview()` client component
- Preserves: 기존 이벤트 입력·결과·`/api/runs/stream` 호출

- [ ] **Step 1: Next 16 Client Component·CSS·접근성 문서를 확인한다**

Run:

```bash
sed -n '1,220p' frontend/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md
sed -n '1,180p' frontend/node_modules/next/dist/docs/01-app/01-getting-started/11-css.md
sed -n '1,220p' frontend/node_modules/next/dist/docs/03-architecture/accessibility.md
```

Expected: `"use client"` 경계, global CSS import 규칙, 키보드·ARIA 기본 요구사항을 확인한다.

- [ ] **Step 2: 화면 문구·엔드포인트·조건부 표시 계약의 실패 테스트를 작성한다**

`tests/test_frontend_update_contract.py`를 작성한다. 새 프론트 테스트 패키지를 추가하지 않고, Next build에 더해 필수 문구·API·조건부 렌더링의 소스 계약만 확인한다.

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "frontend" / "app"


def test_home_exposes_accessible_review_mode_switch():
    source = (ROOT / "page.tsx").read_text(encoding="utf-8")
    assert 'aria-pressed={reviewMode === "event"}' in source
    assert 'aria-pressed={reviewMode === "update"}' in source
    assert "이벤트 점검" in source
    assert "업데이트 점검" in source


def test_update_screen_has_prelaunch_copy_and_four_decision_labels():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")
    assert "출시 전 예상이며 실제 이용자 반응이 아닙니다" in source
    assert 'Go: "출시 가능"' in source
    assert 'Revise: "일부 수정 후 출시"' in source
    assert 'Test: "테스트 후 출시"' in source
    assert 'Hold: "판정 보류"' in source
    assert 'fetch(`${API_URL}/api/update-runs/stream`' in source


def test_actual_after_section_is_conditionally_rendered():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")
    assert 'item.period === "after"' in source
    assert "업데이트 후 실제 반응" in source
    assert "출시 후 검증할 지표" in source


def test_language_ratios_are_hidden_when_sample_conclusion_is_hidden():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")
    assert "language.conclusion ?" in source
    assert "language.hidden_reason" in source
    assert "language.sentiment_counts" in source


def test_official_context_is_visually_separate_from_synthetic_evidence():
    source = (ROOT / "components" / "UpdateReview.tsx").read_text(encoding="utf-8")
    assert "공식으로 확인된 변경 맥락" in source
    assert "official_context" in source
    assert "synthetic" in source


def test_shared_pipeline_has_update_contract_names_and_owners():
    source = (ROOT / "components" / "AgentPipeline.tsx").read_text(encoding="utf-8")
    for contract in ("UpdateFeedbackBundle", "UpdateEvidencePack", "UpdateImpactAssessment", "UpdateValidatedDecision"):
        assert contract in source
    for owner in ("정현예", "유주심", "정아현", "승진배"):
        assert owner in source
```

- [ ] **Step 3: 프론트 계약 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_frontend_update_contract.py -v`

Expected: FAIL because `frontend/app/components/UpdateReview.tsx` does not exist.

- [ ] **Step 4: 기존 4행 파이프라인을 공유 컴포넌트로 추출한다**

`frontend/app/components/AgentPipeline.tsx`를 `"use client"`로 작성하고, 현재 `page.tsx`의 `AgentEvent`, `agents`, `agentOrder`, `nodeLabels`, `stateLabels`, `AgentPipeline` 본문을 옮긴다. 모드별 출력 계약과 역할만 아래 매핑으로 바꾸고 JSX 구조와 로딩 animation은 그대로 보존한다.

```tsx
"use client";

import { useMemo } from "react";

export type AgentEvent = {
  sequence: number;
  agent: string;
  node: string;
  state: string;
  message: string;
  metrics: Record<string, string | number | boolean>;
};

const agentOrder = ["collection", "evidence_rag_personas", "event_redteam", "audit_strategy"];
const owners: Record<string, string> = {
  collection: "정현예",
  evidence_rag_personas: "유주심",
  event_redteam: "정아현",
  audit_strategy: "승진배",
};
const eventAgents = {
  collection: { label: "자료 수집 에이전트", contract: "FeedbackBundle", role: "기준일 이전 자료를 모으고 개인정보를 남기지 않는 요약 자료를 만듭니다." },
  evidence_rag_personas: { label: "의견 정리 에이전트", contract: "EvidencePack", role: "반복 문제와 이용자 유형을 정리합니다." },
  event_redteam: { label: "위험 점검 에이전트", contract: "RiskAssessment", role: "이벤트 실패 경로를 점검합니다." },
  audit_strategy: { label: "최종 판정 에이전트", contract: "ValidatedDecision", role: "근거와 정책으로 최종 판정을 고정합니다." },
};
const updateAgents = {
  collection: { label: "자료 수집 에이전트", contract: "UpdateFeedbackBundle", role: "기간·출처·감정·비식별 요약을 업데이트 자료로 정규화합니다." },
  evidence_rag_personas: { label: "변경 영향 분석 에이전트", contract: "UpdateEvidencePack", role: "긍정·부정·혼합 신호와 이용자 유형을 연결합니다." },
  event_redteam: { label: "업데이트 레드팀 에이전트", contract: "UpdateImpactAssessment", role: "실패 경로와 출시 후 확인 지표를 제안합니다." },
  audit_strategy: { label: "검증·전략 에이전트", contract: "UpdateValidatedDecision", role: "근거·위험·지표를 검증해 출시 판정을 계산합니다." },
};
const nodeLabels: Record<string, string> = {
  source_selected: "자료 출처 확인", cutoff_checked: "검토 기준일 확인", period_checked: "자료 기간 구분", anonymized: "개인정보 보호 처리", samples_counted: "언어별 의견 수 집계", bundle_ready: "수집 결과 정리",
  deduplicated: "중복 의견 정리", signals_grouped: "반응 신호 분류", issues_grouped: "반복 문제 분류", language_gate_checked: "언어별 자료 충분성 확인", personas_linked: "이용자 유형 연결", personas_built: "이용자 유형 정리", pack_ready: "의견 분석 결과 정리",
  change_reviewed: "변경 전·후 점검", event_reviewed: "이벤트 조건 점검", failure_paths_built: "문제 발생 경로 정리", metrics_linked: "확인 지표 연결", assessment_ready: "영향 점검 결과 정리",
  evidence_checked: "근거 존재 확인", risks_validated: "위험 기준 검토", sample_gate_applied: "자료 충분성 확인", decision_fixed: "최종 판정", recommendations_built: "실행 권고 정리", revisions_built: "개선안 정리", claude_narrative: "Claude 설명 생성", claude_output_checked: "Claude 결과 안전성 확인",
};
const stateLabels: Record<string, string> = { waiting: "대기 중", running: "처리 중", retrying: "재시도 중", complete: "완료", failed: "확인 필요" };

export function AgentPipeline({ events, active = false, mode }: { events: AgentEvent[]; active?: boolean; mode: "event" | "update" }) {
  const agents = mode === "update" ? updateAgents : eventAgents;
  const groups = useMemo(() => agentOrder.map((agent) => {
    const allEvents = events.filter((event) => event.agent === agent);
    const visibleEvents = allEvents.filter((event) => !["queued", "agent"].includes(event.node));
    const failed = allEvents.some((event) => event.state === "failed");
    const complete = allEvents.some((event) => event.node === "agent" && event.state === "complete");
    const running = allEvents.some((event) => ["running", "retrying"].includes(event.state));
    const status = failed ? "failed" : complete ? "complete" : running ? "running" : "waiting";
    const current = [...visibleEvents].reverse().find((event) => ["running", "retrying"].includes(event.state));
    return { agent, events: visibleEvents, status, current };
  }), [events]);
  const inputCopy = mode === "update" ? "업데이트 변경안 + 자료" : "이벤트 정보 + 자료";
  const outputCopy = mode === "update" ? "출시 전 업데이트 판정" : "최종 검토 결과";
  return <section className="pipeline">
    <div className="pipeline-head"><strong>입력</strong><code>{inputCopy}</code><span>→</span><strong>출력</strong><code>{outputCopy}</code><span className={`pipeline-state ${active ? "is-running" : "is-complete"}`}><i />{active ? "에이전트가 순서대로 실행 중입니다" : "실행이 완료되었습니다"}</span></div>
    {groups.map(({ agent, events: nodeEvents, status, current }, index) => {
      const info = agents[agent as keyof typeof agents];
      return <div className={`agent-row agent-${status}`} key={agent}>
        <div className="agent-meta"><small>단계 {String(index + 1).padStart(2, "0")}</small><h3>{info.label}</h3><span className="agent-status"><i />{stateLabels[status]}{current ? ` · ${nodeLabels[current.node] ?? current.node}` : ""}</span><p className="agent-owner">담당자 · {owners[agent]}</p><p className="agent-contract">출력 형식 · {info.contract}</p><p className="agent-role">{info.role}</p></div>
        <div className="nodes">
          {nodeEvents.map((event, nodeIndex) => <details className="node" key={`${event.node}-${nodeIndex}`}><summary><small>노드 {String(nodeIndex + 1).padStart(2, "0")}</small><strong>{nodeLabels[event.node] ?? event.node}</strong><code>{event.node}</code><p>{event.message}</p></summary><div className="node-detail"><p><b>자연어 설명</b> {event.message}</p><p><b>정의된 값</b> {Object.entries(event.metrics).map(([key, value]) => `${key}=${String(value)}`).join(", ") || "추가 지표 없음"}</p><p><b>처리 상태</b> {stateLabels[event.state] ?? event.state}</p><pre>{JSON.stringify(event, null, 2)}</pre></div></details>)}
          {nodeEvents.length === 0 && <div className="node-placeholder"><span className={status === "running" ? "spinner" : "status-dot"} /><strong>{status === "running" ? "노드 준비 중" : stateLabels[status]}</strong><p>{status === "waiting" ? "앞 단계가 끝나면 실행됩니다." : "첫 처리 결과를 기다리는 중입니다."}</p></div>}
        </div>
      </div>;
    })}
  </section>;
}
```

`page.tsx`에서 옮긴 타입·상수·함수는 중복으로 남기지 않는다.

- [ ] **Step 5: 업데이트 입력·SSE·결과 컴포넌트를 구현한다**

`frontend/app/components/UpdateReview.tsx`를 `"use client"`로 작성한다. 입력 상태는 평면 object 하나로 두고, payload를 만들 때만 선택 유형의 `details` 객체를 만들어 불필요한 추상화를 피한다.

```tsx
"use client";

import { FormEvent, useState } from "react";
import { AgentEvent, AgentPipeline } from "./AgentPipeline";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const decisionLabels: Record<string, string> = {
  Go: "출시 가능",
  Revise: "일부 수정 후 출시",
  Test: "테스트 후 출시",
  Hold: "판정 보류",
};
const updateTypeLabels = { weapon_balance: "무기 밸런스", ui_ux: "UI·UX", system_rules: "시스템·규칙" };
const initial = {
  game: "PUBG: BATTLEGROUNDS",
  update_name: "Dragunov 확률 피해 제거",
  update_type: "weapon_balance",
  current_state: "기본 피해 58, 최대 피해 73의 확률형 구조",
  change_summary: "확률형 피해를 제거하고 피해를 60으로 고정",
  goal: "운에 따른 편차를 줄이고 전투 결과 예측 가능성을 높인다.",
  expected_benefits: "피해 결과 예측 가능성, 실력 중심 전투, 공정성 인식 개선",
  concerns: "반동·연사력을 포함한 실제 성능, 사용률 쏠림, 메타 변화",
  scope: "일반 매칭의 Dragunov 사용 경험",
  planned_on: "2026-08-20",
  cutoff_on: "2026-08-13",
  official_context_url: "https://pubg.com/en/news/6616",
  official_context: "PUBG Update 25.2의 확률형 피해 제거 공식 변경 맥락",
  target_weapon: "Dragunov", damage: "기본 58·최대 73 확률 → 60 고정", recoil: "현행 유지", rate_of_fire: "해당 없음", ammunition: "7.62mm", spawn_and_modes: "일반 매칭",
  changed_screen: "해당 없음", user_journey: "해당 없음", exposed_information: "해당 없음", possible_errors: "해당 없음",
  participation_conditions: "해당 없음", rewards: "해당 없음", restrictions: "해당 없음", exception_rules: "해당 없음", existing_user_impact: "해당 없음",
};

function details(form: typeof initial) {
  if (form.update_type === "weapon_balance") return { kind: "weapon_balance", target_weapon: form.target_weapon, damage: form.damage, recoil: form.recoil, rate_of_fire: form.rate_of_fire, ammunition: form.ammunition, spawn_and_modes: form.spawn_and_modes };
  if (form.update_type === "ui_ux") return { kind: "ui_ux", changed_screen: form.changed_screen, user_journey: form.user_journey, exposed_information: form.exposed_information, possible_errors: form.possible_errors };
  return { kind: "system_rules", participation_conditions: form.participation_conditions, rewards: form.rewards, restrictions: form.restrictions, exception_rules: form.exception_rules, existing_user_impact: form.existing_user_impact };
}
```

`UpdateReview` 내부에 다음 state를 둔다.

```tsx
const [form, setForm] = useState(initial);
const [sourceMode, setSourceMode] = useState("fixture");
const [steamAppId, setSteamAppId] = useState("578080");
const [useX, setUseX] = useState(false);
const [periodStart, setPeriodStart] = useState("2026-08-06T00:00");
const [periodEnd, setPeriodEnd] = useState("2026-08-13T00:00");
const [csvData, setCsvData] = useState("");
const [useClaude, setUseClaude] = useState(true);
const [result, setResult] = useState<UpdateRunResult | null>(null);
const [events, setEvents] = useState<AgentEvent[]>([]);
const [loading, setLoading] = useState(false);
const [error, setError] = useState("");
```

submit에서 payload를 아래 형태로 만들고, 기존 `page.tsx::submit`의 `fetch`/reader/frame parsing 25줄을 그대로 옮겨 `/api/update-runs/stream`을 호출한다.

```tsx
const payload = {
  game: form.game,
  update_name: form.update_name,
  update_type: form.update_type,
  current_state: form.current_state,
  change_summary: form.change_summary,
  goal: form.goal,
  expected_benefits: form.expected_benefits.split(",").map((value) => value.trim()).filter(Boolean),
  concerns: form.concerns.split(",").map((value) => value.trim()).filter(Boolean),
  scope: form.scope,
  planned_on: form.planned_on,
  cutoff_on: form.cutoff_on,
  official_context_url: form.official_context_url || null,
  official_context: form.official_context || null,
  details: details(form),
  source_mode: sourceMode,
  fixture_case: "dragunov_random_damage_removal",
  steam_app_id: sourceMode === "live" && steamAppId ? Number(steamAppId) : null,
  use_x: sourceMode === "live" ? useX : false,
  period_start: sourceMode === "live" ? new Date(periodStart).toISOString() : null,
  period_end: sourceMode === "live" ? new Date(periodEnd).toISOString() : null,
  imported_csv: sourceMode === "import" ? csvData : null,
  use_llm: useClaude,
};
const response = await fetch(`${API_URL}/api/update-runs/stream`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
  body: JSON.stringify(payload),
});
```

렌더링은 다음 영역을 이 순서로 둔다.

1. `업데이트 유형` 세 버튼: `aria-pressed`, 무기 밸런스/UI·UX/시스템·규칙. 선택 handler는 `const next = ...; setForm({...form, update_type: next}); if (next !== "weapon_balance" && sourceMode === "fixture") setSourceMode("live");`로 Dragunov fixture가 다른 유형 payload에 남지 않게 한다.
2. `업데이트 기본 정보` 카드: 공통 입력 11개.
3. 선택 유형의 필드만 렌더하는 `변경 세부 조건` 카드.
4. `자료 출처와 실행` 카드: 무기 밸런스에서만 Dragunov fixture를 노출하고, UI·UX/시스템·규칙은 Steam·X live 또는 CSV만 선택하게 하며 Claude toggle를 표시한다.
5. 실행 버튼 직전 고정 안내: `출시 전 예상이며 실제 이용자 반응이 아닙니다.`
6. loading 시 `<AgentPipeline events={events} active mode="update" />`.
7. 결과 배너: 네 개 한국어 판정 label, `executive_summary`, 실행 ID, Claude/fallback 상태.
8. `공식으로 확인된 변경 맥락` 카드: 응답의 `result.brief.official_context`와 `official_context_url`을 표시하고 합성 의견과 다른 배경색을 쓴다.
9. 별도 그리드: `예상 긍정 반응`, `예상 부정 반응`, `반응이 갈릴 이용자 유형`.
10. `언어권별 예상` 카드: `conclusion` 있는 언어만 감정 건수를 표시하고, `conclusion === null`이면 비율 대신 `hidden_reason`을 표시한다.
11. `출시 후 검증할 지표` 표: 지표명, 측정 방법, 성공 기준, 연결 위험.
12. `const actualAfter = result.brief.evidence.filter((item) => item.period === "after")`; `actualAfter.length > 0`일 때만 `업데이트 후 실제 반응` 영역 렌더.
13. 근거 카드 `<details>`: 비식별 요약, 기간, 감정, 태그, 출처 URL; 원문 제공을 약속하지 않음.
14. `<AgentPipeline events={result.events} mode="update" />`와 5개 artifact JSON `<details>`.

`UpdateRunResult` TypeScript type은 API 키와 동일한 `brief`, `feedback`, `evidence`, `impact`, `validated`, `events`, `fallback_used`, `analysis_incomplete`, `llm_provider`, `llm_requested`를 포함하고, 렌더링에서 사용하는 아래 세부 타입을 명시한다.

```tsx
type Evidence = { evidence_id: string; source: string; source_url: string; language: string; observed_at: string; period: string; sentiment: string; summary: string; mechanism_tags: string[]; relevance: number; synthetic: boolean };
type Risk = { risk_id: string; category: string; title: string; severity: string; evidence_ids: string[]; failure_path: string; confidence: number };
type Metric = { metric_id: string; title: string; measurement: string; success_condition: string; addresses_risk_ids: string[] };
type Impact = { impact_id: string; title: string; summary: string; affected_personas: string[]; evidence_ids: string[]; confidence: number };
type LanguageInsight = { language: string; conclusion: string | null; hidden_reason: string | null; sentiment_counts: Record<string, number>; evidence_ids: string[]; confidence: number };
type UpdateRunResult = {
  brief: { run_id: string; decision: string; executive_summary: string; official_context: string | null; official_context_url: string | null; expected_positive: Impact[]; expected_negative: Impact[]; split_conditions: Array<Record<string, unknown>>; persona_impacts: Array<Record<string, unknown>>; language_insights: LanguageInsight[]; top_risks: Risk[]; validation_metrics: Metric[]; evidence: Evidence[]; recommendations: Array<Record<string, unknown>> };
  feedback: { evidence: Evidence[] } & Record<string, unknown>;
  evidence: Record<string, unknown>;
  impact: Record<string, unknown>;
  validated: Record<string, unknown>;
  events: AgentEvent[];
  fallback_used: boolean;
  analysis_incomplete: boolean;
  llm_provider: string;
  llm_requested: boolean;
};
```

- [ ] **Step 6: 홈 화면에 접근 가능한 검토 대상 선택을 추가한다**

`frontend/app/page.tsx`에서 옮긴 `AgentPipeline` 관련 타입·상수·함수를 제거하고 import한다.

```tsx
import { AgentEvent, AgentPipeline } from "./components/AgentPipeline";
import { UpdateReview } from "./components/UpdateReview";
```

`Home`에 `const [reviewMode, setReviewMode] = useState<"event" | "update">("event");`를 추가하고, 제목 아래에 다음을 렌더한다.

```tsx
<div className="mode-switch" role="group" aria-label="검토 대상">
  <button type="button" aria-pressed={reviewMode === "event"} onClick={() => setReviewMode("event")}>
    <strong>이벤트 점검</strong><span>보상·참여·이용 조건을 점검합니다.</span>
  </button>
  <button type="button" aria-pressed={reviewMode === "update"} onClick={() => setReviewMode("update")}>
    <strong>업데이트 점검</strong><span>변경안의 예상 반응과 출시 조건을 점검합니다.</span>
  </button>
</div>
{reviewMode === "update" ? <UpdateReview /> : <>{/* existing event form/loading/result unchanged */}</>}
```

기존 파이프라인 호출 두 곳에 `mode="event"`를 추가한다. 이벤트 form·payload·결과 JSX 본문은 문구를 바꾸지 않는다.

- [ ] **Step 7: 현재 Linear 토큰을 재사용해 모드·결과 레이아웃을 추가한다**

`frontend/app/globals.css`에 새 컬러 토큰 없이 현재 `--surface`, `--border`, `--accent`, `--muted`를 재사용한다.

```css
.mode-switch,.update-types,.reaction-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:18px 0; }
.mode-switch button,.update-type { border:1px solid var(--border); border-radius:10px; background:var(--surface); color:var(--text); padding:16px; text-align:left; cursor:pointer; }
.mode-switch button[aria-pressed="true"],.update-type[aria-pressed="true"] { border-color:var(--accent); box-shadow:0 0 0 3px #5e6ad21f; background:#fafaff; }
.mode-switch strong,.mode-switch span { display:block; }.mode-switch span { color:var(--muted); font-size:12px; margin-top:6px; }
.update-types { grid-template-columns:repeat(3,minmax(0,1fr)); }
.prelaunch-notice { border:1px solid #c7c9ed; border-radius:8px; background:#fafaff; color:#4b568c; padding:13px 14px; font-size:13px; line-height:1.5; }
.reaction-card { border:1px solid var(--border); border-radius:10px; background:var(--surface); padding:16px; }
.reaction-card.positive { border-top:3px solid #20865a; }.reaction-card.negative { border-top:3px solid #b42318; }
.metric-table { width:100%; border-collapse:collapse; font-size:13px; }.metric-table th,.metric-table td { border-bottom:1px solid var(--border); padding:12px; text-align:left; vertical-align:top; }.metric-table th { color:var(--muted); background:#fafafa; }
.evidence-list details { border:1px solid var(--border); border-radius:8px; margin-top:8px; padding:12px; }.evidence-meta { color:var(--muted); font-size:12px; }
@media (max-width:800px) { .mode-switch,.update-types,.reaction-grid { grid-template-columns:1fr; }.metric-table { display:block; overflow-x:auto; } }
```

- [ ] **Step 8: 정적 계약·TypeScript build·기존 API 테스트를 확인한다**

Run:

```bash
uv run pytest tests/test_frontend_update_contract.py tests/test_update_api.py tests/test_api.py -v
cd frontend && npm run build
```

Expected: pytest PASS; Next.js production build exits 0 with no TypeScript error.

- [ ] **Step 9: Task 7을 커밋한다**

```bash
git add frontend/app/components/AgentPipeline.tsx frontend/app/components/UpdateReview.tsx frontend/app/page.tsx frontend/app/globals.css tests/test_frontend_update_contract.py
git commit -m "feat: add update review web experience"
```

---

### Task 8: 업데이트 성공 게이트·문서·전체 회귀 검증

**Files:**
- Create: `evaluation/verify_update_success.py`
- Create: `tests/test_update_success_gate.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `load_dragunov_brief`, `UpdateReviewOrchestrator`, `UpdatePipelineResult`
- Produces: `verify() -> UpdateSuccessReport`
- Produces: runnable command `uv run python -m evaluation.verify_update_success`

- [ ] **Step 1: 업데이트 성공 게이트의 실패 테스트를 작성한다**

`tests/test_update_success_gate.py`를 작성한다.

```python
import evaluation.verify_update_success as update_gate
from update_review.contracts import UpdateDecision


def test_update_success_gate_passes():
    report = update_gate.verify()
    assert report.passed
    assert report.decision is UpdateDecision.TEST
    assert report.evidence_count == 75
    assert report.synthetic_only
    assert report.comparable_reference_only
    assert report.actual_after_count == 0
    assert report.reproducible_core
    assert report.semantic_links_valid
    assert report.event_sequence_valid
    assert len(report.input_snapshot_hash) == 64


def test_update_success_gate_rejects_actual_after_in_fixture(monkeypatch):
    original = update_gate.UpdateReviewOrchestrator

    class LeakingOrchestrator(original):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            changed = result.brief.evidence[0].model_copy(update={"period": "after"})
            result.brief = result.brief.model_copy(update={"evidence": [changed, *result.brief.evidence[1:]]})
            return result

    monkeypatch.setattr(update_gate, "UpdateReviewOrchestrator", LeakingOrchestrator)
    report = update_gate.verify()
    assert report.actual_after_count == 1
    assert not report.comparable_reference_only
    assert not report.passed
```

- [ ] **Step 2: 성공 게이트 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_update_success_gate.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'evaluation.verify_update_success'`.

- [ ] **Step 3: Dragunov 재현성·참조·노드 순서 성공 게이트를 구현한다**

`evaluation/verify_update_success.py`를 다음과 같이 작성한다. 자연어 문장은 달라질 수 있으므로 `core_outcome`에서 제외하고, 정책·ID·해시만 비교한다.

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from execution import AGENT_ORDER, ExecutionState
from update_review.contracts import EvidencePeriod, UpdateDecision
from update_review.fixtures import load_dragunov_brief
from update_review.orchestrator import UpdatePipelineResult, UpdateReviewOrchestrator


class UpdateSuccessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: UpdateDecision
    evidence_count: int
    synthetic_only: bool
    comparable_reference_only: bool
    actual_after_count: int
    reproducible_core: bool
    semantic_links_valid: bool
    event_sequence_valid: bool
    input_snapshot_hash: str
    passed: bool


def core_outcome(result: UpdatePipelineResult) -> tuple:
    return (
        result.brief.decision,
        tuple((item.risk_id, item.category, item.severity, tuple(sorted(item.evidence_ids))) for item in result.brief.top_risks),
        tuple((item.metric_id, tuple(sorted(item.addresses_risk_ids))) for item in result.brief.validation_metrics),
        tuple(sorted(item.evidence_id for item in result.brief.evidence)),
        result.brief.policy_version,
        result.brief.input_snapshot_hash,
    )


def verify() -> UpdateSuccessReport:
    result = UpdateReviewOrchestrator().run(load_dragunov_brief("update-success-gate"))
    repeat = UpdateReviewOrchestrator().run(load_dragunov_brief("update-success-gate-repeat"))
    evidence_ids = {item.evidence_id for item in result.brief.evidence}
    risk_ids = {item.risk_id for item in result.brief.top_risks}
    semantic_links_valid = all(set(item.evidence_ids) <= evidence_ids for item in result.brief.top_risks) and all(set(item.addresses_risk_ids) <= risk_ids for item in result.brief.validation_metrics)
    complete_order = [item.agent for item in result.events if item.node == "agent" and item.state == ExecutionState.COMPLETE]
    event_sequence_valid = complete_order[:4] == list(AGENT_ORDER)
    actual_after_count = sum(item.period is EvidencePeriod.AFTER for item in result.brief.evidence)
    synthetic_only = bool(result.brief.evidence) and all(item.synthetic for item in result.brief.evidence)
    comparable_only = bool(result.brief.evidence) and all(item.period is EvidencePeriod.COMPARABLE_REFERENCE for item in result.brief.evidence)
    reproducible_core = core_outcome(result) == core_outcome(repeat)
    passed = all((
        result.brief.decision is UpdateDecision.TEST,
        len(result.brief.evidence) == 75,
        synthetic_only,
        comparable_only,
        actual_after_count == 0,
        reproducible_core,
        semantic_links_valid,
        event_sequence_valid,
        len(result.brief.input_snapshot_hash) == 64,
    ))
    return UpdateSuccessReport(
        decision=result.brief.decision,
        evidence_count=len(result.brief.evidence),
        synthetic_only=synthetic_only,
        comparable_reference_only=comparable_only,
        actual_after_count=actual_after_count,
        reproducible_core=reproducible_core,
        semantic_links_valid=semantic_links_valid,
        event_sequence_valid=event_sequence_valid,
        input_snapshot_hash=result.brief.input_snapshot_hash,
        passed=passed,
    )


if __name__ == "__main__":
    print(verify().model_dump_json(indent=2))
```

- [ ] **Step 4: 업데이트 성공 게이트 테스트와 CLI 출력을 확인한다**

Run:

```bash
uv run pytest tests/test_update_success_gate.py -v
uv run python -m evaluation.verify_update_success
```

Expected: pytest PASS; JSON contains `"decision": "Test"`, `"actual_after_count": 0`, `"passed": true`.

- [ ] **Step 5: README에 업데이트 점검의 의미·실행·안전 경계를 추가한다**

`README.md`의 `게임체인저 서비스 실행` 설명 아래에 다음을 추가한다.

```markdown
### 출시 전 업데이트 점검

웹 화면 상단에서 `업데이트 점검`을 선택하면 무기 밸런스,
UI·UX, 시스템·규칙 변경안의 출시 전 예상을 확인할 수 있습니다.
기본 사례는 Dragunov의 확률형 피해를 고정 피해 60으로 바꾸는
변경안입니다.

저장 사례의 75개 의견은 [PUBG Update 25.2 패치 노트](https://pubg.com/en/news/6616)와
변경 조건을 바탕으로 만든 비식별 합성 관점입니다. 실제 사용자 여론이나
업데이트 후 실제 반응으로 해석하지 않습니다. 출시 전 결과는 예상이며,
서비스는 출시 후 확인할 지표를 별도로 제시합니다.

```bash
uv run python -m evaluation.verify_update_success
```

Steam·X 실시간 경로는 사용자가 선택한 때만 호출합니다. 연결 실패·표본
부족 시 저장 사례로 자동 대체하지 않고 `판정 보류`로 표시합니다. 원문과
사용자 식별자는 저장하지 않습니다.
```

- [ ] **Step 6: 전체 Python·성공 게이트·Next build를 최종 검증한다**

Run:

```bash
uv sync --extra dev --locked
uv run pytest
uv run python -m evaluation.verify_success
uv run python -m evaluation.verify_update_success
uv run python -c "from backend.app.main import app; assert app.title == 'Game Changer API'"
cd frontend && npm run build
```

Expected:

- `uv run pytest`: all existing 85 tests plus the new update-review tests PASS.
- `evaluation.verify_success`: existing event report contains `"passed": true`.
- `evaluation.verify_update_success`: update report contains `"decision": "Test"`, `"actual_after_count": 0`, `"passed": true`.
- FastAPI import exits 0.
- Next.js production build exits 0 with no hydration or TypeScript error.

- [ ] **Step 7: 비밀·원문·실행 로그가 Git 대상에 없는지 확인한다**

Run:

```bash
git status --short
git ls-files backend/.env .streamlit/secrets.toml .data
rg -n "ANTHROPIC_API_KEY=|X_BEARER_TOKEN=|raw_text|username|account_id" --glob '!docs/superpowers/**' --glob '!tests/**' .
```

Expected: `backend/.env`, `.streamlit/secrets.toml`, `.data/` are not tracked; no actual key value or persisted raw/identity field is found. Schema/importer forbidden-column names may appear only in source validation code.

- [ ] **Step 8: Task 8을 커밋한다**

```bash
git add evaluation/verify_update_success.py tests/test_update_success_gate.py README.md
git commit -m "docs: add update review acceptance gate"
```

---
