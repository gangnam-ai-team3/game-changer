from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

import backend.app.main as api_main
from res.corpus import CorpusRecord


def _record(
    index: int,
    *,
    language: str,
    stance: str,
    confidence: float = 0.9,
    topic_tags: tuple[str, ...] = ("weapon_balance", "core_gameplay"),
) -> CorpusRecord:
    return CorpusRecord(
        evidence_id=f"private-evidence-{index:04d}",
        language=language,
        created_at="2026-08-18T10:00:00+00:00",
        updated_at="2026-08-19T10:00:00+00:00",
        stance=stance,
        summary=f"{language} 비식별 파생 요약 {index}",
        reason_codes=("balance", "predictability"),
        behavior_codes=("wait_and_see",),
        topic_tags=topic_tags,
        confidence=confidence,
    )


def _manifest() -> dict[str, str]:
    return {
        "status": "active",
        "snapshot_at": "2026-08-19T11:41:41+00:00",
        "corpus_version": "test-corpus-v1",
        "ko_count": "100",
        "en_count": "120",
    }


def test_trends_returns_safe_aggregate_without_llm_or_private_metadata(monkeypatch):
    rows = {
        "ko": [
            _record(1, language="ko", stance="positive", confidence=0.9),
            _record(2, language="ko", stance="negative", confidence=0.8),
        ],
        "en": [
            _record(3, language="en", stance="mixed", confidence=0.7),
            _record(4, language="en", stance="neutral", confidence=0.6),
        ],
    }
    monkeypatch.setattr(api_main, "corpus_status", lambda _path: _manifest())
    monkeypatch.setattr(
        api_main,
        "search_corpus",
        lambda _query, *, language, **_kwargs: rows[language],
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("trend endpoint must not enter an LLM or public-run path")

    monkeypatch.setattr(api_main, "_public_demo_budget", forbidden)
    monkeypatch.setattr(api_main, "_acquire_public_run", forbidden)
    monkeypatch.setattr(api_main, "EventPreflightOrchestrator", forbidden)
    monkeypatch.setattr(api_main, "UpdateReviewOrchestrator", forbidden)

    response = TestClient(api_main.app).post(
        "/api/trends",
        json={
            "game": "PUBG: BATTLEGROUNDS",
            "report_title": "Dragunov 밸런스",
            "content_type": "update",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["snapshot_at"] == "2026-08-19T11:41:41Z"
    assert result["corpus_version"] == "test-corpus-v1"
    assert result["corpus_count"] == 220
    assert result["evidence_count"] == 4
    assert result["average_confidence"] == 0.75
    assert sum(result["sentiment_counts"].values()) == result["evidence_count"]
    assert sum(result["language_counts"].values()) == result["evidence_count"]
    assert result["top_topics"][0] == {"label": "무기 밸런스", "count": 4}
    assert result["top_reasons"][0] == {"label": "게임 밸런스", "count": 4}
    assert result["top_behaviors"][0] == {
        "label": "다른 이용자의 반응이나 추가 정보를 기다림",
        "count": 4,
    }
    assert len(result["evidence"]) <= 6
    assert [item["language"] for item in result["evidence"]] == ["ko", "en", "ko", "en"]
    assert all(set(item) == {"language", "stance", "summary", "confidence"} for item in result["evidence"])
    assert "private-evidence" not in response.text
    assert "created_at" not in response.text
    assert "updated_at" not in response.text
    assert "2026-08-18T10:00:00" not in response.text


def test_trends_uses_the_code_owned_category_query(monkeypatch):
    calls: list[tuple[str, str, int]] = []

    def search(query, *, language, limit, **_kwargs):
        calls.append((query, language, limit))
        return [_record(
            10 if language == "ko" else 11,
            language=language,
            stance="mixed",
            topic_tags=("reward_system", "event_flow"),
        )]

    monkeypatch.setattr(api_main, "corpus_status", lambda _path: _manifest())
    monkeypatch.setattr(api_main, "search_corpus", search)

    response = TestClient(api_main.app).post(
        "/api/trends",
        json={"game": "PUBG", "report_title": "희귀 콘텐츠"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["evidence_count"] == 2
    assert calls == [
        ("이벤트 보상 진행 구매", "ko", 20),
        ("이벤트 보상 진행 구매", "en", 20),
    ]


def test_trends_returns_safe_error_when_corpus_database_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "ROOT", tmp_path)

    response = TestClient(api_main.app).post(
        "/api/trends",
        json={"game": "PUBG", "report_title": "무기 밸런스"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "동향 코퍼스를 불러올 수 없습니다."}


def test_trends_rejects_games_outside_the_pubg_corpus(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsupported game must not read the corpus")

    monkeypatch.setattr(api_main, "corpus_status", forbidden)

    response = TestClient(api_main.app).post(
        "/api/trends",
        json={"game": "다른 게임", "report_title": "이벤트"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "현재 동향 코퍼스는 PUBG만 지원합니다."}


def test_trends_requires_an_honest_report_title_contract():
    response = TestClient(api_main.app).post(
        "/api/trends",
        json={"game": "PUBG", "content_scope": "검색 범위"},
    )

    assert response.status_code == 422


def test_trends_applies_the_selected_content_type(monkeypatch):
    monkeypatch.setattr(api_main, "corpus_status", lambda _path: _manifest())
    rows = [
        _record(30, language="ko", stance="negative", topic_tags=("reward_system",)),
        _record(31, language="ko", stance="positive", topic_tags=("weapon_balance",)),
    ]
    monkeypatch.setattr(
        api_main,
        "search_corpus",
        lambda _query, *, language, **_kwargs: rows if language == "ko" else [],
    )
    client = TestClient(api_main.app)

    event = client.post(
        "/api/trends",
        json={"game": "PUBG", "report_title": "공통 보고서", "content_type": "event"},
    ).json()
    update = client.post(
        "/api/trends",
        json={"game": "PUBG", "report_title": "공통 보고서", "content_type": "update"},
    ).json()

    assert event["sentiment_counts"]["negative"] == 1
    assert event["sentiment_counts"]["positive"] == 0
    assert update["sentiment_counts"]["negative"] == 0
    assert update["sentiment_counts"]["positive"] == 1
