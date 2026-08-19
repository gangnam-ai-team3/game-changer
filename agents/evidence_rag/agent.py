from __future__ import annotations

import os
from collections.abc import Callable
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.evidence_rag.retrieval import embedding_rank
from agents.structured import ClaudeBudget, StructuredModelError, parse_claude_structured, parse_structured, require_native_business_korean
from contracts import (
    ArtifactStatus,
    ErrorCode,
    EvidencePack,
    ExploratoryInsight,
    FeedbackBundle,
    Language,
    LanguageInsight,
    MechanismIssue,
    Persona,
    PersonaKind,
    PipelineError,
    Producer,
    RiskCategory,
)

ISSUE_TITLES = {
    RiskCategory.DOUBLE_GACHA: "2단계 확률 구조",
    RiskCategory.FRAGMENTED_FLOW: "분절된 구매·제작 흐름",
    RiskCategory.OPAQUE_PROGRESS: "불명확한 확정 진행 경로",
    RiskCategory.RANDOM_BONUS: "확률형 보너스 편차",
    RiskCategory.EXPIRING_CURRENCY: "이벤트 재화 만료 손실",
}
TAG_TITLES = {
    "fixed_reward": "정해진 보상 교환 구조",
    "weekly_reset": "주간 초기화 시점",
}


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


class EvidenceRagAgent:
    model = os.getenv("OPENAI_RAG_MODEL", "gpt-5.6-luna")
    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    prompt_path = Path(__file__).with_name("prompt.md")

    def __init__(self, use_llm: bool = False, client=None, provider: str | None = None, budget: ClaudeBudget | None = None) -> None:
        self.use_llm = use_llm
        self.client = client
        self.provider = provider or ("openai" if client is not None else os.getenv("LLM_PROVIDER", "claude"))
        self.budget = budget

    def run(
        self,
        bundle: FeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> EvidencePack:
        base = self.run_deterministic(bundle, on_event=on_event)
        if self.use_llm:
            if self.provider == "claude":
                notify = on_event or (lambda _node, _message, _metrics: None)
                notify("claude_narrative", "Claude가 근거 범위 안의 설명을 생성합니다.", {"provider": "claude"})
                narrative = parse_claude_structured(
                    model=os.getenv("CLAUDE_RAG_MODEL", "claude-sonnet-4-6"),
                    prompt_path=self.prompt_path,
                    output_type=EvidenceNarrative,
                    payload=base,
                    client=self.client,
                    budget=self.budget,
                )
                require_native_business_korean(
                    [
                        text
                        for issue in narrative.issues
                        for text in (issue.title, issue.summary)
                    ]
                    + [
                        text
                        for persona in narrative.personas
                        for text in (
                            *persona.motivations,
                            *persona.churn_triggers,
                            *persona.play_constraints,
                            persona.payment_sensitivity,
                        )
                    ]
                    + [
                        text
                        for insight in narrative.exploratory_insights
                        for text in (insight.title, insight.summary)
                    ]
                )
                notify("claude_output_checked", "Claude 설명의 근거 ID와 형식을 확인했습니다.", {"provider": "claude"})
            else:
                client = self.client
                if client is None:
                    if not os.getenv("OPENAI_API_KEY"):
                        raise StructuredModelError(ErrorCode.AUTH_FAILED, "OPENAI_API_KEY is missing")
                    from openai import OpenAI

                    client = OpenAI()
                ranked = embedding_rank(
                    "event reward probability guarantee progression payment expiration fairness",
                    bundle.evidence,
                    client=client,
                    model=self.embedding_model,
                )
                narrative = parse_structured(
                    model=self.model,
                    prompt_path=self.prompt_path,
                    output_type=EvidenceNarrative,
                    payload=base.model_copy(update={"evidence": ranked}),
                    client=client,
                )
            return self._merge_narrative(base, narrative)
        return base

    def run_deterministic(
        self,
        bundle: FeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> EvidencePack:
        return self._deterministic(bundle, on_event=on_event)

    def _merge_narrative(
        self, base: EvidencePack, narrative: EvidenceNarrative
    ) -> EvidencePack:
        issues_by_category = {
            issue.category: (index, issue) for index, issue in enumerate(base.issues)
        }
        personas_by_kind = {
            persona.kind: (index, persona) for index, persona in enumerate(base.personas)
        }
        evidence_ids = {item.evidence_id for item in base.evidence}
        issues = list(base.issues)
        personas = list(base.personas)

        for proposal in narrative.issues:
            official = issues_by_category.get(proposal.category)
            if official is None or not set(proposal.evidence_ids) <= set(official[1].evidence_ids):
                self._invalid_narrative_reference()
            index, issue = official
            issues[index] = issue.model_copy(
                update={"title": proposal.title, "summary": proposal.summary}
            )

        for proposal in narrative.personas:
            official = personas_by_kind.get(proposal.kind)
            if official is None or not set(proposal.evidence_ids) <= set(official[1].evidence_ids):
                self._invalid_narrative_reference()
            index, persona = official
            personas[index] = persona.model_copy(
                update={
                    "motivations": proposal.motivations,
                    "churn_triggers": proposal.churn_triggers,
                    "play_constraints": proposal.play_constraints,
                    "payment_sensitivity": proposal.payment_sensitivity,
                }
            )

        for insight in narrative.exploratory_insights:
            if not set(insight.evidence_ids) <= evidence_ids:
                self._invalid_narrative_reference()

        return base.model_copy(
            update={
                "issues": issues,
                "personas": personas,
                "exploratory_insights": [
                    *base.exploratory_insights,
                    *narrative.exploratory_insights,
                ],
            }
        )

    @staticmethod
    def _invalid_narrative_reference() -> None:
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID, "LLM narrative references unknown evidence"
        )

    def _deterministic(
        self,
        bundle: FeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> EvidencePack:
        notify = on_event or (lambda _node, _message, _metrics: None)
        deduplicated = list(
            {(item.source, item.source_id): item for item in bundle.evidence}.values()
        )
        notify(
            "deduplicated",
            "중복 근거를 제거했습니다.",
            {"evidence": len(deduplicated)},
        )
        issues: list[MechanismIssue] = []
        for category, title in ISSUE_TITLES.items():
            matching = [item for item in deduplicated if category.value in item.mechanism_tags]
            if matching:
                issues.append(
                    MechanismIssue(
                        issue_id=f"issue-{category.value}",
                        category=category,
                        title=title,
                        summary=f"{len(matching)}개 비식별 근거에서 반복 확인됨.",
                        evidence_ids=[item.evidence_id for item in matching],
                        confidence=sum(item.relevance for item in matching) / len(matching),
                    )
                )

        notify(
            "issues_grouped",
            "메커니즘별 근거를 묶었습니다.",
            {"issues": len(issues)},
        )

        samples = {sample.language: sample for sample in bundle.samples}
        language_insights: list[LanguageInsight] = []
        for language in Language:
            items = [item for item in deduplicated if item.language == language]
            sample = samples.get(language)
            if sample and sample.sufficient:
                tag_labels = {category.value: title for category, title in ISSUE_TITLES.items()} | TAG_TITLES
                top_tags = [
                    tag_labels.get(tag, tag)
                    for tag, _ in Counter(tag for item in items for tag in item.mechanism_tags).most_common(3)
                ]
                language_insights.append(
                    LanguageInsight(
                        language=language,
                        conclusion=f"해당 언어권에서는 {', '.join(top_tags)}이 주요 우려로 예상됩니다.",
                        evidence_ids=[item.evidence_id for item in items],
                        confidence=_average_relevance(items),
                    )
                )
            else:
                language_insights.append(
                    LanguageInsight(
                        language=language,
                        conclusion=None,
                        hidden_reason="일반 의견 100건과 메커니즘 의견 15건의 최소 표본 기준에 미달했습니다.",
                        evidence_ids=[item.evidence_id for item in items],
                        confidence=0,
                    )
                )

        notify(
            "language_gate_checked",
            "언어권별 표본 기준을 확인했습니다.",
            {"visible": sum(item.conclusion is not None for item in language_insights)},
        )
        errors = list(bundle.errors)
        personas = self._personas(deduplicated, language_insights)
        if len(deduplicated) < 15:
            errors.append(
                PipelineError(
                    code=ErrorCode.INSUFFICIENT_EVIDENCE,
                    message="이용자 유형을 만들려면 비식별 근거가 최소 15건 필요합니다.",
                )
            )

        notify(
            "personas_built",
            "근거 기반 페르소나를 만들었습니다.",
            {"personas": len(personas)},
        )
        result = EvidencePack(
            run_id=bundle.run_id,
            status=ArtifactStatus.PARTIAL if errors else ArtifactStatus.COMPLETE,
            producer=Producer.EVIDENCE_RAG,
            input_refs=[bundle.ref],
            errors=errors,
            issues=issues,
            language_insights=language_insights,
            evidence=deduplicated,
            personas=personas,
        )
        notify(
            "pack_ready",
            "EvidencePack 계약을 통과했습니다.",
            {"evidence": len(deduplicated)},
        )
        return result

    def _personas(self, evidence, insights: list[LanguageInsight]) -> list[Persona]:
        if len(evidence) < 15:
            return []
        language_differences = {
            insight.language: (
                insight.conclusion or "표본 기준 미달로 언어권 고유 차이를 판단하지 않음"
            )
            for insight in insights
        }
        specs = (
            (
                PersonaKind.TIME_CONSTRAINED,
                "시간 제약형 캐주얼·복귀 유저",
                ["짧은 시간 안에 명확한 진척"],
                ["복잡한 동선", "재화 만료"],
                ["일일 플레이 시간이 짧거나 불규칙함"],
                "시간 절약 가치가 분명할 때만 지불",
                {"fragmented_flow", "opaque_progress", "expiring_currency"},
            ),
            (
                PersonaKind.VALUE_SEEKING,
                "보상 효율형 무·소과금 유저",
                ["예측 가능한 보상 효율"],
                ["중첩 확률", "지출 대비 결과 편차"],
                ["무료·저가 경로를 우선함"],
                "확정 가치와 상한에 매우 민감",
                {"double_gacha", "opaque_progress", "random_bonus"},
            ),
            (
                PersonaKind.COLLECTOR,
                "수집·고관여 소비자",
                ["원하는 스킨의 완성 가능한 수집 경로"],
                ["천장 부재", "분절된 제작 흐름"],
                ["목표 보상에는 반복 참여 가능"],
                "목표 획득 경로가 투명하면 지불 의향이 높음",
                {"double_gacha", "fragmented_flow", "opaque_progress", "random_bonus"},
            ),
            (
                PersonaKind.CORE_GAMEPLAY,
                "전투 경험 우선 코어 유저",
                ["전투 흐름을 방해하지 않는 보상"],
                ["과도한 상점 동선", "반복 미션 압박"],
                ["전투 플레이가 주 목적"],
                "전투와 무관한 확률 소비에는 민감",
                {"fragmented_flow", "expiring_currency"},
            ),
        )
        personas: list[Persona] = []
        for kind, label, motivations, churn, constraints, sensitivity, tags in specs:
            selected = [item for item in evidence if tags.intersection(item.mechanism_tags)]
            selected_ids = [item.evidence_id for item in selected]
            if len(selected_ids) < 15:
                selected_ids.extend(
                    item.evidence_id for item in evidence if item.evidence_id not in selected_ids
                )
            personas.append(
                Persona(
                    kind=kind,
                    label=label,
                    motivations=motivations,
                    churn_triggers=churn,
                    play_constraints=constraints,
                    payment_sensitivity=sensitivity,
                    language_differences=language_differences,
                    evidence_ids=selected_ids[:15],
                    confidence=_average_relevance(selected[:15] or evidence[:15]),
                )
            )
        return personas


def _average_relevance(items) -> float:
    return sum(item.relevance for item in items) / len(items) if items else 0
