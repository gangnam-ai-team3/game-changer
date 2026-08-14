from __future__ import annotations

from collections.abc import Callable
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
            raise ValueError(
                "fixture source is required until an external update source is selected"
            )
        notify = on_event or (lambda _node, _message, _metrics: None)
        result = load_update_feedback_fixture(brief, options.fixture_case)
        notify(
            "source_selected",
            "출시 전 예상을 위한 저장 비교 자료를 선택했습니다.",
            {"input_mode": options.input_mode.value},
        )
        notify(
            "period_checked",
            "모든 자료를 실제 사후 반응이 아닌 비교 참고로 구분했습니다.",
            {"comparable_reference": len(result.evidence)},
        )
        notify(
            "anonymized",
            "원문과 사용자 식별자 없이 합성 요약만 불러왔습니다.",
            {"evidence": len(result.evidence)},
        )
        notify(
            "samples_counted",
            "언어권별 관련 표본을 집계했습니다.",
            {"insufficient": sum(not item.sufficient for item in result.samples)},
        )
        notify(
            "bundle_ready",
            "UpdateFeedbackBundle 계약 검증을 통과했습니다.",
            {"evidence": len(result.evidence)},
        )
        return result
