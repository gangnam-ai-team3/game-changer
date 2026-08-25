'use strict';

const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

const APPID = 578080; // PUBG: BATTLEGROUNDS (고정)
const DB_PATH = path.join(__dirname, 'steam-reviews.db');

const STEAM_LANGUAGE_CODES = [
  'english', 'koreana', 'japanese', 'schinese', 'tchinese', 'russian', 'spanish', 'latam',
  'portuguese', 'brazilian', 'french', 'german', 'italian', 'polish', 'dutch', 'turkish',
  'thai', 'vietnamese', 'indonesian', 'malay', 'arabic', 'ukrainian', 'czech', 'hungarian',
  'romanian', 'bulgarian', 'greek', 'swedish', 'danish', 'finnish', 'norwegian',
];

// 사용법: node collector.js [분] → 백필(처음부터 끝까지, 이미 완료된 언어는 건너뜀)
//        node collector.js sync [분] → 동기화(경계 ID까지만 훑고, 새 리뷰는 삽입·수정된 리뷰는 갱신)
//        나중에 하루 1회/1시간 1회로 자동 반복하려면, 이 sync 모드를 cron 등 외부 스케줄러로 주기 실행하면 된다
//        (이 파일 자체는 상시로 계속 도는 프로세스가 아니라, 실행할 때마다 한 번 돌고 끝난다).
const MODE = process.argv[2] === 'sync' ? 'sync' : 'backfill';
const RUN_MINUTES = Number((MODE === 'sync' ? process.argv[3] : process.argv[2]) || 30);
const DEADLINE = Date.now() + RUN_MINUTES * 60 * 1000;

function openDb(dbPath = DB_PATH) {
  const db = new DatabaseSync(dbPath);
  // WAL 모드: 이 프로세스가 쓰는 동안에도 다른 프로세스가 동시에 읽기 조회를 할 수 있게 함
  // (이전에 상태 확인 쿼리가 "database is locked"로 전체 작업을 죽인 문제의 원인)
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec(`
    CREATE TABLE IF NOT EXISTS reviews (
      recommendationid TEXT PRIMARY KEY,
      appid INTEGER NOT NULL,
      language TEXT NOT NULL,
      review TEXT,
      voted_up INTEGER,
      timestamp_created INTEGER NOT NULL,
      timestamp_updated INTEGER,
      steamid TEXT,
      playtime_forever_minutes INTEGER,
      collected_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reviews_ts ON reviews(timestamp_created);
    CREATE INDEX IF NOT EXISTS idx_reviews_lang ON reviews(language);
    -- 기간+언어로 동시에 거르는 조회(prepare-evidence.js)가 많아 복합 인덱스를 따로 둔다.
    CREATE INDEX IF NOT EXISTS idx_reviews_app_lang_created ON reviews(appid, language, timestamp_created DESC);
    CREATE TABLE IF NOT EXISTS collector_state (
      language TEXT PRIMARY KEY,
      done INTEGER NOT NULL DEFAULT 0,
      last_cursor TEXT,
      updated_at INTEGER,
      last_synced_at INTEGER
    );
  `);
  // SQLite는 컬럼 단위 "IF NOT EXISTS"를 지원하지 않아, 이미 있으면 나는 에러를 무시하는 방식으로
  // 예전 DB에도 새 컬럼을 안전하게 추가한다(여러 번 실행해도 문제없음).
  for (const stmt of [
    'ALTER TABLE collector_state ADD COLUMN last_synced_at INTEGER',
    'ALTER TABLE collector_state ADD COLUMN sync_boundary_id TEXT',
    'ALTER TABLE collector_state ADD COLUMN last_run_had_errors INTEGER DEFAULT 0',
  ]) {
    try {
      db.exec(stmt);
    } catch (err) {
      // 컬럼이 이미 있으면 여기로 온다 — 정상.
    }
  }

  // 원본 DB엔 실제 steamid가 들어있어 파일 권한을 소유자만 읽고 쓸 수 있게 좁혀둔다
  // (hy/ 폴더 전체가 아니라 DB 파일 자체만 — 폴더는 다른 소스 파일도 같이 들어있는 공용 공간이므로).
  for (const suffix of ['', '-shm', '-wal']) {
    const p = dbPath + suffix;
    if (fs.existsSync(p)) {
      try {
        fs.chmodSync(p, 0o600);
      } catch (err) {
        // 일부 파일시스템/권한 상황에서 chmod가 안 될 수 있음 — best effort.
      }
    }
  }

  return db;
}

// 429/500/503과 네트워크 타임아웃/오류만 제한적으로 재시도한다. 그 외 상태코드는 바로 실패 처리.
async function fetchWithRetry(url, language, stats, maxAttempts = 3) {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let res;
    try {
      res = await fetch(url);
    } catch (err) {
      if (attempt === maxAttempts) {
        stats.errors.push(`${language}: ${err.message}`);
        return null;
      }
      await new Promise((r) => setTimeout(r, 500 * attempt));
      continue;
    }
    if (res.ok) return res;
    if ([429, 500, 503].includes(res.status) && attempt < maxAttempts) {
      await new Promise((r) => setTimeout(r, 500 * attempt));
      continue;
    }
    stats.errors.push(`${language}: HTTP ${res.status}`);
    return null;
  }
  return null;
}

async function parseAndValidate(res, language, stats) {
  const data = await res.json();
  if (data.success !== 1 || !Array.isArray(data.reviews)) {
    stats.errors.push(`${language}: 응답 형식 오류 (success=${data.success})`);
    return null;
  }
  return data;
}

async function collectLanguage(db, language, stats) {
  const insert = db.prepare(`
    INSERT OR IGNORE INTO reviews
      (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const upsertState = db.prepare(`
    INSERT INTO collector_state (language, done, last_cursor, updated_at, last_run_had_errors)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(language) DO UPDATE SET done = excluded.done, last_cursor = excluded.last_cursor,
      updated_at = excluded.updated_at, last_run_had_errors = excluded.last_run_had_errors
  `);

  const existingState = db.prepare('SELECT done, last_cursor FROM collector_state WHERE language = ?').get(language);
  if (existingState && existingState.done) {
    stats.perLanguage[language] = { skipped: true, reason: '이미 끝까지 완료됨(이전 실행에서)' };
    return;
  }

  let cursor = (existingState && existingState.last_cursor) || '*';
  let pages = 0;
  let inserted = 0;
  let oldestTs = null;
  let newestTs = null;
  let done = false;
  let hadError = false;

  try {
    while (Date.now() < DEADLINE) {
      const url =
        `https://store.steampowered.com/appreviews/${APPID}?json=1&filter=recent&language=${language}` +
        `&num_per_page=100&purchase_type=all&filter_offtopic_activity=0&cursor=${encodeURIComponent(cursor)}`;
      const res = await fetchWithRetry(url, language, stats);
      if (!res) {
        hadError = true;
        break;
      }
      const data = await parseAndValidate(res, language, stats);
      if (!data) {
        hadError = true;
        break;
      }

      const batch = data.reviews;
      if (batch.length === 0) {
        done = true;
        break;
      }
      pages += 1;

      const now = Date.now();
      for (const r of batch) {
        const result = insert.run(
          String(r.recommendationid),
          APPID,
          r.language || language,
          r.review || '',
          r.voted_up ? 1 : 0,
          r.timestamp_created,
          r.timestamp_updated || null,
          (r.author && r.author.steamid) || null,
          (r.author && r.author.playtime_forever) || null,
          now
        );
        if (result.changes > 0) inserted += 1;
        if (oldestTs === null || r.timestamp_created < oldestTs) oldestTs = r.timestamp_created;
        if (newestTs === null || r.timestamp_created > newestTs) newestTs = r.timestamp_created;
      }

      if (!data.cursor || data.cursor === cursor) {
        // 리뷰가 있었는데 다음 cursor가 없거나 반복되면 정상 완료가 아니라 오류로 본다.
        stats.errors.push(`${language}: 리뷰는 있는데 다음 cursor가 이상함(오류로 처리)`);
        hadError = true;
        break;
      }
      cursor = data.cursor;
      // 매 페이지마다 진행 상태를 저장해서, 중간에 죽어도 다음 실행이 여기서부터 이어갈 수 있게 함
      upsertState.run(language, 0, cursor, Date.now(), 0);
    }
  } finally {
    upsertState.run(language, done ? 1 : 0, cursor, Date.now(), hadError ? 1 : 0);
  }

  stats.perLanguage[language] = { pages, inserted, oldestTs, newestTs, done, hadError };
  if (hadError) stats.hadAnyError = true;
}

// 동기화 모드: 최신순으로 훑다가 "저장된 경계 ID(sync_boundary_id)"를 만나면 그 언어는 멈춘다.
// 경계 ID는 지난번 sync가 오류 없이 끝났을 때만 갱신되므로, 중간에 실패한 페이지가 있으면
// 다음 실행이 다시 처음부터 그 구간을 훑어 누락을 회복한다. 새 리뷰는 삽입, 이미 아는 리뷰는
// 내용이 바뀌었을 수 있어(수정된 리뷰) UPSERT로 갱신한다.
async function syncLanguage(db, language, stats) {
  const insert = db.prepare(`
    INSERT INTO reviews
      (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(recommendationid) DO UPDATE SET
      review = excluded.review,
      voted_up = excluded.voted_up,
      timestamp_updated = excluded.timestamp_updated,
      playtime_forever_minutes = excluded.playtime_forever_minutes
  `);
  const existsStmt = db.prepare('SELECT 1 FROM reviews WHERE recommendationid = ?');
  const stateRow = db.prepare('SELECT sync_boundary_id FROM collector_state WHERE language = ?').get(language);
  const boundaryId = stateRow ? stateRow.sync_boundary_id : null;
  const touchSynced = db.prepare(`
    INSERT INTO collector_state (language, done, last_cursor, updated_at, last_synced_at, sync_boundary_id, last_run_had_errors)
    VALUES (?, 0, NULL, ?, ?, ?, 0)
    ON CONFLICT(language) DO UPDATE SET last_synced_at = excluded.last_synced_at,
      sync_boundary_id = excluded.sync_boundary_id, last_run_had_errors = 0
  `);

  let cursor = '*';
  let pages = 0;
  let inserted = 0;
  let updated = 0;
  let caughtUp = false;
  let newestSeenId = null;
  let hadError = false;

  while (Date.now() < DEADLINE) {
    const url =
      `https://store.steampowered.com/appreviews/${APPID}?json=1&filter=recent&language=${language}` +
      `&num_per_page=100&purchase_type=all&filter_offtopic_activity=0&cursor=${encodeURIComponent(cursor)}`;
    const res = await fetchWithRetry(url, language, stats);
    if (!res) {
      hadError = true;
      break;
    }
    const data = await parseAndValidate(res, language, stats);
    if (!data) {
      hadError = true;
      break;
    }

    const batch = data.reviews;
    if (batch.length === 0) break; // 리뷰가 아예 없는 언어 — 이미 다 아는 상태와 같음
    pages += 1;

    const now = Date.now();
    for (const r of batch) {
      const id = String(r.recommendationid);
      if (newestSeenId === null) newestSeenId = id;
      if (boundaryId && id === boundaryId) {
        caughtUp = true;
        break;
      }
      const alreadyExisted = !!existsStmt.get(id);
      insert.run(
        id,
        APPID,
        r.language || language,
        r.review || '',
        r.voted_up ? 1 : 0,
        r.timestamp_created,
        r.timestamp_updated || null,
        (r.author && r.author.steamid) || null,
        (r.author && r.author.playtime_forever) || null,
        now
      );
      if (alreadyExisted) updated += 1;
      else inserted += 1;
    }

    if (caughtUp) break;
    if (!data.cursor || data.cursor === cursor) {
      stats.errors.push(`${language}: 다음 cursor가 이상함(오류로 처리)`);
      hadError = true;
      break;
    }
    cursor = data.cursor;
  }

  // 실패 시 경계값/동기화시각을 갱신하지 않는다 — 다음 실행이 실패한 구간을 처음부터 다시 훑도록.
  if (!hadError) {
    touchSynced.run(language, Date.now(), Date.now(), newestSeenId || boundaryId);
  } else {
    stats.hadAnyError = true;
  }
  stats.perLanguage[language] = { pages, inserted, updated, caughtUp, hadError };
}

async function main() {
  const db = openDb();
  const stats = { perLanguage: {}, errors: [], hadAnyError: false };

  console.log(`${MODE === 'sync' ? '동기화(새 리뷰/수정 리뷰)' : '백필'} 시작: appid=${APPID}, 최대 ${RUN_MINUTES}분간 실행, DB=${DB_PATH}`);

  const runOne = MODE === 'sync' ? syncLanguage : collectLanguage;
  await Promise.all(STEAM_LANGUAGE_CODES.map((lang) => runOne(db, lang, stats)));

  const totalRow = db.prepare('SELECT COUNT(*) AS c, MIN(timestamp_created) AS minTs, MAX(timestamp_created) AS maxTs FROM reviews').get();
  const fileSize = fs.statSync(DB_PATH).size;

  console.log('=== 수집 완료 ===');
  console.log('총 저장 건수(DB 전체):', totalRow.c);
  console.log('가장 오래된 리뷰:', new Date(totalRow.minTs * 1000).toISOString());
  console.log('가장 최신 리뷰:', new Date(totalRow.maxTs * 1000).toISOString());
  console.log('DB 파일 크기(byte):', fileSize, '(' + (fileSize / 1024 / 1024).toFixed(2) + ' MB)');
  console.log('언어별 상세:', JSON.stringify(stats.perLanguage, null, 2));
  if (stats.errors.length) console.log('오류:', JSON.stringify(stats.errors, null, 2));

  db.close();

  // 일부 언어라도 오류가 있었으면 "성공적으로 끝났다"고 착각하지 않도록 종료 코드를 0이 아니게 한다
  // (외부 스케줄러가 이 값을 보고 재시도/알림을 판단할 수 있게).
  if (stats.hadAnyError) {
    process.exitCode = 1;
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error('수집기 실패:', err);
    process.exit(1);
  });
}

module.exports = {
  APPID,
  DB_PATH,
  STEAM_LANGUAGE_CODES,
  openDb,
  fetchWithRetry,
  parseAndValidate,
  collectLanguage,
  syncLanguage,
};
