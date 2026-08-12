from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from contracts import (
    ArtifactStatus,
    EventBrief,
    EvidenceItem,
    FeedbackBundle,
    InputMode,
    Language,
    LanguageSample,
    Producer,
    SearchRecord,
    SourceType,
)

ROOT = Path(__file__).resolve().parents[1]


def load_demo_event(run_id: str) -> EventBrief:
    return EventBrief(
        run_id=run_id,
        status=ArtifactStatus.COMPLETE,
        producer=Producer.USER,
        input_refs=[],
        errors=[],
        game="PUBG: BATTLEGROUNDS",
        event_name="Black Market 2025",
        goal=(
            "복귀 Progressive 스킨의 수집 매력을 활용해 이벤트 참여와 유료 전환을 유도하되, "
            "이용자가 목표 보상까지의 비용과 진행 경로를 명확히 이해할 수 있도록 한다."
        ),
        starts_at=datetime(2025, 6, 11, tzinfo=UTC),
        ends_at=datetime(2025, 7, 22, tzinfo=UTC),
        target_users=["복귀 유저", "무·소과금 유저", "스킨 수집 유저", "코어 전투 유저"],
        participation_rule="패스 미션, Loot Cache 구매·개봉, Workshop 특별 제작 참여",
        repeat_rule="일일·주간 미션과 반복 Loot Cache 개봉",
        rewards=["Progressive weapon skin", "Chroma", "Black Market Token", "Prime Parcel"],
        currencies=["G-Coin", "BP", "Black Market Token", "Scrap"],
        probability_guarantee=(
            "Loot Cache에서 확률 보상을 얻고 일부 Prime Parcel에서 다시 확률 보상을 얻는 "
            "2단계 구조. 원하는 스킨까지의 고정 마일스톤은 없음."
        ),
        monetization_policy=(
            "Crafter Pass와 G-Coin Loot Cache 팩을 판매하고 확률형 보너스로 추가 토큰을 제공. "
            "구매·개봉·제작·진행 확인 화면이 분리됨."
        ),
        expiration_policy="이벤트 종료 뒤 남은 Black Market Token은 교환·환불 없이 삭제",
        cutoff_at=datetime(2025, 6, 11, tzinfo=UTC),
    )


def load_feedback_fixture(event: EventBrief) -> FeedbackBundle:
    evidence: list[EvidenceItem] = []
    samples: list[LanguageSample] = []
    search_log: list[SearchRecord] = []
    path = ROOT / "fixtures" / "black_market_2025.jsonl"

    for line in path.read_text(encoding="utf-8").splitlines():
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
            template = row["summaries"][index % len(row["summaries"])]
            suffix = f"{language.value.replace('-', '').lower()}-{index + 1:03d}"
            evidence.append(
                EvidenceItem(
                    evidence_id=f"fx-{suffix}",
                    source=SourceType.SYNTHETIC,
                    source_url="https://example.invalid/event-preflight-fixture",
                    source_id=f"synthetic-{suffix}",
                    language=language,
                    observed_at=event.cutoff_at - timedelta(days=index + 1),
                    summary=template["text"],
                    mechanism_tags=[template["tag"]],
                    relevance=0.88,
                    synthetic=True,
                )
            )
        search_log.append(
            SearchRecord(
                source=SourceType.SYNTHETIC,
                language=language,
                query="Black Market mechanism synthetic fixture",
                requested_at=event.cutoff_at - timedelta(days=1),
                result_count=row["mechanism_count"],
            )
        )

    return FeedbackBundle(
        run_id=event.run_id,
        status=ArtifactStatus.COMPLETE,
        producer=Producer.COLLECTOR,
        input_refs=[event.event_name],
        errors=[],
        input_mode=InputMode.FIXTURE,
        cutoff_at=event.cutoff_at,
        search_log=search_log,
        samples=samples,
        evidence=evidence,
    )
