'use strict';

// hy 담당(수집) 파트의 핵심 파이프라인 — Anthropic API(Claude)를 전혀 쓰지 않는다.
//
//   ① 전체 수집(collector.js, 별도 실행) → DB
//   ② 사용자가 정한 기간에 맞는 리뷰만 추리기
//   ③ 너무 짧은 리뷰 삭제 + 근접중복 리뷰를 하나로 병합
//   ④ 남은 리뷰마다 벡터화(통계적 해싱 트릭 — 신경망 아님)
//
// 언어별 "너무 짧다"의 기준(글자 수)은 아래 CJK_MIN_TEXT_LENGTH / DEFAULT_MIN_TEXT_LENGTH 참고.
// 사람이 보기 좋은 문서(hy/README.md)에도 같은 숫자를 적어 두었으니, 기준을 바꾸면 두 곳 다 맞춰야 한다.

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { STEAM_LANGUAGE_CODES, resolveSteamAppId, openReadOnlyDb } = require('./steam-db.js');

const STEAM_REVIEW_TEXT_LIMIT = 1000; // 리뷰 하나당 담아갈 텍스트 길이 상한(문자)
const SIMILARITY_THRESHOLD = 0.9; // hy.md 3번 게이트 "유사도90%+"

// 원본 steamid는 절대 결과에 남기지 않는다 — 단방향 해시로 치환한다(같은 사람인지는 판단 가능,
// 역으로 실제 계정을 알아낼 수는 없음). hy.md의 "작성자 식별정보를 근거ID로 치환" 원칙과 같은 방식.
//
// steamid는 "7656119로 시작하는 17자리 숫자"처럼 형식이 정해져 있어서, 소금(salt) 없이 그냥
// sha256(steamid)만 하면 공격자가 있을 법한 steamid를 미리 다 해시해 둔 표(레인보우 테이블)로
// 역추적할 수 있다. 그래서 아무도 모르는 소금값을 섞는다 — 이 소금 파일은 절대 공유/커밋하지 않는다.
const HASH_SALT_PATH = path.join(__dirname, '.hash-salt');

function loadOrCreateHashSalt() {
  try {
    const existing = fs.readFileSync(HASH_SALT_PATH, 'utf8').trim();
    // 형식이 깨진(잘리거나 손상된) salt를 그대로 쓰면 해시가 뒤죽박죽되므로, 64자리 hex가
    // 아니면 손상된 것으로 보고 새로 만든다(조용히 잘못된 값을 쓰지 않는다).
    if (/^[0-9a-f]{64}$/.test(existing)) return existing;
    throw new Error('salt 형식이 올바르지 않음');
  } catch (err) {
    const salt = crypto.randomBytes(32).toString('hex');
    fs.writeFileSync(HASH_SALT_PATH, salt, { mode: 0o600 });
    return salt;
  }
}

const HASH_SALT = loadOrCreateHashSalt();

function hashAuthor(steamid) {
  if (!steamid) return null;
  return crypto.createHash('sha256').update(HASH_SALT + String(steamid)).digest('hex').slice(0, 16);
}

// "작성자ID+시간창" 중복 판정 기준 — 같은 작성자(해시 기준)가 이 시간 안에 또 올렸으면 중복으로 본다.
const AUTHOR_TIME_WINDOW_SECONDS = 30 * 60; // 30분

// 한국어·중국어·일본어는 음절/한자 하나에 뜻이 압축돼 있어, 같은 글자 수라도 완결된 문장일 확률이 훨씬 높다
// (실측: "핵쟁이 진짜 많아요" 10자, "外挂太多了真的" 7자, "チーターが多すぎる" 9자 모두 완결된 문장인데
// 영어로 같은 뜻은 26자 필요). 그래서 이 언어들만 최소 길이 기준을 낮춘다.
const CJK_LANGUAGES = new Set(['koreana', 'schinese', 'tchinese', 'japanese']);
const CJK_MIN_TEXT_LENGTH = 8;
const DEFAULT_MIN_TEXT_LENGTH = 20;

function minTextLengthFor(language) {
  return CJK_LANGUAGES.has(language) ? CJK_MIN_TEXT_LENGTH : DEFAULT_MIN_TEXT_LENGTH;
}

function normalizeForSimilarity(text) {
  return (text || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function trigramSet(text) {
  const normalized = normalizeForSimilarity(text);
  const set = new Set();
  if (normalized.length < 3) {
    if (normalized.length > 0) set.add(normalized);
    return set;
  }
  for (let i = 0; i <= normalized.length - 3; i += 1) {
    set.add(normalized.slice(i, i + 3));
  }
  return set;
}

function jaccardSimilarity(setA, setB) {
  if (setA.size === 0 && setB.size === 0) return 1;
  let intersection = 0;
  const [smaller, larger] = setA.size <= setB.size ? [setA, setB] : [setB, setA];
  for (const gram of smaller) {
    if (larger.has(gram)) intersection += 1;
  }
  const union = setA.size + setB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// 리뷰가 많은 언어(영어 등)에서 전체를 서로 한 번씩 비교(O(n²))하면 너무 느려진다(4,000건이면
// 약 800만 회 비교). 그래서 먼저 ①완전히 같은 텍스트는 해시로 즉시 병합(O(n))하고, ②남은 건
// "같은 언어 + 작성 시각 순으로 정렬 후 바로 인접한 N건까지만" 문자 유사도를 비교한다(근접중복은
// 보통 비슷한 시기에 몰려서 올라오므로, 멀리 떨어진 건까지 비교할 필요가 적다). 그래도 비교 횟수가
// 상한을 넘으면 truncated=true로 표시하고 중단한다(감으로 자르지 않고, 숫자 상한으로 자름).
const NEAR_DUP_WINDOW = 50;
const MAX_COMPARISONS = 200000;

// 완전히 같은 정규화 텍스트끼리 먼저 묶는다 — 이 안에서는 트라이그램 비교가 필요 없다(이미 100% 동일).
function exactDuplicateGroups(rows) {
  const byText = new Map();
  for (const r of rows) {
    const key = normalizeForSimilarity(r.review);
    if (!byText.has(key)) byText.set(key, []);
    byText.get(key).push(r);
  }
  const exactPairs = [];
  for (const group of byText.values()) {
    for (let i = 1; i < group.length; i += 1) {
      exactPairs.push({ a: group[0].recommendationid, b: group[i].recommendationid, reason: 'exactMatch' });
    }
  }
  return exactPairs;
}

// 같은 언어권 안에서만 비교한다(번역돼서 다른 언어로 재게시되는 경우는 범위 밖).
// 반환값: { pairs, truncated } — truncated=true면 비교 상한에 걸려 일부 근접중복을 못 찾았을 수 있음.
function findSimilarPairs(rows) {
  const sorted = [...rows].sort((a, b) => a.timestamp_created - b.timestamp_created);
  const grams = sorted.map((r) => trigramSet(r.review));
  const pairs = [];
  let comparisons = 0;
  let truncated = false;
  for (let i = 0; i < sorted.length && !truncated; i += 1) {
    const upper = Math.min(i + 1 + NEAR_DUP_WINDOW, sorted.length);
    for (let j = i + 1; j < upper; j += 1) {
      if (comparisons >= MAX_COMPARISONS) {
        truncated = true;
        break;
      }
      comparisons += 1;
      const sim = jaccardSimilarity(grams[i], grams[j]);
      if (sim >= SIMILARITY_THRESHOLD) {
        pairs.push({ a: sorted[i].recommendationid, b: sorted[j].recommendationid, similarity: Math.round(sim * 1000) / 1000 });
      }
    }
  }
  return { pairs, truncated };
}

// 같은 작성자(해시 기준)가 짧은 시간 안에 또 올린 경우도 중복 후보로 잡는다 — 문자 유사도가 낮아도
// (예: 완전히 다른 말로 다시 씀) 같은 사람이 시간 몰아서 올린 반복 게시는 이걸로 잡을 수 있다.
function findAuthorTimeWindowPairs(rows) {
  const byAuthor = new Map();
  for (const r of rows) {
    if (!r.authorHash) continue;
    if (!byAuthor.has(r.authorHash)) byAuthor.set(r.authorHash, []);
    byAuthor.get(r.authorHash).push(r);
  }

  const pairs = [];
  for (const group of byAuthor.values()) {
    for (let i = 0; i < group.length; i += 1) {
      for (let j = i + 1; j < group.length; j += 1) {
        const diff = Math.abs(group[i].timestamp_created - group[j].timestamp_created);
        if (diff <= AUTHOR_TIME_WINDOW_SECONDS) {
          pairs.push({ a: group[i].recommendationid, b: group[j].recommendationid, reason: 'authorTimeWindow' });
        }
      }
    }
  }
  return pairs;
}

// 유사 쌍(A-B, B-C처럼 연결된 것들)을 하나의 그룹으로 묶는다(union-find). AI 판단 없는 순수 그래프 연결 작업.
function mergeDuplicates(rows, similarPairs) {
  const parent = new Map();
  function find(id) {
    if (!parent.has(id)) parent.set(id, id);
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root);
    let cur = id;
    while (parent.get(cur) !== root) {
      const next = parent.get(cur);
      parent.set(cur, root);
      cur = next;
    }
    return root;
  }
  function union(a, b) {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  }

  for (const r of rows) find(r.recommendationid);
  for (const pair of similarPairs) union(pair.a, pair.b);

  const groups = new Map();
  for (const r of rows) {
    const root = find(r.recommendationid);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(r);
  }

  const merged = [];
  for (const group of groups.values()) {
    // 대표건: 가장 정보가 많은(가장 긴) 리뷰를 대표로 남긴다
    const representative = group.reduce((best, r) => (r.review.length > best.review.length ? r : best), group[0]);
    merged.push({
      ...representative,
      duplicateCount: group.length,
      mergedIds: group.map((r) => r.recommendationid).filter((id) => id !== representative.recommendationid),
    });
  }
  return merged;
}

// 통계적 벡터화(해싱 트릭) — 신경망 임베딩이 아니라 3-gram을 고정 길이 숫자 벡터로 접어넣는 순수 계산 방식.
// scikit-learn의 HashingVectorizer 등에서 쓰는 표준 기법과 동일한 원리. 모델/외부 API/다운로드 없이 즉시 계산된다.
const VECTOR_DIMENSIONS = 64;

function hashString(str) {
  let hash = 5381;
  for (let i = 0; i < str.length; i += 1) {
    hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0; // djb2
  }
  return hash >>> 0;
}

function vectorize(text, dims = VECTOR_DIMENSIONS) {
  const grams = trigramSet(text);
  const vector = new Array(dims).fill(0);
  for (const gram of grams) {
    const h = hashString(gram);
    const sign = (h & 1) === 0 ? 1 : -1; // 해시 충돌로 인한 편향을 줄이는 표준 해싱 트릭 기법
    vector[h % dims] += sign;
  }
  const norm = Math.sqrt(vector.reduce((sum, v) => sum + v * v, 0));
  if (norm > 0) {
    for (let i = 0; i < dims; i += 1) vector[i] = Math.round((vector[i] / norm) * 1000) / 1000;
  }
  return vector;
}

// 원본 DB(steamid 컬럼)와 비식별화 사본 DB(author_hash 컬럼) 둘 다 그대로 조회할 수 있게 스키마를 감지한다.
// 사본 DB를 공유해도 받는 쪽이 이 코드로 자기가 원하는 기간·언어로 계속 자유롭게 조회할 수 있게 하기 위함.
function detectAuthorColumn(db) {
  const columns = db.prepare('PRAGMA table_info(reviews)').all().map((c) => c.name);
  if (columns.includes('steamid')) return 'steamid';
  if (columns.includes('author_hash')) return 'author_hash';
  throw new Error('reviews 테이블에 steamid/author_hash 컬럼이 모두 없습니다 — DB 스키마를 확인하세요.');
}

// hy가 지금 수집하는 게임은 PUBG 하나뿐이다. 다른 appid가 들어오면 "리뷰 0건이라 완료됨"처럼
// 착각하기 쉬운 결과를 주지 않고, 아예 지원하지 않는 대상이라고 명확히 알려준다.
const SUPPORTED_APPID = 578080;

// 수집 상태를 단순 boolean이 아니라 네 가지로 구분한다:
//  - complete   : 이 언어권이 요청 기간까지 완전히 수집됨(또는 이미 끝까지 백필 완료)
//  - partial    : 지난 수집/동기화 실행에서 오류가 있었음(일부만 믿을 수 있음)
//  - incomplete : 아직 요청 기간까지 수집이 안 끝남(더 과거 쪽)
//  - unknown    : 이 언어권에 대한 수집 상태 기록 자체가 없음(한 번도 수집 안 함)
function computeCollectionStatus({ state, earliestMs, periodStartMs }) {
  if (!state) return 'unknown';
  if (state.last_run_had_errors) return 'partial';
  if (state.done || earliestMs === null || periodStartMs >= earliestMs) return 'complete';
  return 'incomplete';
}

// collector_state의 last_run_had_errors 컬럼은 이번 개정에서 새로 추가됐다. collector.js를
// 아직 다시 안 돌려서 예전 스키마 그대로인 DB(또는 그런 DB로 만든 사본)를 읽기 전용으로 열어도
// 깨지지 않도록, 있으면 쓰고 없으면 빠진 컬럼 취급(항상 0)한다 — detectAuthorColumn과 같은 패턴.
function detectCollectorStateHasErrorTracking(db) {
  const columns = db.prepare('PRAGMA table_info(collector_state)').all().map((c) => c.name);
  return columns.includes('last_run_had_errors');
}

// ②③④를 한 언어권에 대해 실행한다.
function prepareLanguage({ db, appid, language, periodStartMs, periodEndMs, authorColumn, hasErrorTracking }) {
  const periodStartSec = Math.floor(periodStartMs / 1000);
  const periodEndSec = Math.floor(periodEndMs / 1000); // 기준일(cutoff) — 이 시각은 포함하지 않는다.

  const stateStmt = db.prepare(
    hasErrorTracking
      ? 'SELECT done, last_run_had_errors, last_synced_at FROM collector_state WHERE language = ?'
      : 'SELECT done, 0 AS last_run_had_errors, last_synced_at FROM collector_state WHERE language = ?'
  );
  const state = stateStmt.get(language);

  const earliestStmt = db.prepare('SELECT MIN(timestamp_created) AS minTs FROM reviews WHERE appid = ? AND language = ?');
  const earliest = earliestStmt.get(appid, language);
  const earliestMs = earliest.minTs !== null ? earliest.minTs * 1000 : null;
  const collectionStatus = computeCollectionStatus({ state, earliestMs, periodStartMs });
  // 완료 판단의 근거가 된 값들을 그대로 노출한다(문서 3.6) — 호출하는 쪽이 "언제 기준으로 이 상태인지"
  // 직접 확인할 수 있게.
  const oldestReachedAt = earliestMs === null ? null : new Date(earliestMs).toISOString();
  const lastSyncedAt = state && state.last_synced_at ? new Date(state.last_synced_at).toISOString() : null;
  const snapshotAt = new Date().toISOString();

  // 기준일(cutoff) 보호: 시작은 포함(>=)하되 기준일 자체는 제외(<)한다. 작성일뿐 아니라 수정일도
  // 기준일 이후면 제외한다(원래 더 이전에 써놓고 기준일 지나서 고친 리뷰가 섞여 들어가지 않도록).
  const selectStmt = db.prepare(
    `SELECT recommendationid, language, review, voted_up, timestamp_created, timestamp_updated, ${authorColumn}, playtime_forever_minutes
     FROM reviews
     WHERE appid = ? AND language = ?
       AND timestamp_created >= ? AND timestamp_created < ?
       AND (timestamp_updated IS NULL OR timestamp_updated < ?)
     ORDER BY timestamp_created DESC`
  );
  const rawRows = selectStmt.all(appid, language, periodStartSec, periodEndSec, periodEndSec).map((r) => ({
    recommendationid: r.recommendationid,
    // steamid 원본이면 여기서 해시로 치환, 이미 author_hash(비식별화 사본 DB)면 그대로 사용
    authorHash: authorColumn === 'steamid' ? hashAuthor(r.steamid) : r.author_hash,
    language: r.language,
    review: (r.review || '').slice(0, STEAM_REVIEW_TEXT_LIMIT),
    voted_up: !!r.voted_up,
    timestamp_created: r.timestamp_created,
    playtime_forever_minutes: r.playtime_forever_minutes,
  }));

  const minLen = minTextLengthFor(language);
  const longEnough = rawRows.filter((r) => normalizeForSimilarity(r.review).length >= minLen);
  const tooShortRemoved = rawRows.length - longEnough.length;

  // 중복 판정 세 가지를 합친다: ① 완전 동일 텍스트(해시, O(n)) ② 텍스트 유사도 90%+(제한된 인접 구간만)
  // ③ 같은 작성자(해시)가 시간창 이내 재게시
  const exactPairs = exactDuplicateGroups(longEnough);
  const { pairs: similarPairs, truncated } = findSimilarPairs(longEnough);
  const authorPairs = findAuthorTimeWindowPairs(longEnough);
  const merged = mergeDuplicates(longEnough, exactPairs.concat(similarPairs, authorPairs));
  const evidence = merged.map((item) => ({ ...item, vector: vectorize(item.review) }));

  return {
    language,
    collectionStatus,
    appId: appid,
    oldestReachedAt,
    lastSyncedAt,
    snapshotAt,
    rawInPeriod: rawRows.length,
    tooShortRemoved,
    duplicatesMerged: longEnough.length - merged.length,
    finalCount: evidence.length,
    dedupTruncated: truncated,
    evidence,
  };
}

// hy 담당 파트의 진입점. Claude를 전혀 부르지 않는다 — 여기서 반환된 evidence를 다음 단계(res 등)로 넘기면 된다.
// dbPath를 안 주면 원본 로컬 DB를 쓰고, 비식별화 사본(export-anon-db.js가 만든 것)의 경로를 주면 그걸 대신 조회한다 —
// 둘 다 같은 방식으로 자유롭게 기간/언어를 바꿔가며 반복 조회할 수 있다.
async function prepareEvidence({ gameName, periodStartMs, periodEndMs, languages, dbPath }) {
  if (!(Number.isFinite(periodStartMs) && Number.isFinite(periodEndMs) && periodStartMs < periodEndMs)) {
    return { found: false, error: '조회 시작일이 종료일(기준일)보다 늦거나 같습니다.' };
  }

  const resolved = await resolveSteamAppId(gameName);
  if (!resolved) {
    return { found: false, gameName };
  }
  const { appid, matchedName } = resolved;

  if (appid !== SUPPORTED_APPID) {
    return { found: false, gameName, matchedName, appid, error: '지원하지 않는 게임입니다(현재 PUBG: BATTLEGROUNDS만 수집함).' };
  }

  const db = openReadOnlyDb(dbPath);
  if (!db) {
    return { found: true, appid, matchedName, dbMissing: true, perLanguage: [], evidence: [] };
  }

  try {
    const authorColumn = detectAuthorColumn(db);
    const hasErrorTracking = detectCollectorStateHasErrorTracking(db);
    const targetLanguages =
      Array.isArray(languages) && languages.length > 0
        ? languages.filter((code) => STEAM_LANGUAGE_CODES.includes(code))
        : STEAM_LANGUAGE_CODES;

    const perLanguage = targetLanguages.map((language) =>
      prepareLanguage({ db, appid, language, periodStartMs, periodEndMs, authorColumn, hasErrorTracking })
    );

    const evidence = perLanguage.flatMap((p) => p.evidence);
    const summary = perLanguage.map(
      ({
        language,
        collectionStatus,
        appId,
        oldestReachedAt,
        lastSyncedAt,
        snapshotAt,
        rawInPeriod,
        tooShortRemoved,
        duplicatesMerged,
        finalCount,
        dedupTruncated,
      }) => ({
        language,
        collectionStatus,
        appId,
        oldestReachedAt,
        lastSyncedAt,
        snapshotAt,
        rawInPeriod,
        tooShortRemoved,
        duplicatesMerged,
        finalCount,
        dedupTruncated,
      })
    );

    return {
      found: true,
      appid,
      matchedName,
      perLanguage: summary,
      totalRaw: perLanguage.reduce((s, p) => s + p.rawInPeriod, 0),
      totalFinal: evidence.length,
      evidence,
    };
  } finally {
    db.close();
  }
}

module.exports = {
  prepareEvidence,
  findSimilarPairs,
  exactDuplicateGroups,
  findAuthorTimeWindowPairs,
  mergeDuplicates,
  vectorize,
  hashAuthor,
  detectAuthorColumn,
  minTextLengthFor,
  computeCollectionStatus,
  CJK_MIN_TEXT_LENGTH,
  DEFAULT_MIN_TEXT_LENGTH,
  AUTHOR_TIME_WINDOW_SECONDS,
  NEAR_DUP_WINDOW,
  MAX_COMPARISONS,
  SUPPORTED_APPID,
};
