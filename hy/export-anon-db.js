'use strict';

// 원본 DB(hy/steam-reviews.db, steamid·리뷰원문 있음)에서 공유해도 안전한 파생 스냅샷을 만든다.
// 원본은 절대 건드리지 않고 로컬에만 둔다.
//
// v2 스키마 변경 이유: 예전 v1(steamid만 author_hash로 치환)은 recommendationid + 리뷰 원문 +
// 정확한 타임스탬프를 그대로 남겼다. 스팀 공식 appreviews API는 recommendationid와 실제
// author.steamid를 같은 응답 객체로 묶어서 돌려주므로(우리가 collector.js에서 이미 그렇게 수집함),
// 누구든 같은 공개 API를 다시 돌리면 recommendationid → steamid 대조표를 만들 수 있다.
// 즉 recommendationid나 원문을 남기는 한 steamid를 지워도 사실상 재식별이 가능했다.
//
// 그래서 v2는 "판단 가능한 최소 정보"만 남긴다: 새로 만든 evidence_id(로컬 전용 키로 만든 HMAC,
// recommendationid와 무관), app_id, language, created_at/updated_at(정확한 시:분:초가 아니라
// UTC 날짜 단위로만). 리뷰 원문·recommendationid·steamid·author_hash·재생시간은 스키마에도
// 파일 바이트 어디에도 없다.
//
// 느낌 판단(stance)·요약(summary)·원인 분류(reason_codes) 같은 필드는 이 스냅샷에 없다 — 그건
// jelly 파트가 만드는 값이라, jelly·res 담당자와 계약을 먼저 맞춘 뒤에 별도로 합류시킬 예정이다.
//
// 사용법: node export-anon-db.js [출력경로]  (기본값: hy/steam-reviews.anon.db)

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DatabaseSync } = require('node:sqlite');
const { DB_PATH } = require('./steam-db.js');

const OUTPUT_PATH = process.argv[2] || path.join(__dirname, 'steam-reviews.anon.db');

// evidence_id: 이 로컬 전용 키로 만든 HMAC-SHA256의 앞 24자리. 키와 recommendationid 둘 다
// 출력 파일에 안 들어가므로, 이 id만 보고 원래 recommendationid로 되돌릴 방법이 없다.
const EVIDENCE_KEY_PATH = path.join(__dirname, '.evidence-key');

function loadOrCreateEvidenceKey() {
  try {
    const existing = fs.readFileSync(EVIDENCE_KEY_PATH, 'utf8').trim();
    if (/^[0-9a-f]{64}$/.test(existing)) return existing;
    throw new Error('evidence key 형식이 올바르지 않음');
  } catch (err) {
    const key = crypto.randomBytes(32).toString('hex');
    fs.writeFileSync(EVIDENCE_KEY_PATH, key, { mode: 0o600 });
    return key;
  }
}

const EVIDENCE_KEY = loadOrCreateEvidenceKey();

function evidenceId(recommendationid) {
  return crypto.createHmac('sha256', EVIDENCE_KEY).update(String(recommendationid)).digest('hex').slice(0, 24);
}

// 정확한 시:분:초까지 남기면 "이 시각에 딱 하나 있는 리뷰"로 스팀 공개 리스트와 대조해 역추적될
// 위험이 있어, UTC 날짜 단위로만 정규화한다.
function toUtcDay(unixSeconds) {
  return new Date(unixSeconds * 1000).toISOString().slice(0, 10); // 'YYYY-MM-DD'
}

function assertSafeOutputPath(outputPath, sourcePath = DB_PATH) {
  const resolvedOut = path.resolve(outputPath);
  const resolvedSrc = path.resolve(sourcePath);
  if (resolvedOut === resolvedSrc) {
    throw new Error('출력 경로가 원본 DB와 같습니다 — 원본을 덮어쓸 수 있어 거부합니다.');
  }
  if (fs.existsSync(resolvedOut) && fs.existsSync(resolvedSrc)) {
    const outStat = fs.statSync(resolvedOut);
    const srcStat = fs.statSync(resolvedSrc);
    if (outStat.ino === srcStat.ino && outStat.dev === srcStat.dev) {
      throw new Error('출력 경로가 원본 DB와 같은 파일(inode)입니다 — 거부합니다.');
    }
  }
}

// sourcePath는 테스트에서 실제 원본(hy/steam-reviews.db) 대신 합성 DB를 가리키게 하기 위한 것 —
// 기본값은 항상 실제 원본이다.
function exportAnonymizedDb(outputPath, sourcePath = DB_PATH) {
  if (!fs.existsSync(sourcePath)) {
    throw new Error(`원본 DB가 없습니다: ${sourcePath} (먼저 collector.js로 수집해야 합니다)`);
  }
  assertSafeOutputPath(outputPath, sourcePath);

  // 같은 디렉터리에 임시 파일로 완성한 뒤, 검증 통과 후에만 rename으로 원자 교체한다.
  // 도중에 실패하면 기존에 있던 활성 사본(있었다면)이 그대로 유지된다.
  const tmpPath = `${outputPath}.tmp-${process.pid}-${Date.now()}`;
  const cleanupTmp = () => {
    for (const suffix of ['', '-shm', '-wal']) {
      const p = tmpPath + suffix;
      if (fs.existsSync(p)) fs.unlinkSync(p);
    }
  };
  cleanupTmp();

  const src = new DatabaseSync(sourcePath, { readOnly: true });
  const dst = new DatabaseSync(tmpPath);
  let reviewCount = 0;

  try {
    dst.exec('PRAGMA journal_mode = WAL;');
    dst.exec(`
      CREATE TABLE evidence (
        evidence_id TEXT PRIMARY KEY,
        app_id INTEGER NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT
      );
      CREATE INDEX idx_evidence_app_lang_created ON evidence(app_id, language, created_at DESC);
      CREATE TABLE manifest (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `);

    const insertEvidence = dst.prepare(
      'INSERT INTO evidence (evidence_id, app_id, language, created_at, updated_at) VALUES (?, ?, ?, ?, ?)'
    );

    dst.exec('BEGIN TRANSACTION');
    for (const r of src.prepare(
      'SELECT recommendationid, appid, language, timestamp_created, timestamp_updated FROM reviews'
    ).iterate()) {
      insertEvidence.run(
        evidenceId(r.recommendationid),
        r.appid,
        r.language,
        toUtcDay(r.timestamp_created),
        r.timestamp_updated ? toUtcDay(r.timestamp_updated) : null
      );
      reviewCount += 1;
    }
    dst.exec('COMMIT');

    const insertManifest = dst.prepare('INSERT INTO manifest (key, value) VALUES (?, ?)');
    insertManifest.run('row_count', String(reviewCount));
    insertManifest.run('exported_at', new Date().toISOString());
    insertManifest.run('schema_version', '2');
    insertManifest.run(
      'note',
      'stance/summary/reason_codes 등 분류 필드는 이 스냅샷에 없음 — jelly 파트와 별도 협의 후 추가 예정'
    );
  } catch (err) {
    try {
      dst.exec('ROLLBACK');
    } catch (rollbackErr) {
      // 트랜잭션이 이미 끝난 상태에서 ROLLBACK을 부르면 에러가 나는데, 무시해도 안전하다.
    }
    dst.close();
    src.close();
    cleanupTmp();
    throw err;
  }

  dst.close();
  src.close();

  // 검증 통과 후에만 원자적으로 활성 파일 자리로 교체한다.
  fs.renameSync(tmpPath, outputPath);
  for (const suffix of ['-shm', '-wal']) {
    if (fs.existsSync(tmpPath + suffix)) fs.renameSync(tmpPath + suffix, outputPath + suffix);
  }

  return { outputPath, reviewCount };
}

module.exports = { exportAnonymizedDb, OUTPUT_PATH, assertSafeOutputPath, evidenceId, toUtcDay };

if (require.main === module) {
  const result = exportAnonymizedDb(OUTPUT_PATH);
  const size = fs.statSync(result.outputPath).size;
  console.log('안전 파생 스냅샷 생성 완료 (evidence 스키마 v2)');
  console.log('제외됨: 리뷰 원문, recommendationid, steamid, author_hash, 재생시간');
  console.log('경로:', result.outputPath);
  console.log('건수:', result.reviewCount);
  console.log('파일 크기:', (size / 1024 / 1024).toFixed(1), 'MB');
}
