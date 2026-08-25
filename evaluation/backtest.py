from __future__ import annotations

import json
import random
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from contracts import DecisionBrief

ROOT = Path(__file__).resolve().parents[1]


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    target_count: int = Field(ge=1)
    detected_count: int = Field(ge=0)
    detection_rate: float = Field(ge=0, le=1)
    detected_categories: list[str]
    missed_categories: list[str]
    evidence_link_rate: float = Field(ge=0, le=1)
    sampled_claim_count: int = Field(ge=0)
    sampled_claim_support_rate: float = Field(ge=0, le=1)
    persona_coverage_ok: bool
    passed: bool


def evaluate_black_market(brief: DecisionBrief) -> BacktestResult:
    """Read the post-cutoff answer key only after DecisionBrief exists."""

    ground_truth = json.loads(
        (ROOT / "evaluation" / "black_market_2025_ground_truth.json").read_text(encoding="utf-8")
    )
    targets = {item["category"] for item in ground_truth["targets"]}
    detected = {risk.category.value for risk in brief.top_risks} & targets
    evidence = {item.evidence_id: item for item in brief.evidence}

    linked = [risk for risk in brief.top_risks if risk.evidence_ids and set(risk.evidence_ids) <= evidence.keys()]
    evidence_link_rate = len(linked) / len(brief.top_risks) if brief.top_risks else 1.0

    claim_links = [
        (risk.category.value, evidence_id)
        for risk in brief.top_risks
        for evidence_id in risk.evidence_ids
        if evidence_id in evidence
    ]
    random.Random(20260804).shuffle(claim_links)
    sample = claim_links[:20]
    supported = sum(category in evidence[evidence_id].mechanism_tags for category, evidence_id in sample)
    support_rate = supported / len(sample) if sample else 0
    persona_ok = len(brief.panel_results) == 4 and all(
        len(set(result.evidence_ids)) >= 15 and set(result.evidence_ids) <= evidence.keys()
        for result in brief.panel_results
    )

    return BacktestResult(
        label=ground_truth["label"],
        target_count=len(targets),
        detected_count=len(detected),
        detection_rate=len(detected) / len(targets),
        detected_categories=sorted(detected),
        missed_categories=sorted(targets - detected),
        evidence_link_rate=evidence_link_rate,
        sampled_claim_count=len(sample),
        sampled_claim_support_rate=support_rate,
        persona_coverage_ok=persona_ok,
        passed=(
            len(detected) >= 3
            and evidence_link_rate == 1
            and len(sample) == 20
            and support_rate >= 0.9
            and persona_ok
        ),
    )
