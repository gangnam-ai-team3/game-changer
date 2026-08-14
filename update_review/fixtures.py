from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from contracts import (
    ArtifactStatus,
    InputMode,
    Language,
    LanguageSample,
    Producer,
    SearchRecord,
    SourceType,
)
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
FIXTURE_FILES = {
    "dragunov_random_damage_removal": "dragunov_random_damage_removal.jsonl"
}
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
        expected_benefits=[
            "피해 결과 예측 가능성",
            "실력 중심 전투와의 정합성",
            "공정성 인식 개선",
        ],
        concerns=[
            "반동·연사력을 포함한 실제 성능",
            "사용률 급등 또는 하락",
            "코어 전투 이용자의 메타 반응",
        ],
        scope="일반 매칭의 Dragunov 사용 경험",
        planned_at=datetime(2026, 8, 20, tzinfo=UTC),
        cutoff_at=datetime(2026, 8, 13, tzinfo=UTC),
        official_context=(
            "PUBG Update 25.2에서 이용자 피드백을 바탕으로 "
            "확률형 피해를 제거했다는 공식 변경 맥락"
        ),
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
        samples.append(
            LanguageSample(
                language=language,
                general_count=row["general_count"],
                mechanism_count=row["mechanism_count"],
            )
        )
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
                    observed_at=brief.cutoff_at
                    - timedelta(days=(row_index * 15) + index + 1),
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
