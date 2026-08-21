import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agents.structured import (
    ClaudeBudget,
    StructuredModelError,
    parse_claude_structured,
    require_native_business_korean,
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
    "predictability": "같은 조건에서 결과를 미리 가늠할 수 있는지",
    "skill_fairness": "운보다 실력이 결과에 더 크게 반영되는지",
    "balance_regression": "고정 피해가 실제 전투에서 너무 강하거나 약하지 않은지",
    "fairness_regression": "특정 이용자에게만 유리한 결과가 생기는지",
    "validation_needed": "설명과 실제 성능이 일치하는지",
    "information_clarity": "무엇이 달라지는지 바로 이해할 수 있는지",
    "flow_disruption": "기존 이용 과정이 더 복잡해지는지",
    "rule_exception": "예외 상황에서도 같은 규칙이 적용되는지",
    "learning_burden": "새 규칙을 다시 익혀야 하는지",
}

SIGNAL_REACTION_COPY = {
    "predictability": {
        Sentiment.POSITIVE: (
            "같은 조건이라면 결과가 어떻게 나올지 미리 가늠할 수 있어 더 납득됩니다.",
            "변경된 기능을 직접 사용해 보거나 이용 빈도를 늘릴 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "수치가 바뀌어도 결과를 여전히 가늠하기 어렵다면 바뀐 의미를 느끼기 어려울 것 같습니다.",
            "변경 효과를 확인할 때까지 기존 방식을 유지하거나 추가 설명을 요구할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "결과를 가늠하기 쉬워지는 점은 좋지만 실제 상황에서도 같은지는 직접 확인하고 싶습니다.",
            "변경 전후 결과를 비교한 뒤 계속 이용할지 판단할 가능성이 있습니다.",
        ),
    },
    "skill_fairness": {
        Sentiment.POSITIVE: (
            "운보다 실력으로 승부가 갈린다는 느낌이 들어 결과를 받아들이기 쉽습니다.",
            "경쟁 상황에서 변경 사항을 직접 시험하고 긍정적으로 평가할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "특정 수치나 조건이 결과를 더 크게 좌우한다면 실력 중심 변경이라고 느끼기 어렵습니다.",
            "불리하다고 느끼는 상황을 공유하거나 추가 조정을 요청할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "운 요소가 줄어드는 방향은 반갑지만 숙련도 차이가 제대로 반영되는지는 더 봐야겠습니다.",
            "여러 숙련 구간의 결과를 확인할 때까지 평가를 유보할 가능성이 있습니다.",
        ),
    },
    "balance_regression": {
        Sentiment.POSITIVE: (
            "성능 편차가 줄어들면 다른 선택지와 비교하기 쉬워질 것 같습니다.",
            "기존 선택지와 성능을 비교하며 변경안을 시험할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "피해가 고정돼도 반동과 연사력까지 고려하면 이 무기만 지나치게 강하거나 약해질까 걱정됩니다.",
            "몇 차례 사용한 뒤 다른 무기로 돌아가거나 추가 조정을 요청할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "성능이 안정되는 점은 좋지만 무기 선택이 한쪽으로 쏠리지 않을지는 확인이 필요합니다.",
            "다른 무기와 비교한 수치가 공개될 때까지 평가를 유보할 가능성이 있습니다.",
        ),
    },
    "fairness_regression": {
        Sentiment.POSITIVE: (
            "같은 조건에는 같은 결과가 적용된다면 더 공정하다고 느낄 것 같습니다.",
            "변경안을 신뢰하고 계속 이용할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "특정 이용자에게만 유리한 결과가 생긴다면 공정한 변경이라고 느끼기 어렵습니다.",
            "불리한 조건을 피하거나 공정성 문제를 제기할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "전체 방향은 공정해 보여도 이용 조건에 따라 유불리가 달라지는지는 더 확인하고 싶습니다.",
            "조건별 결과가 공개될 때까지 판단을 미룰 가능성이 있습니다.",
        ),
    },
    "validation_needed": {
        Sentiment.POSITIVE: (
            "테스트 수치가 함께 공개되면 변경 이유를 믿고 시도해 볼 수 있을 것 같습니다.",
            "검증 결과를 확인한 뒤 변경된 기능을 이용할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "좋아졌다는 설명만으로는 믿기 어렵습니다. 테스트 수치와 실제 사용 경험을 확인한 뒤 판단하고 싶습니다.",
            "검증 결과가 공개될 때까지 이용이나 구매 결정을 미룰 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "변경 방향은 이해하지만 수치가 공개되기 전에는 실제로 좋아졌다고 판단하기 어렵습니다.",
            "테스트 결과를 확인한 뒤 찬반 의견을 정할 가능성이 있습니다.",
        ),
    },
    "information_clarity": {
        Sentiment.POSITIVE: (
            "한눈에 무엇이 바뀌었는지 알 수 있어 바로 이용할 수 있을 것 같습니다.",
            "별도 안내를 찾지 않고 변경된 기능을 시도할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "무엇이 달라졌고 내 이용 방식에 어떤 영향을 주는지 알 수 없다면 혼란스러울 것 같습니다.",
            "안내를 다시 찾거나 기능 이용을 미룰 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "큰 변화는 알겠지만 세부 조건까지 바로 이해하기는 어려울 것 같습니다.",
            "추가 안내를 확인한 뒤 이용 여부를 결정할 가능성이 있습니다.",
        ),
    },
    "flow_disruption": {
        Sentiment.POSITIVE: (
            "기존 이용 과정 안에서 바로 끝낼 수 있다면 부담 없이 사용할 수 있을 것 같습니다.",
            "현재 이용 습관을 유지하면서 새 기능을 사용할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "하던 일을 끝내려면 화면을 더 많이 오가야 한다면 번거로워서 이용을 줄일 것 같습니다.",
            "중간에 이탈하거나 기존 방식으로 돌아갈 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "새 기능은 필요하지만 이용 단계가 늘어난다면 자주 쓰지는 않을 것 같습니다.",
            "필요할 때만 제한적으로 이용할 가능성이 있습니다.",
        ),
    },
    "rule_exception": {
        Sentiment.POSITIVE: (
            "예외 상황까지 같은 기준이 적용된다면 결과를 믿을 수 있을 것 같습니다.",
            "경계 상황을 걱정하지 않고 기능을 계속 이용할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "예외 상황마다 결과가 달라진다면 규칙을 믿기 어렵고 손해를 봤다고 느낄 수 있습니다.",
            "문제가 생길 수 있는 조건을 피하거나 문의를 제기할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "기본 규칙은 이해되지만 예외 상황에서도 같은 결과가 나오는지는 확인하고 싶습니다.",
            "예외 조건을 확인한 뒤 이용 범위를 정할 가능성이 있습니다.",
        ),
    },
    "learning_burden": {
        Sentiment.POSITIVE: (
            "기존에 알던 방식과 크게 다르지 않다면 어렵지 않게 적응할 수 있을 것 같습니다.",
            "짧은 안내만 확인하고 새 방식을 이용할 가능성이 있습니다.",
        ),
        Sentiment.NEGATIVE: (
            "새 규칙을 다시 외워야 한다면 적응하기 전까지 이용을 미룰 것 같습니다.",
            "학습 부담이 적은 기존 기능을 계속 이용할 가능성이 있습니다.",
        ),
        Sentiment.MIXED: (
            "처음에는 낯설겠지만 안내가 충분하면 익힐 수 있을 것 같습니다.",
            "안내 수준을 확인한 뒤 천천히 이용할 가능성이 있습니다.",
        ),
    },
}

NO_DIRECT_PERSONA_COPY = {
    PersonaKind.TIME_CONSTRAINED: (
        "현재 자료에는 짧은 이용 시간에 미칠 영향을 판단할 근거가 없습니다.",
        "이용 시간과 이탈 변화 자료를 보강하기 전에는 행동 변화를 예상하기 어렵습니다.",
    ),
    PersonaKind.VALUE_SEEKING: (
        "현재 자료에는 시간이나 비용에 미칠 영향을 판단할 근거가 없습니다.",
        "추가 비용과 이용 변화 자료를 보강하기 전에는 행동 변화를 예상하기 어렵습니다.",
    ),
    PersonaKind.COLLECTOR: (
        "현재 자료에는 수집 목표나 보유 상태에 미칠 영향을 판단할 근거가 없습니다.",
        "수집 행동 자료를 보강하기 전에는 행동 변화를 예상하기 어렵습니다.",
    ),
    PersonaKind.CORE_GAMEPLAY: (
        "현재 자료에는 핵심 이용 경험에 미칠 영향을 판단할 근거가 없습니다.",
        "성능과 이용 행동 자료를 보강하기 전에는 행동 변화를 예상하기 어렵습니다.",
    ),
}

PERSONA_COPY_LABELS = {
    PersonaKind.TIME_CONSTRAINED: "시간이 부족한 복귀 이용자",
    PersonaKind.VALUE_SEEKING: "가성비를 중시하는 이용자",
    PersonaKind.COLLECTOR: "수집을 즐기는 이용자",
    PersonaKind.CORE_GAMEPLAY: "전투 경험을 우선하는 이용자",
}

PERSONA_OPINION_CONTEXT = {
    PersonaKind.TIME_CONSTRAINED: "접속 시간이 짧은 입장에서는",
    PersonaKind.VALUE_SEEKING: "투입하는 시간과 비용을 따져보면",
    PersonaKind.COLLECTOR: "수집 목표와 보유 가치의 관점에서는",
    PersonaKind.CORE_GAMEPLAY: "실제 교전 경험을 기준으로 보면",
}

PERSONA_ACTION_CONTEXT = {
    PersonaKind.TIME_CONSTRAINED: "짧은 플레이 안에서 먼저 변화를 확인하고",
    PersonaKind.VALUE_SEEKING: "변경 효과와 부담을 비교하고",
    PersonaKind.COLLECTOR: "수집 목표와 보유 가치에 미치는 영향을 확인하고",
    PersonaKind.CORE_GAMEPLAY: "훈련장과 실제 교전에서 성능을 비교하고",
}


def _reaction_text(tag: str, sentiment: Sentiment) -> str:
    quote, action = SIGNAL_REACTION_COPY[tag][sentiment]
    return f"예상 대표 의견: “{quote}”\n예상 행동: {action}"


def _persona_reaction(
    persona: PersonaKind,
    signal_ids: list[str],
    sentiment: Sentiment,
) -> str:
    if not signal_ids:
        quote, action = NO_DIRECT_PERSONA_COPY[persona]
    else:
        tag = signal_ids[0].split("-", 1)[1]
        quote, action = SIGNAL_REACTION_COPY[tag][sentiment]
        quote = f"{PERSONA_OPINION_CONTEXT[persona]} {quote}"
        action = f"{PERSONA_ACTION_CONTEXT[persona]} {action}"
    return f"예상 대표 의견: “{quote}”\n예상 행동: {action}"


def _language_reaction(items) -> str:
    def leading_tag(sentiments: set[Sentiment]) -> tuple[str, Sentiment] | None:
        counts = Counter(
            (tag, item.sentiment)
            for item in items
            if item.sentiment in sentiments
            for tag in item.mechanism_tags
            if tag in SIGNAL_REACTION_COPY
        )
        return min(counts, key=lambda item: (-counts[item], item[0], item[1].value)) if counts else None

    positive_lead = leading_tag({Sentiment.POSITIVE})
    concern_lead = leading_tag({Sentiment.NEGATIVE, Sentiment.MIXED})
    positive = (
        SIGNAL_REACTION_COPY[positive_lead[0]][positive_lead[1]][0]
        if positive_lead
        else None
    )
    concern = (
        SIGNAL_REACTION_COPY[concern_lead[0]][concern_lead[1]][0]
        if concern_lead
        else None
    )
    if positive and concern:
        return f"“{positive}”라는 기대와 “{concern}”라는 신중한 반응이 함께 예상됩니다."
    if concern:
        return f"“{concern}”라는 우려가 가장 클 것으로 예상됩니다."
    if positive:
        return f"“{positive}”라는 기대가 가장 클 것으로 예상됩니다."
    return "현재 근거만으로는 이 언어권의 대표 반응을 예상하기 어렵습니다."

# Claude may select only these code-owned prospective alternatives.  The
# deterministic signal summary is also added for every signal at runtime.
_SIGNAL_PROSPECTIVE_ALTERNATIVES = {
    "predictability": (
        "피해량이 고정되면 결과 예측 가능성이 높아질 것으로 예상됩니다.",
    ),
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


def _signal_prospective_templates(signal: ReactionSignal) -> tuple[str, ...]:
    tag = signal.signal_id.split("-", 1)[1]
    return (signal.summary, *_SIGNAL_PROSPECTIVE_ALTERNATIVES.get(tag, ()))


class SignalNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class EvidenceNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[SignalNarrative]


class PersonaCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: PersonaKind
    opinion: str = Field(min_length=10, max_length=220)
    action: str = Field(min_length=10, max_length=220)


class PersonaCopyNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[PersonaCopy] = Field(min_length=1)


def _copy_key(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.casefold())


def _validate_persona_copy(
    base: UpdateEvidencePack,
    narrative: PersonaCopyNarrative,
) -> dict[PersonaKind, PersonaCopy]:
    expected = {item.persona for item in base.persona_impacts}
    received = [item.persona for item in narrative.personas]
    if len(received) != len(expected) or set(received) != expected:
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Haiku 페르소나 문구가 기존 이용자 유형과 일치하지 않습니다.",
        )
    values = [
        value
        for item in narrative.personas
        for value in (item.opinion, item.action)
    ]
    require_native_business_korean(values)
    opinions = [_copy_key(item.opinion) for item in narrative.personas]
    actions = [_copy_key(item.action) for item in narrative.personas]
    if len(set(opinions)) != len(opinions) or len(set(actions)) != len(actions):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Haiku 페르소나 문구가 서로 중복됩니다.",
        )
    unsafe = re.compile(r"https?://|www\.|@|\b[0-9a-f]{20,}\b|\b\d{10,}\b", re.I)
    if any("\n" in value or unsafe.search(value) for value in values):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Haiku 페르소나 문구에 허용하지 않은 식별 정보가 포함됐습니다.",
        )
    prospective = (
        "것 같습니다",
        "걱정됩니다",
        "싶습니다",
        "어렵습니다",
        "필요합니다",
        "수 있습니다",
    )
    actions_are_predictions = (
        "가능성이 있습니다",
        "가능성이 높습니다",
        "것으로 예상됩니다",
        "예상하기 어렵습니다",
        "확인해야 합니다",
        "수 있습니다",
    )
    if any(not any(marker in item.opinion for marker in prospective) for item in narrative.personas):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Haiku 의견은 출시 전 예상으로 표현해야 합니다.",
        )
    if any(not any(marker in item.action for marker in actions_are_predictions) for item in narrative.personas):
        raise StructuredModelError(
            ErrorCode.SCHEMA_INVALID,
            "Haiku 행동은 출시 전 가능성으로 표현해야 합니다.",
        )
    base_by_persona = {item.persona: item for item in base.persona_impacts}
    for item in narrative.personas:
        source = base_by_persona[item.persona]
        if not (
            source.positive_signal_ids
            or source.negative_signal_ids
            or source.split_signal_ids
        ) and (
            "자료" not in item.opinion
            or "어렵" not in item.opinion
            or "자료" not in item.action
            or "어렵" not in item.action
        ):
            raise StructuredModelError(
                ErrorCode.SCHEMA_INVALID,
                "근거가 없는 이용자 유형은 자료 부족을 분명히 밝혀야 합니다.",
            )
    return {item.persona: item for item in narrative.personas}


class UpdateEvidenceAgent:
    prompt_path = Path(__file__).with_name("prompts") / "evidence.md"
    persona_prompt_path = Path(__file__).with_name("prompts") / "persona.md"

    def __init__(
        self,
        use_llm: bool = False,
        client=None,
        budget: ClaudeBudget | None = None,
        rewrite_personas: bool = False,
    ) -> None:
        self.use_llm = use_llm
        self.client = client
        self.budget = budget
        self.rewrite_personas = rewrite_personas

    def run(
        self,
        bundle: UpdateFeedbackBundle,
        on_event: Callable[[str, str, dict], None] | None = None,
    ) -> UpdateEvidencePack:
        base = self.run_deterministic(bundle, on_event=on_event)
        if self.rewrite_personas:
            return self._rewrite_persona_copy(base, on_event)
        if not self.use_llm:
            return base
        notify = on_event or (lambda _node, _message, _metrics: None)
        notify(
            "claude_narrative",
            "Claude Sonnet이 고정된 근거 범위에서 출시 전 템플릿을 선택합니다.",
            {"provider": "claude"},
        )
        signals = {
            item.signal_id: item
            for item in [
                *base.positive_signals,
                *base.negative_signals,
                *base.split_conditions,
            ]
        }
        narrative = parse_claude_structured(
            model=os.getenv("CLAUDE_UPDATE_EVIDENCE_MODEL", "claude-sonnet-4-6"),
            prompt_path=self.prompt_path,
            output_type=EvidenceNarrative,
            payload={
                "artifact": base.model_dump(mode="json"),
                "prospective_templates": {
                    "summary_by_signal_id": {
                        signal_id: list(_signal_prospective_templates(signal))
                        for signal_id, signal in signals.items()
                    }
                },
            },
            client=self.client,
            budget=self.budget,
        )
        for proposal in narrative.signals:
            official = signals.get(proposal.signal_id)
            if official is None or not set(proposal.evidence_ids) <= set(
                official.evidence_ids
            ):
                raise StructuredModelError(
                    ErrorCode.SCHEMA_INVALID,
                    "Claude narrative references unknown signal evidence",
                )
            require_prelaunch_narrative(
                [proposal.title, proposal.summary],
                prediction_fields=[proposal.summary],
                prospective_templates=_signal_prospective_templates(official),
            )
        notify(
            "claude_output_checked",
            "Claude 템플릿 선택의 신호·근거 ID를 확인했고 코드 소유 문장을 유지했습니다.",
            {"provider": "claude"},
        )
        return base

    def _rewrite_persona_copy(
        self,
        base: UpdateEvidencePack,
        on_event: Callable[[str, str, dict], None] | None,
    ) -> UpdateEvidencePack:
        notify = on_event or (lambda _node, _message, _metrics: None)
        if len(base.persona_impacts) < 2:
            return base
        signals = {
            item.signal_id: item
            for item in [
                *base.positive_signals,
                *base.negative_signals,
                *base.split_conditions,
            ]
        }
        notify(
            "persona_copy_started",
            "Claude Haiku가 네 이용자 유형의 예상 의견과 행동을 서로 다르게 정리합니다.",
            {"provider": "claude", "personas": len(base.persona_impacts)},
        )
        try:
            narrative = parse_claude_structured(
                model=(
                    os.getenv("CLAUDE_UPDATE_PERSONA_MODEL", "").strip()
                    or "claude-haiku-4-5-20251001"
                ),
                prompt_path=self.persona_prompt_path,
                output_type=PersonaCopyNarrative,
                payload={
                    "personas": [
                        {
                            "persona": item.persona.value,
                            "label": PERSONA_COPY_LABELS[item.persona],
                            "baseline": item.expected_reaction,
                            "signals": [
                                {
                                    "signal_id": signal_id,
                                    "title": signals[signal_id].title,
                                    "sentiment": signals[signal_id].sentiment.value,
                                }
                                for signal_id in (
                                    item.positive_signal_ids
                                    + item.negative_signal_ids
                                    + item.split_signal_ids
                                )
                            ],
                            "linked_evidence_count": len(item.evidence_ids),
                        }
                        for item in base.persona_impacts
                    ]
                },
                client=self.client,
                budget=self.budget,
            )
            copy_by_persona = _validate_persona_copy(base, narrative)
        except StructuredModelError as exc:
            notify(
                "persona_copy_fallback",
                "Haiku 문구를 제외하고 서로 구분되는 코드 소유 예상 문구를 사용합니다.",
                {"reason": exc.code.value},
            )
            return base
        rewritten = [
            item.model_copy(
                update={
                    "expected_reaction": (
                        f"예상 대표 의견: “{copy_by_persona[item.persona].opinion.strip('“”\"')}”\n"
                        f"예상 행동: {copy_by_persona[item.persona].action}"
                    )
                }
            )
            for item in base.persona_impacts
        ]
        notify(
            "persona_copy_checked",
            "이용자 유형, 근거 연결, 신뢰도와 판정은 유지하고 중복 없는 예상 문구만 반영했습니다.",
            {"provider": "claude", "personas": len(rewritten)},
        )
        return base.model_copy(update={"persona_impacts": rewritten})

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
                            summary=_reaction_text(tag, sentiment),
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
        for persona, tags in (PERSONA_TAGS.items() if deduplicated else []):
            items = [item for item in deduplicated if tags.intersection(item.mechanism_tags)]
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
            split_ids = [
                item.signal_id
                for item in mixed
                if item.signal_id.split("-", 1)[1] in tags
            ]
            linked = items[:15]
            if negative_ids:
                expected_reaction = _persona_reaction(
                    persona, negative_ids, Sentiment.NEGATIVE
                )
            elif split_ids:
                expected_reaction = _persona_reaction(
                    persona, split_ids, Sentiment.MIXED
                )
            elif positive_ids:
                expected_reaction = _persona_reaction(
                    persona, positive_ids, Sentiment.POSITIVE
                )
            else:
                expected_reaction = _persona_reaction(persona, [], Sentiment.MIXED)
            personas.append(
                UpdatePersonaImpact(
                    persona=persona,
                    expected_reaction=expected_reaction,
                    positive_signal_ids=[value for value in positive_ids if value in signal_ids],
                    negative_signal_ids=[value for value in negative_ids if value in signal_ids],
                    split_signal_ids=split_ids,
                    evidence_ids=[item.evidence_id for item in linked],
                    confidence=(
                        sum(item.relevance for item in linked) / len(linked)
                        if linked
                        else 0
                    ),
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
            language_conclusion = _language_reaction(items)
            language_insights.append(
                UpdateLanguageInsight(
                    language=language,
                    conclusion=language_conclusion if sufficient else None,
                    hidden_reason=(
                        None
                        if sufficient
                        else "일반 의견 100건과 관련 의견 15건의 최소 표본 기준에 미달했습니다."
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
