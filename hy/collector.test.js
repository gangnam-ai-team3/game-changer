'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { openDb, syncLanguage } = require('./collector.js');

function tmpDbPath() {
  return path.join(os.tmpdir(), `hy-collector-test-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}.db`);
}

function cleanup(dbPath) {
  for (const suffix of ['', '-shm', '-wal']) {
    const p = dbPath + suffix;
    if (fs.existsSync(p)) fs.unlinkSync(p);
  }
}

function fakeReview(id, timestampCreated) {
  return {
    recommendationid: id,
    language: 'english',
    review: `review text ${id}`,
    voted_up: true,
    timestamp_created: timestampCreated,
    timestamp_updated: timestampCreated,
    author: { steamid: `7656119${id}`, playtime_forever: 100 },
  };
}

test('parseAndValidate rejects malformed Steam responses', async () => {
  const { parseAndValidate } = require('./collector.js');
  const stats = { errors: [] };
  const okRes = { json: async () => ({ success: 1, reviews: [] }) };
  const badSuccess = { json: async () => ({ success: 0, reviews: [] }) };
  const missingReviews = { json: async () => ({ success: 1 }) };

  assert.ok(await parseAndValidate(okRes, 'english', stats));
  assert.equal(await parseAndValidate(badSuccess, 'english', stats), null);
  assert.equal(await parseAndValidate(missingReviews, 'english', stats), null);
  assert.equal(stats.errors.length, 2);
});

test('a sync run that fails partway does not advance sync_boundary_id, so the next run revisits the gap', async () => {
  const dbPath = tmpDbPath();
  const originalFetch = global.fetch;
  try {
    const db = openDb(dbPath);
    db.close();

    // --- 1차 실행: 1페이지는 성공(review-2, review-1 삽입), 2페이지에서 500 오류로 실패 ---
    let call = 0;
    global.fetch = async () => {
      call += 1;
      if (call === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: 1,
            reviews: [fakeReview('id-2', 2000), fakeReview('id-1', 1000)],
            cursor: 'page2',
          }),
        };
      }
      return { ok: false, status: 500 };
    };

    const db1 = openDb(dbPath);
    const stats1 = { errors: [], perLanguage: {} };
    await syncLanguage(db1, 'english', stats1);
    db1.close();

    assert.equal(stats1.perLanguage.english.hadError, true);

    const dbCheck1 = openDb(dbPath);
    const state1 = dbCheck1.prepare('SELECT sync_boundary_id FROM collector_state WHERE language = ?').get('english');
    const rows1 = dbCheck1.prepare('SELECT recommendationid FROM reviews ORDER BY recommendationid').all();
    dbCheck1.close();

    // 실패했으므로 경계값은 아직 null이어야 한다(1차 실행 전에도 없었음).
    assert.equal(state1 ? state1.sync_boundary_id : null, null);
    // 그래도 1페이지에서 성공적으로 받은 리뷰는 이미 저장돼 있어야 한다.
    assert.deepEqual(rows1.map((r) => r.recommendationid), ['id-1', 'id-2']);

    // --- 2차 실행: 이번엔 전부 성공 ---
    call = 0;
    global.fetch = async () => {
      call += 1;
      if (call === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: 1,
            reviews: [fakeReview('id-2', 2000), fakeReview('id-1', 1000)],
            cursor: 'page2',
          }),
        };
      }
      if (call === 2) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: 1,
            reviews: [fakeReview('id-0', 500)],
            cursor: 'page3', // 리뷰가 있는 응답엔 항상 유효한 cursor가 따라온다(스팀 실제 동작과 동일)
          }),
        };
      }
      // 3번째 호출(page3)에서 reviews가 빈 배열로 와야 "진짜로 끝"이라는 뜻이다.
      return { ok: true, status: 200, json: async () => ({ success: 1, reviews: [] }) };
    };

    const db2 = openDb(dbPath);
    const stats2 = { errors: [], perLanguage: {} };
    await syncLanguage(db2, 'english', stats2);
    db2.close();

    assert.equal(stats2.perLanguage.english.hadError, false);

    const dbCheck2 = openDb(dbPath);
    const rows2 = dbCheck2.prepare('SELECT recommendationid FROM reviews ORDER BY recommendationid').all();
    const state2 = dbCheck2.prepare('SELECT sync_boundary_id FROM collector_state WHERE language = ?').get('english');
    dbCheck2.close();

    // 실패했던 구간(id-0)까지 이번엔 회복돼서 들어와 있어야 한다.
    assert.deepEqual(rows2.map((r) => r.recommendationid), ['id-0', 'id-1', 'id-2']);
    assert.equal(state2.sync_boundary_id, 'id-2');
  } finally {
    global.fetch = originalFetch;
    cleanup(dbPath);
  }
});
