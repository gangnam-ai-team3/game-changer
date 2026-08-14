import json
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agents.structured import ClaudeBudget
from connectors import ConnectorError, RawFeedback
from connectors.steam import SteamClient
from connectors.x import XClient
from contracts import ArtifactStatus, ErrorCode, InputMode, Language, SourceType
from update_review.collector import (
    UpdateCollectionOptions,
    UpdateCollectorAgent,
    import_update_csv,
)
from update_review.contracts import EvidencePeriod, Sentiment, UpdateDecision
from update_review.fixtures import load_dragunov_brief
from update_review.orchestrator import UpdateReviewOrchestrator


CSV_HEADER = (
    "source,source_url,source_id,language,observed_at,period,sentiment,summary,"
    "mechanism_tags"
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class FakeClaudeMessages:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=self.payloads.pop(0))]
        )


class FakeClaude:
    def __init__(self, payloads):
        self.messages = FakeClaudeMessages(payloads)


def _safe_live_source_id(source: SourceType, source_id: str) -> str:
    digest = hashlib.sha256(f"{source.value}:{source_id}".encode()).hexdigest()[:20]
    return f"{source.value}-{digest}"


def _csv_row(
    *,
    source="reddit",
    source_url="https://www.reddit.com/r/PUBATTLEGROUNDS/comments/abc",
    source_id="public-source-1",
    language="ko",
    observed_at="2026-08-12T00:00:00+00:00",
    period="before",
    sentiment="negative",
    summary="승인된 비식별 요약",
    mechanism_tags="balance_regression",
):
    return ",".join(
        [
            source,
            source_url,
            source_id,
            language,
            observed_at,
            period,
            sentiment,
            summary,
            mechanism_tags,
        ]
    )


def test_steam_start_at_excludes_older_reviews():
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    payload = {
        "reviews": [
            {
                "timestamp_created": int((cutoff - timedelta(days=2)).timestamp()),
                "recommendationid": "inside",
                "review": "Dragunov fixed damage feels predictable",
            },
            {
                "timestamp_created": int((cutoff - timedelta(days=20)).timestamp()),
                "recommendationid": "old",
                "review": "old",
            },
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
    assert rows[0].source_url == "https://steamcommunity.com"


def test_x_start_at_excludes_older_posts():
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    payload = {
        "data": [
            {
                "id": "inside-post",
                "created_at": "2026-08-11T00:00:00+00:00",
                "text": "inside window",
            },
            {
                "id": "old-post",
                "created_at": "2026-07-01T00:00:00+00:00",
                "text": "old window",
            },
        ]
    }

    rows = XClient(
        "test-token", opener=lambda *_args, **_kwargs: Response(payload)
    ).fetch_recent(
        "PUBG",
        Language.ENGLISH,
        cutoff,
        start_at=cutoff - timedelta(days=7),
    )

    assert [item.text for item in rows] == ["inside window"]
    assert rows[0].source_url == "https://x.com"


def test_x_client_does_not_interpolate_an_untrusted_api_id_into_source_url():
    api_id_secret = "tweet-id?api_id_secret=NEVER-PERSIST"
    payload = {
        "data": [
            {
                "id": api_id_secret,
                "created_at": "2026-08-12T00:00:00+00:00",
                "text": "ephemeral X text",
            }
        ]
    }

    [row] = XClient(
        "test-token", opener=lambda *_args, **_kwargs: Response(payload)
    ).fetch_recent(
        "PUBG", Language.ENGLISH, datetime(2026, 8, 13, tzinfo=UTC)
    )

    assert row.source_url == "https://x.com"
    assert api_id_secret not in repr(row)


@pytest.mark.parametrize("client", ["steam", "x"])
def test_connector_rejects_invalid_start_at_window(client):
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    if client == "steam":
        with pytest.raises(ValueError, match="start_at"):
            SteamClient().fetch_reviews(
                578080, Language.ENGLISH, cutoff, start_at=cutoff
            )
    else:
        with pytest.raises(ValueError, match="start_at"):
            XClient("test-token").fetch_recent(
                "PUBG", Language.ENGLISH, cutoff, start_at=cutoff
            )


def test_update_csv_forbids_raw_and_identity_columns():
    with pytest.raises(ConnectorError, match="personal/raw columns are forbidden"):
        import_update_csv(
            CSV_HEADER + ",username\n",
            datetime(2026, 8, 13, tzinfo=UTC),
        )


@pytest.mark.parametrize("column", ["USERNAME", "Raw_Text", "TEXT"])
def test_update_csv_rejects_casefolded_personal_or_raw_columns(column):
    with pytest.raises(ConnectorError) as error:
        import_update_csv(
            CSV_HEADER + f",{column}\n",
            datetime(2026, 8, 13, tzinfo=UTC),
        )
    assert error.value.code is ErrorCode.INVALID_IMPORT
    assert "personal/raw columns are forbidden" in str(error.value)


def test_update_csv_rejects_unknown_extra_columns_without_reflecting_header():
    secret_header = "PRIVATE-HEADER-7788"
    with pytest.raises(ConnectorError) as error:
        import_update_csv(
            CSV_HEADER + f",{secret_header}\n",
            datetime(2026, 8, 13, tzinfo=UTC),
        )
    assert error.value.code is ErrorCode.INVALID_IMPORT
    assert secret_header not in str(error.value)


def test_update_csv_normalizes_source_identity_and_never_persists_summary_text():
    raw_summary = "alice의 계정 식별 문구와 원문은 절대 저장되면 안 된다"
    csv_data = "\n".join(
        [CSV_HEADER, _csv_row(source_id="public-1", summary=raw_summary)]
    )

    [item] = import_update_csv(csv_data, datetime(2026, 8, 13, tzinfo=UTC))

    assert item.period is EvidencePeriod.BEFORE
    assert item.sentiment is Sentiment.NEGATIVE
    assert item.source_id != "public-1"
    assert item.source_url == "https://www.reddit.com"
    assert item.summary != raw_summary
    assert raw_summary not in item.model_dump_json()
    assert "alice" not in item.model_dump_json()


def test_update_csv_namespaces_same_public_source_id_across_approved_sources():
    csv_data = "\n".join(
        [
            CSV_HEADER,
            _csv_row(source="reddit", source_id="same-public-id"),
            _csv_row(
                source="threads",
                source_url="https://www.threads.net/@safe/post/1",
                source_id="same-public-id",
            ),
        ]
    )

    rows = import_update_csv(csv_data, datetime(2026, 8, 13, tzinfo=UTC))

    assert len({item.source_id for item in rows}) == 2
    assert len({item.evidence_id for item in rows}) == 2


def test_approved_csv_collector_keeps_source_metadata_but_discards_summary_text():
    raw_summary = "approved CSV free text SECRET-CSV must not persist"
    bundle = UpdateCollectorAgent().run(
        load_dragunov_brief("approved-csv"),
        UpdateCollectionOptions(
            use_fixture=False,
            imported_csv="\n".join(
                [CSV_HEADER, _csv_row(summary=raw_summary, source_id="csv-success")]
            ),
        ),
    )

    assert bundle.input_mode is InputMode.IMPORT
    assert bundle.status is ArtifactStatus.PARTIAL  # five-language gate remains active
    assert bundle.evidence[0].source is SourceType.REDDIT_IMPORT
    assert bundle.search_log[0].source is SourceType.REDDIT_IMPORT
    assert raw_summary not in bundle.model_dump_json()


@pytest.mark.parametrize(
    "row",
    [
        _csv_row(period="after"),
        _csv_row(observed_at="2026-08-13T00:00:00+00:00"),
    ],
    ids=["after-period", "cutoff-row"],
)
def test_update_csv_rejects_actual_after_or_cutoff_rows(row):
    with pytest.raises(ConnectorError) as error:
        import_update_csv(
            "\n".join([CSV_HEADER, row]), datetime(2026, 8, 13, tzinfo=UTC)
        )
    assert error.value.code is ErrorCode.INVALID_IMPORT


def test_update_csv_has_separate_two_megabyte_utf8_limit():
    with pytest.raises(ConnectorError) as error:
        import_update_csv(b"x" * 2_000_001, datetime(2026, 8, 13, tzinfo=UTC))
    assert error.value.code is ErrorCode.INVALID_IMPORT


def test_live_failure_never_substitutes_dragunov_fixture():
    class BrokenSteam:
        def fetch_reviews(self, *_args, **_kwargs):
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
    assert result.feedback.input_mode is InputMode.LIVE
    assert result.feedback.evidence == []
    assert result.brief.decision is UpdateDecision.HOLD
    assert result.analysis_incomplete is True
    assert result.fallback_used is False
    assert [error.code for error in result.feedback.errors] == [
        ErrorCode.SOURCE_UNAVAILABLE
    ]


def test_live_raw_is_classified_then_discarded_with_source_metadata(tmp_path):
    raw_text = "private handle ALICE-123 must never enter an artifact or log"
    raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="anonymous-live-source",
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text=raw_text,
    )

    class FakeSteam:
        def __init__(self):
            self.calls = []

        def fetch_reviews(self, _app_id, language, _cutoff_at, **kwargs):
            self.calls.append((language, kwargs["start_at"]))
            return [raw] if language is Language.ENGLISH else []

    fake_claude = FakeClaude(
        [
            {
                "items": [
                    {
                        "source_id": _safe_live_source_id(
                            raw.source, raw.source_id
                        ),
                        "sentiment": "negative",
                        "mechanism_tags": ["balance_regression"],
                        "relevance": 0.9,
                    }
                ]
            }
        ]
    )
    steam = FakeSteam()
    collector = UpdateCollectorAgent(
        steam=steam, use_llm=True, client=fake_claude
    )
    log_path = tmp_path / "live.jsonl"
    result = UpdateReviewOrchestrator(collector=collector).run(
        load_dragunov_brief("live-raw-discard"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
        log_path=log_path,
    )
    serialized = json.dumps(
        {
            "feedback": result.feedback.model_dump(mode="json"),
            "brief": result.brief.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in result.events],
        },
        ensure_ascii=False,
    )

    assert len(steam.calls) == len(Language)
    assert all(start == datetime(2026, 8, 6, tzinfo=UTC) for _, start in steam.calls)
    assert result.feedback.search_log
    assert all(record.source is SourceType.STEAM for record in result.feedback.search_log)
    assert result.feedback.evidence[0].period is EvidencePeriod.BEFORE
    assert result.feedback.evidence[0].summary != raw_text
    assert raw_text not in serialized
    assert raw_text not in log_path.read_text(encoding="utf-8")
    assert "ALICE-123" not in serialized
    assert result.brief.decision is UpdateDecision.HOLD


def test_live_classifier_subset_forces_partial_hold_and_discards_all_raw(tmp_path):
    first_raw_text = "first subset raw text MUST-NOT-PERSIST-001"
    missing_raw_text = "missing subset raw text MUST-NOT-PERSIST-002"
    raw = [
        RawFeedback(
            source=SourceType.STEAM,
            source_url="https://steamcommunity.com/app/578080/reviews/",
            source_id="subset-source-one",
            language=Language.ENGLISH,
            observed_at=datetime(2026, 8, 12, tzinfo=UTC),
            text=first_raw_text,
        ),
        RawFeedback(
            source=SourceType.STEAM,
            source_url="https://steamcommunity.com/app/578080/reviews/",
            source_id="subset-source-two",
            language=Language.ENGLISH,
            observed_at=datetime(2026, 8, 12, tzinfo=UTC),
            text=missing_raw_text,
        ),
    ]

    class SubsetSteam:
        def fetch_reviews(self, _app_id, language, _cutoff_at, **_kwargs):
            return raw if language is Language.ENGLISH else []

    fake_claude = FakeClaude(
        [
            {
                "items": [
                    {
                        "source_id": _safe_live_source_id(
                            raw[0].source, raw[0].source_id
                        ),
                        "sentiment": "negative",
                        "mechanism_tags": ["balance_regression"],
                        "relevance": 0.9,
                    }
                ]
            }
        ]
    )
    log_path = tmp_path / "subset-classifier.jsonl"
    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(
            steam=SubsetSteam(), use_llm=True, client=fake_claude
        )
    ).run(
        load_dragunov_brief("subset-classifier"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
        log_path=log_path,
    )
    serialized = json.dumps(
        {
            "feedback": result.feedback.model_dump(mode="json"),
            "evidence": result.evidence.model_dump(mode="json"),
            "brief": result.brief.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in result.events],
        },
        ensure_ascii=False,
    )

    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.feedback.evidence == []
    assert result.feedback.errors[0].code is ErrorCode.SCHEMA_INVALID
    assert result.evidence.evidence == []
    assert result.brief.decision is UpdateDecision.HOLD
    assert result.analysis_incomplete is True
    assert len(fake_claude.messages.calls) == 1
    for raw_text in (first_raw_text, missing_raw_text):
        assert raw_text not in serialized
        assert raw_text not in log_path.read_text(encoding="utf-8")


def test_live_x_success_uses_shared_claude_budget_and_safe_source_metadata():
    raw_text = "X source free text SECRET-X must not persist"
    raw = RawFeedback(
        source=SourceType.X,
        source_url="https://x.com/i/web/status/1",
        source_id="anonymous-x-source",
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text=raw_text,
    )

    class FakeX:
        def __init__(self):
            self.calls = []

        def fetch_recent(self, _query, language, _cutoff_at, **kwargs):
            self.calls.append((language, kwargs["start_at"]))
            return [raw] if language is Language.ENGLISH else []

    budget = ClaudeBudget(max_requests=3)
    x_client = FakeX()
    bundle = UpdateCollectorAgent(
        x_client=x_client,
        use_llm=True,
        client=FakeClaude(
            [
                {
                    "items": [
                        {
                            "source_id": _safe_live_source_id(
                                raw.source, raw.source_id
                            ),
                            "sentiment": "negative",
                            "mechanism_tags": ["balance_regression"],
                            "relevance": 0.9,
                        }
                    ]
                }
            ]
        ),
        budget=budget,
    ).run(
        load_dragunov_brief("live-x-success"),
        UpdateCollectionOptions(
            use_fixture=False,
            use_x=True,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
    )

    assert len(x_client.calls) == len(Language)
    assert budget.requests == 1
    assert all(record.source is SourceType.X for record in bundle.search_log)
    assert raw_text not in bundle.model_dump_json()


def test_live_metadata_secrets_never_reach_artifacts_events_or_jsonl(tmp_path):
    steam_id_secret = "steam-source-id?private_id=STEAM-7788"
    x_url_secret = "x_url_query_secret=URL-9922"
    x_id_secret = "x-source-id?private_id=X-5566"
    raw_text_secret = "raw text SECRET-TEXT-4400"
    steam_raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id=steam_id_secret,
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text=raw_text_secret,
    )
    x_raw = RawFeedback(
        source=SourceType.X,
        source_url=f"https://x.com/i/web/status/123?{x_url_secret}",
        source_id=x_id_secret,
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text=raw_text_secret,
    )

    class FakeSteam:
        def fetch_reviews(self, _app_id, language, _cutoff_at, **_kwargs):
            return [steam_raw] if language is Language.ENGLISH else []

    class FakeX:
        def fetch_recent(self, _query, language, _cutoff_at, **_kwargs):
            return [x_raw] if language is Language.ENGLISH else []

    fake_claude = FakeClaude(
        [
            {
                "items": [
                    {
                        "source_id": _safe_live_source_id(
                            steam_raw.source, steam_raw.source_id
                        ),
                        "sentiment": "negative",
                        "mechanism_tags": ["balance_regression"],
                        "relevance": 0.9,
                    }
                ]
            }
        ]
    )
    log_path = tmp_path / "metadata-boundary.jsonl"
    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(
            steam=FakeSteam(),
            x_client=FakeX(),
            use_llm=True,
            client=fake_claude,
        )
    ).run(
        load_dragunov_brief("live-metadata-boundary"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            use_x=True,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
        log_path=log_path,
    )
    feedback_json = result.feedback.model_dump_json()
    events_json = json.dumps(
        [item.model_dump(mode="json") for item in result.events], ensure_ascii=False
    )
    brief_json = result.brief.model_dump_json()
    log_text = log_path.read_text(encoding="utf-8")

    [persisted] = result.feedback.evidence
    assert persisted.source_url == "https://steamcommunity.com"
    assert persisted.source_id == _safe_live_source_id(
        steam_raw.source, steam_raw.source_id
    )
    assert persisted.evidence_id == f"live-update-{persisted.source_id}"
    assert result.feedback.errors[0].code is ErrorCode.SCHEMA_INVALID
    assert result.brief.decision is UpdateDecision.HOLD
    classifier_payload = fake_claude.messages.calls[0]["messages"][0]["content"]
    assert steam_id_secret not in classifier_payload
    assert x_id_secret not in classifier_payload
    for secret in (steam_id_secret, x_url_secret, x_id_secret, raw_text_secret):
        assert secret not in feedback_json
        assert secret not in events_json
        assert secret not in brief_json
        assert secret not in log_text


@pytest.mark.parametrize(
    ("source", "source_url"),
    [
        (SourceType.STEAM, "https://attacker@steamcommunity.com/app/578080"),
        (SourceType.STEAM, "https://steamcommunity.com.evil.example/reviews"),
        (SourceType.X, "https://x.com:444/i/web/status/1"),
        (SourceType.X, "https://x.com/i/web/status/1#untrusted-fragment"),
    ],
    ids=["userinfo", "wrong-host", "unsafe-port", "fragment"],
)
def test_live_collector_rejects_unsafe_source_specific_urls(source, source_url):
    raw = RawFeedback(
        source=source,
        source_url=source_url,
        source_id="unsafe-source-id",
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text="unsafe source text",
    )

    class UnsafeSource:
        def fetch_reviews(self, _app_id, language, _cutoff_at, **_kwargs):
            return [raw] if language is Language.ENGLISH else []

        def fetch_recent(self, _query, language, _cutoff_at, **_kwargs):
            return [raw] if language is Language.ENGLISH else []

    fake_claude = FakeClaude([])
    collector = UpdateCollectorAgent(
        steam=UnsafeSource(),
        x_client=UnsafeSource(),
        use_llm=True,
        client=fake_claude,
    )
    options = UpdateCollectionOptions(
        use_fixture=False,
        steam_app_id=578080 if source is SourceType.STEAM else None,
        use_x=source is SourceType.X,
        period_start=datetime(2026, 8, 6, tzinfo=UTC),
        period_end=datetime(2026, 8, 13, tzinfo=UTC),
    )

    bundle = collector.run(load_dragunov_brief("unsafe-url"), options)

    assert bundle.status is ArtifactStatus.PARTIAL
    assert bundle.evidence == []
    assert bundle.errors[0].code is ErrorCode.SCHEMA_INVALID
    assert fake_claude.messages.calls == []


def test_live_cutoff_leak_is_discarded_before_classification_and_logging(tmp_path):
    leaked_text = "after-cutoff private phrase must not persist"
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    leaked_row = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="leaked-window-source",
        language=Language.ENGLISH,
        observed_at=cutoff,
        text=leaked_text,
    )

    class LeakySteam:
        def fetch_reviews(self, _app_id, language, _cutoff_at, **_kwargs):
            return [leaked_row] if language is Language.ENGLISH else []

    fake_claude = FakeClaude([])
    log_path = tmp_path / "cutoff-leak.jsonl"
    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(
            steam=LeakySteam(), use_llm=True, client=fake_claude
        )
    ).run(
        load_dragunov_brief("live-cutoff-leak"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=cutoff,
        ),
        log_path=log_path,
    )
    serialized = json.dumps(result.feedback.model_dump(mode="json"), ensure_ascii=False)

    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.feedback.evidence == []
    assert result.feedback.errors[0].code is ErrorCode.SCHEMA_INVALID
    assert result.brief.decision is UpdateDecision.HOLD
    assert fake_claude.messages.calls == []
    assert leaked_text not in serialized
    assert leaked_text not in log_path.read_text(encoding="utf-8")


def test_live_x_auth_failure_is_partial_hold_without_secret_error_text(tmp_path):
    secret = "x auth failure includes private request detail"

    class BrokenX:
        def fetch_recent(self, *_args, **_kwargs):
            raise ConnectorError(ErrorCode.AUTH_FAILED, secret)

    log_path = tmp_path / "x-auth.jsonl"
    result = UpdateReviewOrchestrator(
        collector=UpdateCollectorAgent(x_client=BrokenX())
    ).run(
        load_dragunov_brief("x-auth-failure"),
        UpdateCollectionOptions(
            use_fixture=False,
            use_x=True,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
        log_path=log_path,
    )
    serialized = json.dumps(
        {
            "feedback": result.feedback.model_dump(mode="json"),
            "brief": result.brief.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in result.events],
        },
        ensure_ascii=False,
    )

    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.feedback.errors[0].code is ErrorCode.AUTH_FAILED
    assert result.brief.decision is UpdateDecision.HOLD
    assert secret not in serialized
    assert secret not in log_path.read_text(encoding="utf-8")


def test_import_failure_discards_csv_text_and_never_uses_fixture(tmp_path):
    raw_text = "CSV private handle SECRET-998 must never persist"
    options = UpdateCollectionOptions(
        use_fixture=False,
        imported_csv="\n".join(
            [
                CSV_HEADER + ",raw_text",
                _csv_row(summary=raw_text) + "," + raw_text,
            ]
        ),
    )
    log_path = tmp_path / "invalid-import.jsonl"
    result = UpdateReviewOrchestrator().run(
        load_dragunov_brief("invalid-import"), options, log_path=log_path
    )
    serialized = json.dumps(
        {
            "feedback": result.feedback.model_dump(mode="json"),
            "brief": result.brief.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in result.events],
        },
        ensure_ascii=False,
    )

    assert options.imported_csv is None
    assert result.feedback.input_mode is InputMode.IMPORT
    assert result.feedback.status is ArtifactStatus.PARTIAL
    assert result.feedback.errors[0].code is ErrorCode.INVALID_IMPORT
    assert result.feedback.evidence == []
    assert result.brief.decision is UpdateDecision.HOLD
    assert raw_text not in serialized
    assert raw_text not in log_path.read_text(encoding="utf-8")


def test_live_cross_source_collision_is_partial_without_sending_raw_to_claude():
    steam_raw = RawFeedback(
        source=SourceType.STEAM,
        source_url="https://steamcommunity.com/app/578080/reviews/",
        source_id="same-source-id",
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text="steam secret raw text",
    )
    x_raw = RawFeedback(
        source=SourceType.X,
        source_url="https://x.com/i/web/status/1",
        source_id="same-source-id",
        language=Language.ENGLISH,
        observed_at=datetime(2026, 8, 12, tzinfo=UTC),
        text="x secret raw text",
    )

    class CollisionSteam:
        def fetch_reviews(self, _app_id, language, _cutoff_at, **_kwargs):
            return [steam_raw] if language is Language.ENGLISH else []

    class CollisionX:
        def fetch_recent(self, _query, language, _cutoff_at, **_kwargs):
            return [x_raw] if language is Language.ENGLISH else []

    fake_claude = FakeClaude([])
    bundle = UpdateCollectorAgent(
        steam=CollisionSteam(),
        x_client=CollisionX(),
        use_llm=True,
        client=fake_claude,
    ).run(
        load_dragunov_brief("live-collision"),
        UpdateCollectionOptions(
            use_fixture=False,
            steam_app_id=578080,
            use_x=True,
            period_start=datetime(2026, 8, 6, tzinfo=UTC),
            period_end=datetime(2026, 8, 13, tzinfo=UTC),
        ),
    )
    serialized = bundle.model_dump_json()

    assert bundle.status is ArtifactStatus.PARTIAL
    assert bundle.evidence == []
    assert bundle.errors[0].code is ErrorCode.SCHEMA_INVALID
    assert fake_claude.messages.calls == []
    assert steam_raw.text not in serialized
    assert x_raw.text not in serialized
