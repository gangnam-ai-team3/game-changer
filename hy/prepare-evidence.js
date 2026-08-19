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
    return fs.readFileSync(HASH_SALT_PATH, 'utf8').trim();
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

// 같은 언어권 안에서만 비교한다(번역돼서 다른 언어로 재게시되는 경우는 범위 밖).
function findSimilarPairs(rows) {
  const grams = rows.map((r) => trigramSet(r.review));
  const pairs = [];
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = i + 1; j < rows.length; j += 1) {
      const sim = jaccardSimilarity(grams[i], grams[j]);
      if (sim >= SIMILARITY_THRESHOLD) {
        pairs.push({ a: rows[i].recommendationid, b: rows[j].recommendationid, similarity: Math.round(sim * 1000) / 1000 });
      }
    }
  }
  return pairs;
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

// ②③④를 한 언어권에 대해 실행한다.
function prepareLanguage({ db, appid, language, periodStartMs, periodEndMs, authorColumn }) {
  const periodStartSec = Math.floor(periodStartMs / 1000);
  const periodEndSec = Math.floor(periodEndMs / 1000);

  const stateStmt = db.prepare('SELECT done FROM collector_state WHERE language = ?');
  const state = stateStmt.get(language);
  const done = state ? !!state.done : false;

  const earliestStmt = db.prepare('SELECT MIN(timestamp_created) AS minTs FROM reviews WHERE appid = ? AND language = ?');
  const earliest = earliestStmt.get(appid, language);
  const coveredFromMs = earliest.minTs !== null ? earliest.minTs * 1000 : null;
  const collectionComplete = done || coveredFromMs === null || periodStartMs >= coveredFromMs;

  const selectStmt = db.prepare(
    `SELECT recommendationid, language, review, voted_up, timestamp_created, ${authorColumn}, playtime_forever_minutes
     FROM reviews
     WHERE appid = ? AND language = ? AND timestamp_created BETWEEN ? AND ?
     ORDER BY timestamp_created DESC`
  );
  const rawRows = selectStmt.all(appid, language, periodStartSec, periodEndSec).map((r) => ({
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

  // 중복 판정 두 가지를 합친다: ① 텍스트 유사도 90%+ ② 같은 작성자(해시)가 시간창 이내 재게시
  const similarPairs = findSimilarPairs(longEnough);
  const authorPairs = findAuthorTimeWindowPairs(longEnough);
  const merged = mergeDuplicates(longEnough, similarPairs.concat(authorPairs));
  const evidence = merged.map((item) => ({ ...item, vector: vectorize(item.review) }));

  return {
    language,
    collectionComplete,
    rawInPeriod: rawRows.length,
    tooShortRemoved,
    duplicatesMerged: longEnough.length - merged.length,
    finalCount: evidence.length,
    evidence,
  };
}

// hy 담당 파트의 진입점. Claude를 전혀 부르지 않는다 — 여기서 반환된 evidence를 다음 단계(res 등)로 넘기면 된다.
// dbPath를 안 주면 원본 로컬 DB를 쓰고, 비식별화 사본(export-anon-db.js가 만든 것)의 경로를 주면 그걸 대신 조회한다 —
// 둘 다 같은 방식으로 자유롭게 기간/언어를 바꿔가며 반복 조회할 수 있다.
async function prepareEvidence({ gameName, periodStartMs, periodEndMs, languages, dbPath }) {
  const resolved = await resolveSteamAppId(gameName);
  if (!resolved) {
    return { found: false, gameName };
  }
  const { appid, matchedName } = resolved;

  const db = openReadOnlyDb(dbPath);
  if (!db) {
    return { found: true, appid, matchedName, dbMissing: true, perLanguage: [], evidence: [] };
  }

  try {
    const authorColumn = detectAuthorColumn(db);
    const targetLanguages =
      Array.isArray(languages) && languages.length > 0
        ? languages.filter((code) => STEAM_LANGUAGE_CODES.includes(code))
        : STEAM_LANGUAGE_CODES;

    const perLanguage = targetLanguages.map((language) =>
      prepareLanguage({ db, appid, language, periodStartMs, periodEndMs, authorColumn })
    );

    const evidence = perLanguage.flatMap((p) => p.evidence);
    const summary = perLanguage.map(({ language, collectionComplete, rawInPeriod, tooShortRemoved, duplicatesMerged, finalCount }) => ({
      language,
      collectionComplete,
      rawInPeriod,
      tooShortRemoved,
      duplicatesMerged,
      finalCount,
    }));

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
  findAuthorTimeWindowPairs,
  mergeDuplicates,
  vectorize,
  hashAuthor,
  detectAuthorColumn,
  minTextLengthFor,
  CJK_MIN_TEXT_LENGTH,
  DEFAULT_MIN_TEXT_LENGTH,
  AUTHOR_TIME_WINDOW_SECONDS,
};
