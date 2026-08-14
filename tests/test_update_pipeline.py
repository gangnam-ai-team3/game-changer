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
    assert {item.period for item in bundle.evidence} == {
        EvidencePeriod.COMPARABLE_REFERENCE
    }
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
