from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

PUBG_APP_ID = 578080
TAXONOMY_VERSION = "pubg-steam-v1"
DEFAULT_DB = Path(".data/corpus/pubg_steam.sqlite3")
STEAM_LANGUAGES = {"ko": "koreana", "en": "english"}
_CODEX_ENV_KEYS = (
    "PATH",
    "HOME",
    "CODEX_HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
)


class CorpusBuildError(RuntimeError):
    pass


class Quality(StrEnum):
    USABLE = "usable"
    LOW_INFORMATION = "low_information"
    OFF_TOPIC = "off_topic"


class Stance(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class ReasonCode(StrEnum):
    FAIRNESS = "fairness"
    PREDICTABILITY = "predictability"
    BALANCE = "balance"
    COMPLEXITY = "complexity"
    COST_VALUE = "cost_value"
    PROGRESS_CLARITY = "progress_clarity"
    TIME_BURDEN = "time_burden"
    REWARD_APPEAL = "reward_appeal"
    GAMEPLAY_QUALITY = "gameplay_quality"
    PERFORMANCE_STABILITY = "performance_stability"
    CHEATING_SECURITY = "cheating_security"
    CONTENT_VARIETY = "content_variety"
    SOCIAL_EXPERIENCE = "social_experience"
    UNSPECIFIED = "unspecified"


class BehaviorCode(StrEnum):
    TRY_OR_RETURN = "try_or_return"
    CONTINUE_PLAYING = "continue_playing"
    PURCHASE_OR_PARTICIPATE = "purchase_or_participate"
    WAIT_AND_SEE = "wait_and_see"
    REDUCE_PLAY = "reduce_play"
    STOP_OR_REFUND = "stop_or_refund"
    REQUEST_CHANGE = "request_change"
    SWITCH_LOADOUT = "switch_loadout"
    RECOMMEND = "recommend"
    UNSPECIFIED = "unspecified"


class TopicTag(StrEnum):
    WEAPON_BALANCE = "weapon_balance"
    RANDOMNESS = "randomness"
    REWARD_SYSTEM = "reward_system"
    PROGRESSION = "progression"
    MONETIZATION = "monetization"
    EVENT_FLOW = "event_flow"
    MATCHMAKING = "matchmaking"
    PERFORMANCE = "performance"
    ANTI_CHEAT = "anti_cheat"
    CONTENT = "content"
    INTERFACE = "interface"
    CORE_GAMEPLAY = "core_gameplay"
    OTHER = "other"


class ReviewLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=24, max_length=24)
    quality: Quality
    stance: Stance
    reason_codes: list[ReasonCode] = Field(min_length=1, max_length=3)
    behavior_codes: list[BehaviorCode] = Field(min_length=1, max_length=2)
    topic_tags: list[TopicTag] = Field(min_length=1, max_length=4)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def unique_codes(self) -> ReviewLabel:
        for values in (self.reason_codes, self.behavior_codes, self.topic_tags):
            if len(values) != len(set(values)):
                raise ValueError("classification codes must be unique")
        return self


class ReviewLabelBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReviewLabel]


@dataclass(frozen=True, slots=True)
class EphemeralSteamReview:
    """Raw text is process-memory only and must never be serialized."""

    evidence_id: str
    language: str
    created_at: datetime
    updated_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    evidence_id: str
    language: str
    created_at: str
    updated_at: str
    stance: str
    summary: str
    reason_codes: tuple[str, ...]
    behavior_codes: tuple[str, ...]
    topic_tags: tuple[str, ...]
    confidence: float


STANCE_LABELS = {
    Stance.POSITIVE: "긍정적인 경험",
    Stance.NEGATIVE: "부정적인 경험",
    Stance.MIXED: "장점과 우려가 함께 있는 경험",
    Stance.NEUTRAL: "판단을 유보한 경험",
}
REASON_LABELS = {
    ReasonCode.FAIRNESS: "결과의 공정성",
    ReasonCode.PREDICTABILITY: "결과를 예상하기 쉬운 정도",
    ReasonCode.BALANCE: "게임 밸런스",
    ReasonCode.COMPLEXITY: "이용 과정의 복잡성",
    ReasonCode.COST_VALUE: "비용 대비 가치",
    ReasonCode.PROGRESS_CLARITY: "진행 상황의 명확성",
    ReasonCode.TIME_BURDEN: "필요한 시간과 반복 부담",
    ReasonCode.REWARD_APPEAL: "보상의 매력",
    ReasonCode.GAMEPLAY_QUALITY: "핵심 플레이 경험",
    ReasonCode.PERFORMANCE_STABILITY: "성능과 안정성",
    ReasonCode.CHEATING_SECURITY: "부정행위 대응과 신뢰",
    ReasonCode.CONTENT_VARIETY: "콘텐츠의 다양성",
    ReasonCode.SOCIAL_EXPERIENCE: "함께 플레이하는 경험",
    ReasonCode.UNSPECIFIED: "구체적으로 드러나지 않은 이유",
}
BEHAVIOR_LABELS = {
    BehaviorCode.TRY_OR_RETURN: "직접 사용하거나 다시 접속함",
    BehaviorCode.CONTINUE_PLAYING: "현재 플레이를 이어감",
    BehaviorCode.PURCHASE_OR_PARTICIPATE: "구매하거나 이벤트에 참여함",
    BehaviorCode.WAIT_AND_SEE: "다른 이용자의 반응이나 추가 정보를 기다림",
    BehaviorCode.REDUCE_PLAY: "플레이 시간을 줄임",
    BehaviorCode.STOP_OR_REFUND: "플레이를 중단하거나 환불을 고려함",
    BehaviorCode.REQUEST_CHANGE: "추가 수정이나 개선을 요청함",
    BehaviorCode.SWITCH_LOADOUT: "다른 무기나 플레이 방식을 선택함",
    BehaviorCode.RECOMMEND: "다른 이용자에게 추천함",
    BehaviorCode.UNSPECIFIED: "구체적인 다음 행동은 드러나지 않음",
}
TOPIC_LABELS = {
    TopicTag.WEAPON_BALANCE: "무기 밸런스",
    TopicTag.RANDOMNESS: "확률과 무작위 결과",
    TopicTag.REWARD_SYSTEM: "보상 구조",
    TopicTag.PROGRESSION: "진행 구조",
    TopicTag.MONETIZATION: "유료 이용 방식",
    TopicTag.EVENT_FLOW: "이벤트 참여 과정",
    TopicTag.MATCHMAKING: "매치메이킹",
    TopicTag.PERFORMANCE: "성능과 오류",
    TopicTag.ANTI_CHEAT: "부정행위 대응",
    TopicTag.CONTENT: "콘텐츠 구성",
    TopicTag.INTERFACE: "화면과 조작 흐름",
    TopicTag.CORE_GAMEPLAY: "핵심 전투 경험",
    TopicTag.OTHER: "기타 게임 경험",
}
QUERY_ALIASES = {
    "확률": ("randomness", "predictability"),
    "랜덤": ("randomness", "predictability"),
    "상자": ("randomness", "reward_system", "monetization"),
    "보상": ("reward_system", "reward_appeal", "progression"),
    "패스": ("reward_system", "progression", "monetization"),
    "토큰": ("reward_system", "progression", "monetization"),
    "비용": ("cost_value", "monetization"),
    "구매": ("cost_value", "monetization"),
    "무기": ("weapon_balance", "balance", "core_gameplay"),
    "피해": ("weapon_balance", "balance", "predictability"),
    "반동": ("weapon_balance", "core_gameplay"),
    "dmr": ("weapon_balance", "core_gameplay"),
    "dragunov": ("weapon_balance", "core_gameplay"),
    "성능": ("performance", "performance_stability"),
    "오류": ("performance", "performance_stability"),
    "핵": ("anti_cheat", "cheating_security"),
    "cheat": ("anti_cheat", "cheating_security"),
    "gacha": ("randomness", "reward_system", "monetization"),
    "loot": ("randomness", "reward_system"),
    "weapon": ("weapon_balance", "balance", "core_gameplay"),
    "damage": ("weapon_balance", "balance", "predictability"),
}

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,32}\b")
_LONG_ID = re.compile(r"\b\d{12,20}\b")
_STEAM_MARKUP = re.compile(r"\[/?[A-Za-z0-9_= -]+\]")
_SPACE = re.compile(r"\s+")


def classify_with_codex(
    reviews: list[EphemeralSteamReview],
    *,
    codex_bin: str = "codex",
    timeout_seconds: int = 600,
) -> list[ReviewLabel]:
    if not reviews:
        return []
    payload = {
        "items": [
            {
                "item_id": review.evidence_id,
                "language": review.language,
                "text": _redact(review.text),
            }
            for review in reviews
        ]
    }
    env = {key: os.environ[key] for key in _CODEX_ENV_KEYS if key in os.environ}
    prompt = Path(__file__).with_name("corpus_prompt.md").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="gamechanger-corpus-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        schema_path.write_text(
            json.dumps(ReviewLabelBatch.model_json_schema(), ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    codex_bin,
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "--output-schema",
                    str(schema_path),
                    prompt,
                ],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                cwd=temp_dir,
                env=env,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CorpusBuildError("Codex 분류 작업을 실행하지 못했습니다.") from exc
    if completed.returncode != 0:
        raise CorpusBuildError("Codex 분류 작업이 완료되지 않았습니다.")
    try:
        batch = ReviewLabelBatch.model_validate_json(completed.stdout)
    except ValueError as exc:
        raise CorpusBuildError("Codex 분류 결과가 약속한 형식과 다릅니다.") from exc
    return _validate_label_ids(reviews, batch.items)


def verify_chatgpt_login(*, codex_bin: str = "codex") -> str:
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    try:
        status = subprocess.run(
            [codex_bin, "login", "status"],
            text=True,
            capture_output=True,
            env=env,
            timeout=20,
            check=False,
        )
        version = subprocess.run(
            [codex_bin, "--version"],
            text=True,
            capture_output=True,
            env=env,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CorpusBuildError("Codex CLI 상태를 확인할 수 없습니다.") from exc
    login_output = f"{status.stdout}\n{status.stderr}"
    if status.returncode != 0 or "Logged in using ChatGPT" not in login_output:
        raise CorpusBuildError("Codex CLI를 ChatGPT 구독 계정으로 로그인해 주세요.")
    if version.returncode != 0:
        raise CorpusBuildError("Codex CLI 버전을 확인할 수 없습니다.")
    return version.stdout.strip()


def build_from_hy_db(
    source_db: Path,
    db_path: Path = DEFAULT_DB,
    *,
    target_per_language: int = 500,
    batch_size: int = 40,
    max_pages: int = 20,
    classify: Callable[[list[EphemeralSteamReview]], list[ReviewLabel]] = classify_with_codex,
    classifier_name: str | None = None,
) -> dict[str, Any]:
    """Convert Hy's complete local raw DB into Res's safe active corpus."""
    source_db = Path(source_db)
    db_path = Path(db_path)
    stage_path = db_path.with_name(f"{db_path.name}.staging")
    key_path = db_path.with_name(f".{db_path.name}.evidence-key")
    _reject_source_database(source_db, db_path, stage_path, key_path)
    if not source_db.is_file():
        raise CorpusBuildError("Hy 원본 DB를 찾지 못했습니다.")

    connection = sqlite3.connect(f"{source_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        snapshot, backfill_watermarks = _hy_safe_snapshot(connection)
        evidence_key = _load_or_create_evidence_key(key_path)
        seen_text_hashes = {language: set() for language in STEAM_LANGUAGES}

        def fetch_reviews(**kwargs) -> Iterator[EphemeralSteamReview]:
            return _iter_hy_reviews(
                connection,
                language=kwargs["language"],
                cutoff_at=kwargs["cutoff_at"],
                evidence_key=evidence_key,
                seen_text_hashes=seen_text_hashes[kwargs["language"]],
                candidate_limit=kwargs["max_pages"] * 100,
                backfill_watermark=backfill_watermarks[
                    STEAM_LANGUAGES[kwargs["language"]]
                ],
            )

        return build_corpus(
            db_path,
            target_per_language=target_per_language,
            batch_size=batch_size,
            max_pages=max_pages,
            fetch_reviews=fetch_reviews,
            classify=classify,
            classifier_name=classifier_name,
            snapshot_at=snapshot,
        )
    except sqlite3.Error as exc:
        raise CorpusBuildError("Hy 원본 DB 형식이 올바르지 않습니다.") from exc
    finally:
        connection.close()


def _reject_source_database(source_db: Path, *protected_paths: Path) -> None:
    source = source_db.resolve()
    for path in protected_paths:
        protected = path.resolve()
        if source == protected or (
            source.exists()
            and protected.exists()
            and os.path.samefile(source, protected)
        ):
            raise CorpusBuildError(
                "Hy 원본 DB와 안전 코퍼스 관련 경로는 같을 수 없습니다."
            )


def _load_or_create_evidence_key(key_path: Path) -> bytes:
    if key_path.is_symlink():
        raise CorpusBuildError("코퍼스 ID 키 경로는 심볼릭 링크일 수 없습니다.")
    try:
        key = key_path.read_bytes()
    except FileNotFoundError:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = key_path.read_bytes()
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
    if len(key) != 32:
        raise CorpusBuildError("코퍼스 ID 키 형식이 올바르지 않습니다.")
    os.chmod(key_path, 0o600)
    return key


def _hy_safe_snapshot(
    connection: sqlite3.Connection,
) -> tuple[datetime, dict[str, int]]:
    state = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            """
            SELECT language, done, updated_at
            FROM collector_state
            WHERE language IN ('koreana', 'english')
            """
        )
    }
    if set(state) != {"koreana", "english"}:
        raise CorpusBuildError("Hy DB의 한국어와 영어 수집 상태가 모두 필요합니다.")
    if any(done != 1 for done, _watermark in state.values()):
        raise CorpusBuildError("Hy DB의 한국어와 영어 수집이 완료되지 않았습니다.")
    try:
        watermarks = {language: int(value[1]) for language, value in state.items()}
    except (TypeError, ValueError) as exc:
        raise CorpusBuildError("Hy DB의 백필 완료 시각이 올바르지 않습니다.") from exc
    collected_at = {
        language: connection.execute(
            """
            SELECT MIN(collected_at)
            FROM reviews
            WHERE appid = ? AND language = ? AND collected_at <= ?
            """,
            (PUBG_APP_ID, language, watermark),
        ).fetchone()[0]
        for language, watermark in watermarks.items()
    }
    if set(collected_at) != {"koreana", "english"} or any(
        value is None for value in collected_at.values()
    ):
        raise CorpusBuildError("Hy DB에 한국어와 영어 리뷰가 모두 필요합니다.")
    try:
        snapshot = datetime.fromtimestamp(min(collected_at.values()) / 1000, UTC)
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        raise CorpusBuildError("Hy DB의 수집 시각이 올바르지 않습니다.") from exc
    return snapshot, watermarks


def _iter_hy_reviews(
    connection: sqlite3.Connection,
    *,
    language: str,
    cutoff_at: datetime,
    evidence_key: bytes,
    seen_text_hashes: set[bytes],
    candidate_limit: int,
    backfill_watermark: int,
) -> Iterator[EphemeralSteamReview]:
    steam_language = STEAM_LANGUAGES[language]
    cutoff_timestamp = int(cutoff_at.timestamp())
    rows = connection.execute(
        """
        SELECT recommendationid, review, timestamp_created,
               COALESCE(timestamp_updated, timestamp_created)
        FROM reviews
        WHERE appid = ? AND language = ?
          AND timestamp_created < ?
          AND COALESCE(timestamp_updated, timestamp_created) < ?
          AND collected_at <= ?
        ORDER BY timestamp_created DESC, recommendationid
        LIMIT ?
        """,
        (
            PUBG_APP_ID,
            steam_language,
            cutoff_timestamp,
            cutoff_timestamp,
            backfill_watermark,
            candidate_limit,
        ),
    )
    for public_id, text, created, updated in rows:
        if (
            not isinstance(public_id, str)
            or not public_id.strip()
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue
        text_hash = hashlib.sha256(text.encode()).digest()
        if text_hash in seen_text_hashes:
            continue
        seen_text_hashes.add(text_hash)
        try:
            created_at = datetime.fromtimestamp(int(created), UTC)
            updated_at = datetime.fromtimestamp(int(updated), UTC)
        except (OverflowError, OSError, TypeError, ValueError):
            continue
        if created_at > updated_at:
            continue
        evidence_id = hmac.new(
            evidence_key,
            f"steam:{PUBG_APP_ID}:{public_id}".encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        yield EphemeralSteamReview(
            evidence_id=evidence_id,
            language=language,
            created_at=cutoff_at,
            updated_at=cutoff_at,
            text=text.strip(),
        )


def build_corpus(
    db_path: Path = DEFAULT_DB,
    *,
    target_per_language: int = 500,
    batch_size: int = 40,
    max_pages: int = 20,
    resume: bool = False,
    fetch_reviews: Callable[..., Iterable[EphemeralSteamReview]],
    classify: Callable[[list[EphemeralSteamReview]], list[ReviewLabel]] = classify_with_codex,
    classifier_name: str | None = None,
    snapshot_at: datetime | None = None,
) -> dict[str, Any]:
    if target_per_language < 1 or not 1 <= batch_size <= 100 or max_pages < 1:
        raise ValueError(
            "target_per_language, batch_size and max_pages must be positive"
        )
    db_path = Path(db_path)
    stage_path = db_path.with_name(f"{db_path.name}.staging")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    current_classifier = classifier_name or verify_chatgpt_login()

    if resume and stage_path.exists():
        connection = sqlite3.connect(stage_path)
        manifest = _read_manifest(connection)
        snapshot = datetime.fromisoformat(manifest["snapshot_at"])
        if (
            int(manifest["target_per_language"]) != target_per_language
            or int(manifest["app_id"]) != PUBG_APP_ID
            or manifest["taxonomy_version"] != TAXONOMY_VERSION
        ):
            connection.close()
            raise CorpusBuildError("기존 준비 코퍼스의 설정이 현재 실행과 다릅니다.")
        if manifest["classifier"] != current_classifier:
            connection.close()
            raise CorpusBuildError("기존 준비 코퍼스의 분류기 버전이 현재 실행과 다릅니다.")
        classifier_version = current_classifier
    else:
        stage_path.unlink(missing_ok=True)
        snapshot = snapshot_at or datetime.now(UTC)
        if snapshot.tzinfo is None:
            raise ValueError("snapshot_at must be timezone-aware")
        classifier_version = current_classifier
        connection = sqlite3.connect(stage_path)
        _initialize_database(
            connection,
            snapshot=snapshot,
            target_per_language=target_per_language,
            classifier=classifier_version,
        )

    try:
        existing_ids = {
            row[0] for row in connection.execute("SELECT evidence_id FROM evidence")
        }
        for language in ("ko", "en"):
            accepted = _language_count(connection, language)
            if accepted >= target_per_language:
                continue
            pending: list[EphemeralSteamReview] = []
            for review in fetch_reviews(
                app_id=PUBG_APP_ID,
                language=language,
                cutoff_at=snapshot,
                max_pages=max_pages,
            ):
                if review.evidence_id in existing_ids:
                    continue
                pending.append(review)
                if len(pending) < batch_size:
                    continue
                accepted += _classify_and_store(
                    connection,
                    pending,
                    classify,
                    classifier_version,
                    target_per_language - accepted,
                )
                existing_ids.update(item.evidence_id for item in pending)
                pending.clear()
                if accepted >= target_per_language:
                    break
            if pending and accepted < target_per_language:
                accepted += _classify_and_store(
                    connection,
                    pending,
                    classify,
                    classifier_version,
                    target_per_language - accepted,
                )
                pending.clear()
            if accepted < target_per_language:
                raise CorpusBuildError(
                    f"{language} 언어에서 사용할 수 있는 리뷰를 {target_per_language}건 모으지 못했습니다."
                )

        manifest = _finalize_database(connection, target_per_language)
        connection.close()
        os.replace(stage_path, db_path)
        return manifest
    except Exception:
        connection.close()
        raise


def search_corpus(
    query: str,
    *,
    db_path: Path = DEFAULT_DB,
    language: str,
    limit: int = 20,
    cutoff_at: datetime | None = None,
) -> list[CorpusRecord]:
    if language not in STEAM_LANGUAGES:
        raise ValueError("language must be ko or en")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if cutoff_at is not None and cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware")
    terms = _query_terms(query)
    if not terms:
        raise ValueError("검색어에서 사용할 수 있는 단어를 찾지 못했습니다")
    match = " OR ".join(f'"{term}"' for term in terms)
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT e.evidence_id, e.language, e.created_at, e.updated_at,
                   e.stance, e.summary, e.reason_codes, e.behavior_codes,
                   e.topic_tags, e.confidence
            FROM evidence_fts AS f
            JOIN evidence AS e ON e.evidence_id = f.evidence_id
            WHERE evidence_fts MATCH ? AND e.language = ?
              AND (? IS NULL OR e.updated_at < ?)
            ORDER BY bm25(evidence_fts), e.evidence_id
            LIMIT ?
            """,
            (
                match,
                language,
                cutoff_at.astimezone(UTC).isoformat() if cutoff_at else None,
                cutoff_at.astimezone(UTC).isoformat() if cutoff_at else None,
                limit,
            ),
        ).fetchall()
    finally:
        connection.close()
    return [
        CorpusRecord(
            evidence_id=row[0],
            language=row[1],
            created_at=row[2],
            updated_at=row[3],
            stance=row[4],
            summary=row[5],
            reason_codes=tuple(json.loads(row[6])),
            behavior_codes=tuple(json.loads(row[7])),
            topic_tags=tuple(json.loads(row[8])),
            confidence=float(row[9]),
        )
        for row in rows
    ]


def corpus_status(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        return _read_manifest(connection)
    finally:
        connection.close()


def _classify_and_store(
    connection: sqlite3.Connection,
    reviews: list[EphemeralSteamReview],
    classify: Callable[[list[EphemeralSteamReview]], list[ReviewLabel]],
    classifier: str,
    remaining: int,
) -> int:
    labels = _validate_label_ids(reviews, classify(reviews))
    by_id = {item.item_id: item for item in labels}
    inserted = 0
    for review in reviews:
        if inserted >= remaining:
            break
        label = by_id[review.evidence_id]
        if label.quality is not Quality.USABLE:
            continue
        summary = _summary(label)
        codes = " ".join(
            [
                *(item.value for item in label.reason_codes),
                *(item.value for item in label.behavior_codes),
                *(item.value for item in label.topic_tags),
            ]
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO evidence (
                evidence_id, app_id, language, created_at, updated_at, stance,
                summary, reason_codes, behavior_codes, topic_tags, confidence,
                classifier, taxonomy_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.evidence_id,
                PUBG_APP_ID,
                review.language,
                review.created_at.isoformat(),
                review.updated_at.isoformat(),
                label.stance.value,
                summary,
                json.dumps([item.value for item in label.reason_codes]),
                json.dumps([item.value for item in label.behavior_codes]),
                json.dumps([item.value for item in label.topic_tags]),
                label.confidence,
                classifier,
                TAXONOMY_VERSION,
            ),
        )
        if cursor.rowcount:
            connection.execute(
                "INSERT INTO evidence_fts (evidence_id, search_text) VALUES (?, ?)",
                (review.evidence_id, f"{summary} {codes}"),
            )
            inserted += 1
    connection.commit()
    return inserted


def _validate_label_ids(
    reviews: list[EphemeralSteamReview], labels: list[ReviewLabel]
) -> list[ReviewLabel]:
    expected = [item.evidence_id for item in reviews]
    returned = [item.item_id for item in labels]
    if len(returned) != len(set(returned)) or set(returned) != set(expected):
        missing = len(set(expected) - set(returned))
        extra = len(set(returned) - set(expected))
        duplicates = len(returned) - len(set(returned))
        raise CorpusBuildError(
            "분류 결과의 리뷰 ID가 입력과 정확히 일치하지 않습니다"
            f"(누락 {missing}건, 추가 {extra}건, 중복 {duplicates}건)."
        )
    return labels


def _initialize_database(
    connection: sqlite3.Connection,
    *,
    snapshot: datetime,
    target_per_language: int,
    classifier: str,
) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        CREATE TABLE manifest (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            app_id INTEGER NOT NULL CHECK (app_id = 578080),
            language TEXT NOT NULL CHECK (language IN ('ko', 'en')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            stance TEXT NOT NULL,
            summary TEXT NOT NULL,
            reason_codes TEXT NOT NULL,
            behavior_codes TEXT NOT NULL,
            topic_tags TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            classifier TEXT NOT NULL,
            taxonomy_version TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE evidence_fts USING fts5(
            evidence_id UNINDEXED,
            search_text,
            tokenize='unicode61'
        );
        """
    )
    version = f"pubg-steam-{snapshot.astimezone(UTC):%Y%m%dT%H%M%SZ}-{TAXONOMY_VERSION}"
    values = {
        "status": "staging",
        "corpus_version": version,
        "app_id": str(PUBG_APP_ID),
        "snapshot_at": snapshot.isoformat(),
        "target_per_language": str(target_per_language),
        "classifier": classifier,
        "taxonomy_version": TAXONOMY_VERSION,
    }
    connection.executemany(
        "INSERT INTO manifest (key, value) VALUES (?, ?)", values.items()
    )
    connection.commit()


def _finalize_database(
    connection: sqlite3.Connection, target_per_language: int
) -> dict[str, Any]:
    counts = {
        language: _language_count(connection, language) for language in ("ko", "en")
    }
    if counts != {"ko": target_per_language, "en": target_per_language}:
        raise CorpusBuildError("언어별 목표 수량을 채우지 못해 코퍼스를 활성화하지 않습니다.")
    fts_count = connection.execute("SELECT COUNT(*) FROM evidence_fts").fetchone()[0]
    if fts_count != target_per_language * 2:
        raise CorpusBuildError("검색 색인과 코퍼스 레코드 수가 일치하지 않습니다.")

    digest = hashlib.sha256()
    for row in connection.execute(
        "SELECT * FROM evidence ORDER BY language, evidence_id"
    ):
        digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
    updates = {
        "status": "active",
        "completed_at": datetime.now(UTC).isoformat(),
        "ko_count": str(counts["ko"]),
        "en_count": str(counts["en"]),
        "content_hash": digest.hexdigest(),
    }
    connection.executemany(
        "INSERT OR REPLACE INTO manifest (key, value) VALUES (?, ?)", updates.items()
    )
    connection.commit()
    return _read_manifest(connection)


def _read_manifest(connection: sqlite3.Connection) -> dict[str, Any]:
    return dict(connection.execute("SELECT key, value FROM manifest ORDER BY key"))


def _language_count(connection: sqlite3.Connection, language: str) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM evidence WHERE language = ?", (language,)
        ).fetchone()[0]
    )


def _summary(label: ReviewLabel) -> str:
    reasons = ", ".join(REASON_LABELS[item] for item in label.reason_codes)
    behaviors = ", ".join(BEHAVIOR_LABELS[item] for item in label.behavior_codes)
    topics = ", ".join(TOPIC_LABELS[item] for item in label.topic_tags)
    return (
        f"{STANCE_LABELS[label.stance]}으로 분류되었습니다. 주요 이유는 {reasons}입니다. "
        f"이후 행동은 {behaviors}으로 예상됩니다. 관련 주제는 {topics}입니다."
    )


def _redact(text: str) -> str:
    redacted = _EMAIL.sub("[이메일 제거]", text)
    redacted = _URL.sub("[링크 제거]", redacted)
    redacted = _HANDLE.sub("[계정 제거]", redacted)
    redacted = _LONG_ID.sub("[식별자 제거]", redacted)
    redacted = _STEAM_MARKUP.sub(" ", redacted)
    return _SPACE.sub(" ", redacted).strip()[:2000]


def _query_terms(query: str) -> list[str]:
    lowered = query.lower()
    terms = re.findall(r"[0-9A-Za-z가-힣_]{2,}", lowered)
    for key, aliases in QUERY_ALIASES.items():
        if key in lowered:
            terms.extend(aliases)
    return list(dict.fromkeys(terms))


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PUBG Steam 비식별 코퍼스 빌더")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_hy = subparsers.add_parser(
        "build-hy", help="Hy의 로컬 원본 DB를 안전한 코퍼스로 변환합니다"
    )
    build_hy.add_argument("--source-db", type=Path, required=True)
    build_hy.add_argument("--db", type=Path, default=DEFAULT_DB)
    build_hy.add_argument("--target-per-language", type=int, default=500)
    build_hy.add_argument("--batch-size", type=int, default=40)
    build_hy.add_argument("--max-pages", type=int, default=20)

    status = subparsers.add_parser("status", help="활성 코퍼스 상태를 확인합니다")
    status.add_argument("--db", type=Path, default=DEFAULT_DB)

    search = subparsers.add_parser("search", help="활성 코퍼스를 검색합니다")
    search.add_argument("query")
    search.add_argument("--db", type=Path, default=DEFAULT_DB)
    search.add_argument("--language", choices=("ko", "en"), required=True)
    search.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    try:
        if args.command == "build-hy":
            _print_json(
                build_from_hy_db(
                    args.source_db,
                    args.db,
                    target_per_language=args.target_per_language,
                    batch_size=args.batch_size,
                    max_pages=args.max_pages,
                )
            )
        elif args.command == "status":
            _print_json(corpus_status(args.db))
        else:
            _print_json(
                [
                    asdict(record)
                    for record in search_corpus(
                        args.query,
                        db_path=args.db,
                        language=args.language,
                        limit=args.limit,
                    )
                ]
            )
    except (CorpusBuildError, OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"오류: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
