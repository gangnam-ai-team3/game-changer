'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const {
  assertSafeOutputPath,
  evidenceId,
  toUtcDay,
  toUtcWeekStart,
  exportAnonymizedDb,
  K_ANONYMITY_THRESHOLD,
} = require('./export-anon-db.js');
const { DB_PATH } = require('./steam-db.js');

function makeSrcDb() {
  const srcPath = path.join(os.tmpdir(), `hy-export-src-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}.db`);
  const src = new DatabaseSync(srcPath);
  src.exec(`
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
  `);
  return { srcPath, src };
}

function cleanupPaths(paths) {
  for (const p of paths) {
    for (const suffix of ['', '-shm', '-wal']) {
      if (fs.existsSync(p + suffix)) fs.unlinkSync(p + suffix);
    }
  }
}

test('rejects output path equal to source DB path', () => {
  assert.throws(() => assertSafeOutputPath(DB_PATH));
});

test('evidenceId is stable, does not reveal the raw id, and is 24 hex chars', () => {
  const id1 = evidenceId('233182857');
  const id2 = evidenceId('233182857');
  assert.equal(id1, id2);
  assert.notEqual(id1, '233182857');
  assert.match(id1, /^[0-9a-f]{24}$/);
});

test('toUtcDay drops time-of-day precision', () => {
  assert.equal(toUtcDay(1787130871), new Date(1787130871 * 1000).toISOString().slice(0, 10));
});

test('exported evidence table never contains review text, recommendationid, steamid, author_hash, or playtime columns', () => {
  const { srcPath, src } = makeSrcDb();
  const outPath = path.join(os.tmpdir(), `hy-export-out-${process.pid}-${Date.now()}.db`);
  try {
    const insert = src.prepare(
      `INSERT INTO reviews (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
       VALUES (?, 578080, 'english', ?, 1, ?, NULL, ?, 500, 0)`
    );
    // 같은 날(day) 안에 K_ANONYMITY_THRESHOLD(15)건 이상 넣어 day 단위가 안전하도록 만든다.
    const dayTs = 1700000000; // 2023-11-14 UTC
    for (let i = 0; i < K_ANONYMITY_THRESHOLD; i += 1) {
      insert.run(`rec-safe-${i}`, `sentinel review text ${i}`, dayTs, `7656119800000000${i}`);
    }
    src.close();

    // 두 번째 인자(sourcePath)로 실제 hy/steam-reviews.db 대신 합성 DB를 가리키게 해서,
    // 진짜 원본을 건드리지 않고 스키마/내용을 검증한다.
    const result = exportAnonymizedDb(outPath, srcPath);
    assert.equal(result.reviewCount, K_ANONYMITY_THRESHOLD);

    const out = new DatabaseSync(outPath, { readOnly: true });
    const columns = out.prepare('PRAGMA table_info(evidence)').all().map((c) => c.name);
    const forbidden = ['review', 'recommendationid', 'steamid', 'author_hash', 'playtime_forever_minutes'];
    for (const col of forbidden) {
      assert.ok(!columns.includes(col), `evidence table must not have column "${col}"`);
    }
    assert.deepEqual(columns.sort(), ['app_id', 'created_at', 'date_precision', 'evidence_id', 'language', 'updated_at'].sort());

    const row = out.prepare('SELECT * FROM evidence LIMIT 1').get();
    assert.equal(row.language, 'english');
    assert.equal(row.app_id, 578080);
    assert.equal(row.date_precision, 'day'); // 15건이 하루에 몰려 있으니 하루 단위 그대로 유지돼야 함
    assert.equal(row.created_at, '2023-11-14');
    // 원문/실제 ID가 파일 바이트 어디에도 없는지도 확인(직렬화된 파일을 통째로 훑어봄).
    out.close();
    const rawBytes = fs.readFileSync(outPath, 'latin1');
    assert.ok(!rawBytes.includes('sentinel review text'));
    assert.ok(!rawBytes.includes('76561198000000001'));
    assert.ok(!rawBytes.includes('rec-safe-0'));
  } finally {
    cleanupPaths([srcPath, outPath]);
  }
});

test('k-anonymity: a language/day combo below the threshold gets its date generalized to the week, not dropped', () => {
  const { srcPath, src } = makeSrcDb();
  const outPath = path.join(os.tmpdir(), `hy-export-out-${process.pid}-${Date.now()}.db`);
  try {
    const insert = src.prepare(
      `INSERT INTO reviews (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
       VALUES (?, 578080, 'german', ?, 1, ?, NULL, ?, 0, 0)`
    );
    // 같은 주(2023-11-13 월요일 ~ 11-19 일요일) 안의 서로 다른 3일(수/목/금)에 5건씩(하루 5건 < 15)
    // 흩뿌려서, 하루 단위로는 위험하지만 주 단위로 합치면 15건이 되어 안전해지는 상황을 만든다.
    const weekday1 = 1700006400; // 2023-11-15(수) 00:00 UTC
    const days = [weekday1, weekday1 + 86400, weekday1 + 2 * 86400];
    let i = 0;
    for (const dayTs of days) {
      for (let j = 0; j < 5; j += 1) {
        insert.run(`rec-week-${i}`, `text ${i}`, dayTs + j * 60, `steamid-${i}`);
        i += 1;
      }
    }
    src.close();

    const result = exportAnonymizedDb(outPath, srcPath);
    assert.equal(result.reviewCount, 15, '아무 것도 제외되지 않고 15건 전부 남아야 함');

    const out = new DatabaseSync(outPath, { readOnly: true });
    const rows = out.prepare('SELECT * FROM evidence').all();
    out.close();
    assert.equal(rows.length, 15);
    for (const row of rows) {
      assert.equal(row.date_precision, 'week');
      assert.equal(row.created_at, toUtcWeekStart(weekday1));
    }
  } finally {
    cleanupPaths([srcPath, outPath]);
  }
});

test('k-anonymity: a language too small at every date granularity is suppressed entirely, not just fuzzed', () => {
  const { srcPath, src } = makeSrcDb();
  const outPath = path.join(os.tmpdir(), `hy-export-out-${process.pid}-${Date.now()}.db`);
  try {
    const insert = src.prepare(
      `INSERT INTO reviews (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
       VALUES (?, 578080, 'malay', ?, 1, ?, NULL, ?, 0, 0)`
    );
    // malay 언어 전체를 통틀어 3건뿐 — 하루/주/월/언어 전체 어느 단위로도 15건을 못 채운다.
    insert.run('rec-tiny-1', 'text', 1700000000, 'steamid-tiny-1');
    insert.run('rec-tiny-2', 'text', 1701000000, 'steamid-tiny-2');
    insert.run('rec-tiny-3', 'text', 1702000000, 'steamid-tiny-3');
    src.close();

    const result = exportAnonymizedDb(outPath, srcPath);
    assert.equal(result.reviewCount, 0, '15건 미만인 언어는 통째로 제외돼야 함');
    assert.equal(result.precisionStats.suppressed, 3);

    const out = new DatabaseSync(outPath, { readOnly: true });
    const count = out.prepare("SELECT COUNT(*) c FROM evidence WHERE language = 'malay'").get().c;
    out.close();
    assert.equal(count, 0);
  } finally {
    cleanupPaths([srcPath, outPath]);
  }
});
