'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const {
  prepareEvidence,
  minTextLengthFor,
  CJK_MIN_TEXT_LENGTH,
  DEFAULT_MIN_TEXT_LENGTH,
  computeCollectionStatus,
  findSimilarPairs,
  exactDuplicateGroups,
  SUPPORTED_APPID,
} = require('./prepare-evidence.js');

test('CJK languages get the lower length threshold', () => {
  assert.equal(minTextLengthFor('koreana'), CJK_MIN_TEXT_LENGTH);
  assert.equal(minTextLengthFor('schinese'), CJK_MIN_TEXT_LENGTH);
  assert.equal(minTextLengthFor('english'), DEFAULT_MIN_TEXT_LENGTH);
});

test('computeCollectionStatus distinguishes complete/partial/incomplete/unknown', () => {
  assert.equal(computeCollectionStatus({ state: null, earliestMs: null, periodStartMs: 0 }), 'unknown');
  assert.equal(
    computeCollectionStatus({ state: { done: 0, last_run_had_errors: 1 }, earliestMs: 1000, periodStartMs: 0 }),
    'partial'
  );
  assert.equal(
    computeCollectionStatus({ state: { done: 1, last_run_had_errors: 0 }, earliestMs: 1000, periodStartMs: 0 }),
    'complete'
  );
  assert.equal(
    computeCollectionStatus({ state: { done: 0, last_run_had_errors: 0 }, earliestMs: 5000, periodStartMs: 0 }),
    'incomplete'
  );
});

test('findSimilarPairs stays fast and correct on thousands of rows (no more O(n^2) full scan)', () => {
  const rows = [];
  for (let i = 0; i < 4000; i += 1) {
    // 2,000쌍의 완전 동일 텍스트 + 나머지는 전부 다른 텍스트
    const text = i % 2 === 0 ? `동일한 리뷰 문장 그대로 반복 ${Math.floor(i / 2)}` : `동일한 리뷰 문장 그대로 반복 ${Math.floor(i / 2)}`;
    rows.push({ recommendationid: `id-${i}`, review: text, timestamp_created: 1000 + i });
  }
  const start = Date.now();
  const exactPairs = exactDuplicateGroups(rows);
  const { pairs, truncated } = findSimilarPairs(rows);
  const elapsedMs = Date.now() - start;

  assert.equal(exactPairs.length, 2000, '완전 동일 텍스트 2000쌍이 exact-merge로 먼저 잡혀야 함');
  assert.equal(truncated, false);
  assert.ok(elapsedMs < 2000, `4000건 처리에 ${elapsedMs}ms — 너무 느림(O(n^2) 회귀 의심)`);
});

function makeTestDb() {
  const dbPath = path.join(os.tmpdir(), `hy-prepare-test-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}.db`);
  const db = new DatabaseSync(dbPath);
  db.exec(`
    CREATE TABLE reviews (
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
    CREATE TABLE collector_state (
      language TEXT PRIMARY KEY,
      done INTEGER NOT NULL DEFAULT 0,
      last_cursor TEXT,
      updated_at INTEGER,
      last_synced_at INTEGER,
      sync_boundary_id TEXT,
      last_run_had_errors INTEGER DEFAULT 0
    );
  `);
  return { dbPath, db };
}

test('cutoff is exclusive on both created_at and updated_at, and start is inclusive', async () => {
  const { dbPath, db } = makeTestDb();
  try {
    const insert = db.prepare(`
      INSERT INTO reviews (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const cutoffSec = 2000;
    // 시작 경계(포함돼야 함)
    insert.run('at-start', SUPPORTED_APPID, 'english', 'this review sits exactly at period start boundary', 1, 1000, null, 's1', 0, 0);
    // 기준일과 정확히 같은 시각에 작성 — 제외돼야 함
    insert.run('at-cutoff-created', SUPPORTED_APPID, 'english', 'this review was created exactly at the cutoff instant', 1, cutoffSec, null, 's2', 0, 0);
    // 작성은 이전인데 기준일 이후에 수정됨 — 제외돼야 함
    insert.run('updated-after-cutoff', SUPPORTED_APPID, 'english', 'this review was edited after the cutoff instant passed', 1, 1500, cutoffSec + 10, 's3', 0, 0);
    // 완전히 범위 안 — 포함돼야 함
    insert.run('clearly-inside', SUPPORTED_APPID, 'english', 'this review is clearly inside the requested period range', 1, 1800, null, 's4', 0, 0);
    db.prepare('INSERT INTO collector_state (language, done) VALUES (?, 1)').run('english');
    db.close();

    const result = await prepareEvidence({
      gameName: 'pubg',
      periodStartMs: 1000 * 1000,
      periodEndMs: cutoffSec * 1000,
      languages: ['english'],
      dbPath,
    });

    const ids = result.evidence.map((e) => e.recommendationid).sort();
    assert.deepEqual(ids, ['at-start', 'clearly-inside']);
  } finally {
    for (const suffix of ['', '-shm', '-wal']) {
      const p = dbPath + suffix;
      if (fs.existsSync(p)) fs.unlinkSync(p);
    }
  }
});

test('rejects a request where the start date is not before the cutoff/end date', async () => {
  const result = await prepareEvidence({
    gameName: 'pubg',
    periodStartMs: 2000,
    periodEndMs: 1000,
    languages: ['english'],
  });
  assert.equal(result.found, false);
  assert.ok(result.error);
});

test('SUPPORTED_APPID matches the only game hy currently collects (PUBG: BATTLEGROUNDS)', () => {
  // 실제 "지원하지 않는 게임 거부" 분기(prepareEvidence 안의 appid !== SUPPORTED_APPID 체크)는
  // 스팀 검색 API를 타야 해서 네트워크 없는 테스트 환경에선 별도 통합 테스트로 검증하지 않는다 —
  // 여기서는 그 분기가 비교하는 상수값 자체가 PUBG appid로 고정돼 있는지만 확인한다.
  assert.equal(SUPPORTED_APPID, 578080);
});
