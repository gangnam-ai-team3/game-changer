'use strict';

const path = require('path');
const { DatabaseSync } = require('node:sqlite');

const APPID = 578080; // PUBG: BATTLEGROUNDS (고정)
const DB_PATH = path.join(__dirname, 'steam-reviews.db');

const STEAM_LANGUAGE_CODES = [
  'english', 'koreana', 'japanese', 'schinese', 'tchinese', 'russian', 'spanish', 'latam',
  'portuguese', 'brazilian', 'french', 'german', 'italian', 'polish', 'dutch', 'turkish',
  'thai', 'vi', 'indonesian', 'malay', 'arabic', 'ukrainian', 'czech', 'hungarian',
  'romanian', 'bulgarian', 'greek', 'swedish', 'danish', 'finnish', 'norwegian',
];

// 사용법: node collector.js [분] → 백필(처음부터 끝까지, 이미 완료된 언어는 건너뜀)
//        node collector.js sync [분] → 동기화(이미 DB에 있는 리뷰를 만나면 그 언어는 즉시 멈춤 — 새 리뷰만 추가)
//        나중에 하루 1회/1시간 1회로 자동 반복하려면, 이 sync 모드를 cron 등 외부 스케줄러로 주기 실행하면 된다
//        (이 파일 자체는 상시로 계속 도는 프로세스가 아니라, 실행할 때마다 한 번 돌고 끝난다).
const MODE = process.argv[2] === 'sync' ? 'sync' : 'backfill';
const RUN_MINUTES = Number((MODE === 'sync' ? process.argv[3] : process.argv[2]) || 30);
const DEADLINE = Date.now() + RUN_MINUTES * 60 * 1000;

function openDb() {
  const db = new DatabaseSync(DB_PATH);
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
    CREATE TABLE IF NOT EXISTS collector_state (
      language TEXT PRIMARY KEY,
      done INTEGER NOT NULL DEFAULT 0,
      last_cursor TEXT,
      updated_at INTEGER,
      last_synced_at INTEGER
    );
  `);
  try {
    db.exec('ALTER TABLE collector_state ADD COLUMN last_synced_at INTEGER');
  } catch (err) {
    // 이미 컬럼이 있으면(다음 실행부터) 에러가 나는데, SQLite는 "IF NOT EXISTS"를 컬럼 단위로 지원하지 않아 무시한다.
  }
  return db;
}

async function collectLanguage(db, language, stats) {
  const insert = db.prepare(`
    INSERT OR IGNORE INTO reviews
      (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const upsertState = db.prepare(`
    INSERT INTO collector_state (language, done, last_cursor, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(language) DO UPDATE SET done = excluded.done, last_cursor = excluded.last_cursor, updated_at = excluded.updated_at
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

  try {
    while (Date.now() < DEADLINE) {
      const url =
        `https://store.steampowered.com/appreviews/${APPID}?json=1&filter=recent&language=${language}` +
        `&num_per_page=100&purchase_type=all&filter_offtopic_activity=0&cursor=${encodeURIComponent(cursor)}`;
      let data;
      try {
        const res = await fetch(url);
        if (!res.ok) {
          stats.errors.push(`${language}: HTTP ${res.status}`);
          break;
        }
        data = await res.json();
      } catch (err) {
        stats.errors.push(`${language}: ${err.message}`);
        break;
      }

      const batch = data.reviews || [];
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
        done = true;
        break;
      }
      cursor = data.cursor;
      // 매 페이지마다 진행 상태를 저장해서, 중간에 죽어도 다음 실행이 여기서부터 이어갈 수 있게 함
      upsertState.run(language, 0, cursor, Date.now());
    }
  } finally {
    upsertState.run(language, done ? 1 : 0, cursor, Date.now());
  }

  stats.perLanguage[language] = { pages, inserted, oldestTs, newestTs, done };
}

// 동기화 모드: 최신순으로 훑다가 "이미 DB에 있는 리뷰"를 만나면 그 언어는 바로 멈춘다.
// 그 뒤로는(더 과거) 지난번에 이미 다 확인한 구간이라 다시 훑을 필요가 없기 때문이다.
// 나중에 하루 1회/1시간 1회로 자동 반복하려는 목적의 모드라, 처음 몇 페이지만 보고 금방 끝나는 게 정상이다.
async function syncLanguage(db, language, stats) {
  const insert = db.prepare(`
    INSERT OR IGNORE INTO reviews
      (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const existsStmt = db.prepare('SELECT 1 FROM reviews WHERE recommendationid = ?');
  const touchSynced = db.prepare(`
    INSERT INTO collector_state (language, done, last_cursor, updated_at, last_synced_at)
    VALUES (?, 0, NULL, ?, ?)
    ON CONFLICT(language) DO UPDATE SET last_synced_at = excluded.last_synced_at
  `);

  let cursor = '*';
  let pages = 0;
  let inserted = 0;
  let caughtUp = false;

  while (Date.now() < DEADLINE) {
    const url =
      `https://store.steampowered.com/appreviews/${APPID}?json=1&filter=recent&language=${language}` +
      `&num_per_page=100&purchase_type=all&filter_offtopic_activity=0&cursor=${encodeURIComponent(cursor)}`;
    let data;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        stats.errors.push(`${language}: HTTP ${res.status}`);
        break;
      }
      data = await res.json();
    } catch (err) {
      stats.errors.push(`${language}: ${err.message}`);
      break;
    }

    const batch = data.reviews || [];
    if (batch.length === 0) break; // 리뷰가 아예 없는 언어 — 이미 다 아는 상태와 같음
    pages += 1;

    const now = Date.now();
    for (const r of batch) {
      if (existsStmt.get(String(r.recommendationid))) {
        caughtUp = true;
        break;
      }
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
    }

    if (caughtUp || !data.cursor || data.cursor === cursor) break;
    cursor = data.cursor;
  }

  touchSynced.run(language, Date.now(), Date.now());
  stats.perLanguage[language] = { pages, inserted, caughtUp };
}

async function main() {
  const db = openDb();
  const stats = { perLanguage: {}, errors: [] };

  console.log(`${MODE === 'sync' ? '동기화(새 리뷰만)' : '백필'} 시작: appid=${APPID}, 최대 ${RUN_MINUTES}분간 실행, DB=${DB_PATH}`);

  const runOne = MODE === 'sync' ? syncLanguage : collectLanguage;
  await Promise.all(STEAM_LANGUAGE_CODES.map((lang) => runOne(db, lang, stats)));

  const totalRow = db.prepare('SELECT COUNT(*) AS c, MIN(timestamp_created) AS minTs, MAX(timestamp_created) AS maxTs FROM reviews').get();
  const fs = require('fs');
  const fileSize = fs.statSync(DB_PATH).size;

  console.log('=== 수집 완료 ===');
  console.log('총 저장 건수(DB 전체):', totalRow.c);
  console.log('가장 오래된 리뷰:', new Date(totalRow.minTs * 1000).toISOString());
  console.log('가장 최신 리뷰:', new Date(totalRow.maxTs * 1000).toISOString());
  console.log('DB 파일 크기(byte):', fileSize, '(' + (fileSize / 1024 / 1024).toFixed(2) + ' MB)');
  console.log('언어별 상세:', JSON.stringify(stats.perLanguage, null, 2));
  if (stats.errors.length) console.log('오류:', JSON.stringify(stats.errors, null, 2));

  db.close();
}

main().catch((err) => {
  console.error('수집기 실패:', err);
  process.exit(1);
});
