import pytest

from agents.collector import CollectionOptions
from connectors import ConnectorError
from connectors.importer import import_approved_csv
from contracts import ErrorCode
from orchestrator import EventPreflightOrchestrator

HEADER = "source,source_url,source_id,language,observed_at,summary,mechanism_tags\n"


def test_imports_approved_anonymous_summary(event):
    data = HEADER + (
        "reddit,https://www.reddit.com/r/PUBATTLEGROUNDS/comments/abc,post-1,en,"
        "2025-06-10T00:00:00Z,Two stage reward path is confusing,double_gacha\n"
    )
    [item] = import_approved_csv(data, event.cutoff_at)
    assert item.source_id != "post-1"
    assert item.contains_personal_data is False


def test_import_strips_raw_summary_and_url_path_from_item_and_artifact(event, tmp_path):
    data = HEADER + (
        "reddit,https://www.reddit.com/users/alice?profile=alice#bio,post-alice,en,"
        "2025-06-10T00:00:00Z,username alice raw prose must never persist,double_gacha\n"
    )
    log_path = tmp_path / "run.jsonl"

    result = EventPreflightOrchestrator().run(
        event,
        CollectionOptions(use_fixture=False, imported_csv=data.encode()),
        log_path=log_path,
    )

    [item] = result.feedback.evidence
    assert item.source_url == "https://www.reddit.com"
    assert item.source_id != "post-alice"
    assert item.summary == "비식별 승인 입력에서 double_gacha 메커니즘 우려가 확인됨."
    serialized = item.model_dump_json() + log_path.read_text(encoding="utf-8")
    assert "alice" not in serialized
    assert "raw prose" not in serialized
    assert "/users/" not in serialized


@pytest.mark.parametrize("mechanism_tags", ["", "unknown_tag", "double_gacha|unknown_tag"])
def test_rejects_empty_or_unknown_mechanism_tags(event, mechanism_tags):
    data = HEADER + (
        "reddit,https://reddit.com/r/x,post-1,en,2025-06-10T00:00:00Z,"
        f"safe summary,{mechanism_tags}\n"
    )

    with pytest.raises(ConnectorError) as error:
        import_approved_csv(data, event.cutoff_at)

    assert error.value.code == ErrorCode.INVALID_IMPORT


def test_rejects_timezone_naive_observed_at(event):
    data = HEADER + (
        "reddit,https://reddit.com/r/x,post-1,en,2025-06-10T00:00:00,"
        "safe summary,double_gacha\n"
    )

    with pytest.raises(ConnectorError) as error:
        import_approved_csv(data, event.cutoff_at)

    assert error.value.code == ErrorCode.INVALID_IMPORT


def test_rejects_non_utf8_csv_as_invalid_import(event):
    with pytest.raises(ConnectorError) as error:
        import_approved_csv(b"\xff\xfe\x00", event.cutoff_at)

    assert error.value.code == ErrorCode.INVALID_IMPORT


@pytest.mark.parametrize(
    "data",
    [
        HEADER.replace("mechanism_tags", "username") +
        "reddit,https://www.reddit.com/r/x,post-1,en,2025-06-10T00:00:00Z,summary,user\n",
        HEADER +
        "reddit,https://evil.example/post,post-1,en,2025-06-10T00:00:00Z,summary,double_gacha\n",
        HEADER +
        "reddit,https://reddit.com/r/x/post,post-1,en,2025-06-11T00:00:00Z,summary,double_gacha\n",
    ],
)
def test_rejects_bad_csv(event, data):
    with pytest.raises(ConnectorError) as error:
        import_approved_csv(data, event.cutoff_at)
    assert error.value.code == ErrorCode.INVALID_IMPORT
