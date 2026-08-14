import os
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    require_prelaunch_narrative,
)
from contracts import ArtifactStatus, ErrorCode, Language, PersonaKind, Producer
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
    "fairness_regression": "공정성 인식 저하 가능성",
    "validation_needed": "실제 지표 확인 필요",
    "information_clarity": "변경 정보 이해 가능성",
    "flow_disruption": "이용 동선 변화 부담",
    "rule_exception": "예외 규칙 처리 부담",
    "learning_burden": "새 규칙 학습 부담",
}

PERSONA_TAGS = {
    PersonaKind.TIME_CONSTRAINED: {
        "information_clarity",
        "flow_disruption",
        "learning_burden",
    },
    PersonaKind.VALUE_SEEKING: {"predictability", "skill_fairness", "rule_exception"},
    PersonaKind.COLLECTOR: {
        "information_clarity",
        "rule_exception",
        "learning_burden",
    },
    PersonaKind.CORE_GAMEPLAY: {
        "predictability",
        "skill_fairness",
        "balance_regression",
        "fairness_regression",
        "validation_needed",
    },
}


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

    def __init__(
        self,
        use_llm: bool = False,
        client=None,
        budget: ClaudeBudget | None = None,
    ) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget

    def run(
        self,
        bundle: UpdateFeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateEvidencePack:
        base = self.run_deterministic(bundle, on_event=on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify(
            "claude_narrative",
            "Claude Sonnet이 고정된 근거 범위에서 반응 설명을 보강합니다.",
            {"provider": "claude"},
        )
        narrative = parse_claude_structured(
            model=os.getenv("CLAUDE_UPDATE_EVIDENCE_MODEL", "claude-sonnet-4-6"),
            prompt_path=self.prompt_path,
            output_type=EvidenceNarrative,
            payload=base,
            client=self.client,
            budget=self.budget,
        )
        require_prelaunch_narrative(
            [
                text
                for item in narrative.signals
                for text in (item.title, item.summary)
            ],
            prediction_fields=[item.summary for item in narrative.signals],
        )
        signals = {
            item.signal_id: item
            for item in [
                *base.positive_signals,
                *base.negative_signals,
                *base.split_conditions,
            ]
        }
        for proposal in narrative.signals:
            official = signals.get(proposal.signal_id)
            if official is None or not set(proposal.evidence_ids) <= set(
                official.evidence_ids
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude narrative references unknown signal evidence",
                )
            signals[proposal.signal_id] = official.model_copy(
                update={"title": proposal.title, "summary": proposal.summary}
            )
        notify(
            "claude_output_checked",
            "Claude 설명의 신호·근거 ID를 확인했습니다.",
            {"provider": "claude"},
        )
        return base.model_copy(
            update={
                "positive_signals": [
                    signals[item.signal_id] for item in base.positive_signals
                ],
                "negative_signals": [
                    signals[item.signal_id] for item in base.negative_signals
                ],
                "split_conditions": [
                    signals[item.signal_id] for item in base.split_conditions
                ],
            }
        )

    def run_deterministic(
        self,
        bundle: UpdateFeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateEvidencePack:
        notify = on_event or (lambda _node, _message, _metrics: None)
        ordered_evidence = sorted(
            bundle.evidence,
            key=lambda item: (item.source.value, item.source_id, item.evidence_id),
        )
        deduplicated = sorted(
            {
                (item.source, item.source_id): item
                for item in ordered_evidence
            }.values(),
            key=lambda item: (item.source.value, item.source_id, item.evidence_id),
        )
        notify("deduplicated", "중복 비식별 근거를 하나로 합쳤습니다.", {"evidence": len(deduplicated)})

        def signals(sentiment: Sentiment) -> list[ReactionSignal]:
            rows = []
            for tag, title in SIGNAL_TITLES.items():
                items = [
                    item
                    for item in deduplicated
                    if item.sentiment is sentiment and tag in item.mechanism_tags
                ]
                if items:
                    rows.append(
                        ReactionSignal(
                            signal_id=f"{sentiment.value}-{tag}",
                            title=title,
                            summary=(
                                f"{len(items)}개 비식별 근거에서 {title} 반응이 "
                                "나타날 가능성이 있음."
                            ),
                            sentiment=sentiment,
                            evidence_ids=[item.evidence_id for item in items],
                            confidence=sum(item.relevance for item in items) / len(items),
                        )
                    )
            return rows

        positive = signals(Sentiment.POSITIVE)
        negative = signals(Sentiment.NEGATIVE)
        mixed = [SplitCondition(**item.model_dump()) for item in signals(Sentiment.MIXED)]
        notify(
            "signals_grouped",
            "긍정·부정·혼합 반응 신호를 변경 요소별로 묶었습니다.",
            {"positive": len(positive), "negative": len(negative), "mixed": len(mixed)},
        )
        signal_ids = {item.signal_id for item in [*positive, *negative, *mixed]}
        personas = []
        for persona, tags in PERSONA_TAGS.items():
            items = [item for item in deduplicated if tags.intersection(item.mechanism_tags)]
            if not items:
                continue
            positive_ids = [
                item.signal_id
                for item in positive
                if item.signal_id.split("-", 1)[1] in tags
            ]
            negative_ids = [
                item.signal_id
                for item in negative
                if item.signal_id.split("-", 1)[1] in tags
            ]
            linked = items[:15]
            personas.append(
                UpdatePersonaImpact(
                    persona=persona,
                    expected_reaction="연결된 긍정·부정 신호에 따라 반응이 갈릴 가능성이 있음.",
                    positive_signal_ids=[value for value in positive_ids if value in signal_ids],
                    negative_signal_ids=[value for value in negative_ids if value in signal_ids],
                    split_signal_ids=[
                        item.signal_id
                        for item in mixed
                        if item.signal_id.split("-", 1)[1] in tags
                    ],
                    evidence_ids=[item.evidence_id for item in linked],
                    confidence=sum(item.relevance for item in linked) / len(linked),
                )
            )
        notify("personas_linked", "이용자 유형별로 다르게 나타날 신호와 근거를 연결했습니다.", {"personas": len(personas)})
        samples = {item.language: item for item in bundle.samples}
        language_insights = []
        for language in Language:
            items = [item for item in deduplicated if item.language is language]
            sample = samples.get(language)
            counts = Counter(item.sentiment for item in items)
            sufficient = bool(sample and sample.sufficient)
            language_insights.append(
                UpdateLanguageInsight(
                    language=language,
                    conclusion=(
                        "언어권별 긍정·부정·혼합 반응이 갈릴 가능성이 있음."
                        if sufficient
                        else None
                    ),
                    hidden_reason=(
                        None if sufficient else "일반 100건·관련 15건 최소 표본 미달"
                    ),
                    sentiment_counts={sentiment: counts[sentiment] for sentiment in Sentiment},
                    evidence_ids=[item.evidence_id for item in items],
                    confidence=(
                        sum(item.relevance for item in items) / len(items)
                        if sufficient and items
                        else 0
                    ),
                )
            )
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
