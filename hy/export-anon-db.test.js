'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const { assertSafeOutputPath, evidenceId, toUtcDay, exportAnonymizedDb } = require('./export-anon-db.js');
const { DB_PATH } = require('./steam-db.js');

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
  const srcPath = path.join(os.tmpdir(), `hy-export-src-${process.pid}-${Date.now()}.db`);
  const outPath = path.join(os.tmpdir(), `hy-export-out-${process.pid}-${Date.now()}.db`);
  try {
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
    src.prepare(
      `INSERT INTO reviews (recommendationid, appid, language, review, voted_up, timestamp_created, timestamp_updated, steamid, playtime_forever_minutes, collected_at)
       VALUES ('rec-1', 578080, 'english', 'sentinel review text', 1, 1700000000, NULL, '76561198000000001', 500, 1700000001)`
    ).run();
    src.close();

    // 두 번째 인자(sourcePath)로 실제 hy/steam-reviews.db 대신 합성 DB를 가리키게 해서,
    // 진짜 원본을 건드리지 않고 스키마/내용을 검증한다.
    exportAnonymizedDb(outPath, srcPath);

    const out = new DatabaseSync(outPath, { readOnly: true });
    const columns = out.prepare('PRAGMA table_info(evidence)').all().map((c) => c.name);
    const forbidden = ['review', 'recommendationid', 'steamid', 'author_hash', 'playtime_forever_minutes'];
    for (const col of forbidden) {
      assert.ok(!columns.includes(col), `evidence table must not have column "${col}"`);
    }
    assert.deepEqual(columns.sort(), ['app_id', 'created_at', 'evidence_id', 'language', 'updated_at'].sort());

    const row = out.prepare('SELECT * FROM evidence').get();
    assert.equal(row.language, 'english');
    assert.equal(row.app_id, 578080);
    assert.equal(row.created_at, '2023-11-14');
    // 원문/실제 ID가 파일 바이트 어디에도 없는지도 확인(직렬화된 파일을 통째로 훑어봄).
    out.close();
    const rawBytes = fs.readFileSync(outPath, 'latin1');
    assert.ok(!rawBytes.includes('sentinel review text'));
    assert.ok(!rawBytes.includes('76561198000000001'));
    assert.ok(!rawBytes.includes('rec-1'));
  } finally {
    for (const p of [srcPath, outPath]) {
      for (const suffix of ['', '-shm', '-wal']) {
        if (fs.existsSync(p + suffix)) fs.unlinkSync(p + suffix);
      }
    }
  }
});
