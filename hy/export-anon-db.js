'use strict';

// 원본 DB(hy/steam-reviews.db, steamid 원본 있음)를 통째로 복사하면서 steamid만 author_hash(단방향 해시)로
// 바꾼 공유용 사본을 만든다. 원본은 절대 건드리지 않고 계속 로컬에만 둔다.
//
// 이 사본은 진짜 SQLite DB라서, prepare-evidence.js로 누구든 원하는 기간·언어로 계속 자유롭게 조회할 수 있다
// (prepareEvidence({ ..., dbPath: 이_사본_경로 })). 그래서 "한 번 내보낸 결과 하나"가 아니라, DB를 통째로
// 안전하게 공유하는 방식 — 원본 DB를 만든 목적(자유로운 재조회)을 그대로 유지하면서 개인정보만 뺀다.
//
// 사용법: node export-anon-db.js [출력경로]  (기본값: hy/steam-reviews.anon.db)

const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const { DB_PATH } = require('./steam-db.js');
const { hashAuthor } = require('./prepare-evidence.js');

const OUTPUT_PATH = process.argv[2] || path.join(__dirname, 'steam-reviews.anon.db');

function exportAnonymizedDb(outputPath) {
  if (!fs.existsSync(DB_PATH)) {
    throw new Error(`원본 DB가 없습니다: ${DB_PATH} (먼저 collector.js로 수집해야 합니다)`);
  }
  // 이전에 만든 사본이 있으면 지우고 새로 만든다(항상 최신 원본 기준으로 다시 생성).
  for (const suffix of ['', '-shm', '-wal']) {
    const p = outputPath + suffix;
    if (fs.existsSync(p)) fs.unlinkSync(p);
  }

  const src = new DatabaseSync(DB_PATH, { readOnly: true });
  const dst = new DatabaseSync(outputPath);
  dst.exec('PRAGMA journal_mode = WAL;');
  dst.exec(`
    CREATE TABLE reviews (
      recommendationid TEXT PRIMARY KEY,
      appid INTEGER NOT NULL,
      language TEXT NOT NULL,
      review TEXT,
      voted_up INTEGER,
      timestamp_created INTEGER NOT NULL,
      timestamp_updated INTEGER,
      author_hash TEXT,
      playtime_forever_minutes INTEGER,
      collected_at INTEGER NOT NULL
    );
    CREATE INDEX idx_reviews_ts ON reviews(timestamp_created);
    CREATE INDEX idx_reviews_lang ON reviews(language);
    CREATE TABLE collector_state (
      language TEXT PRIMARY KEY,
      done INTEGER NOT NULL DEFAULT 0,
      last_cursor TEXT,
      updated_at INTEGER,
      last_synced_at INTEGER
    );
  `);

  const insertReview = dst.prepare(`
    INSERT INTO reviews
      (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, author_hash, playtime_forever_minutes, collected_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  // 수십~수백만 행을 한 번에 .all()로 메모리에 다 올리면 메모리 부담이 크므로, iterate()로 한 줄씩 스트리밍한다.
  // 건 단위 자동커밋도 느리므로 트랜잭션 하나로 묶는다.
  let reviewCount = 0;
  dst.exec('BEGIN TRANSACTION');
  try {
    for (const r of src.prepare('SELECT * FROM reviews').iterate()) {
      insertReview.run(
        r.recommendationid,
        r.appid,
        r.language,
        r.review,
        r.voted_up,
        r.timestamp_created,
        r.timestamp_updated,
        hashAuthor(r.steamid), // 원본 steamid는 여기서 끝 — 사본에는 절대 들어가지 않음
        r.playtime_forever_minutes,
        r.collected_at
      );
      reviewCount += 1;
    }
    dst.exec('COMMIT');
  } catch (err) {
    dst.exec('ROLLBACK');
    throw err;
  }

  const insertState = dst.prepare(
    'INSERT INTO collector_state (language, done, last_cursor, updated_at, last_synced_at) VALUES (?, ?, ?, ?, ?)'
  );
  let stateCount = 0;
  for (const s of src.prepare('SELECT * FROM collector_state').all()) {
    insertState.run(s.language, s.done, s.last_cursor, s.updated_at, s.last_synced_at ?? null);
    stateCount += 1;
  }

  src.close();
  dst.close();

  return { outputPath, reviewCount, stateCount };
}

module.exports = { exportAnonymizedDb, OUTPUT_PATH };

if (require.main === module) {
  const result = exportAnonymizedDb(OUTPUT_PATH);
  const size = fs.statSync(result.outputPath).size;
  console.log('비식별화 사본 생성 완료');
  console.log('경로:', result.outputPath);
  console.log('리뷰 건수:', result.reviewCount, '| 언어 상태 건수:', result.stateCount);
  console.log('파일 크기:', (size / 1024 / 1024).toFixed(1), 'MB');
  console.log('(원본 steamid는 이 파일에 없습니다 — author_hash로만 저장됨)');
}
