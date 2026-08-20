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
// v3 변경 이유: v2도 리뷰 원문·ID는 없앴지만, "언어 + 정확한 작성일" 조합 자체가 너무 희귀하면
// (예: 어떤 날 그 언어로 쓴 리뷰가 딱 1건) 스팀 공개 리스트에서 그 언어·그 날짜로 찾아보면 후보가
// 한 명뿐이라 사실상 재식별될 수 있다. 그래서 (language, 날짜) 조합의 건수가 K_ANONYMITY_THRESHOLD
// 미만이면 날짜 정밀도를 하루 → 주 → 월 순으로 낮추고, 그래도 안 되면(해당 언어 자체가 워낙 적으면)
// 그 행은 공유본에서 아예 뺀다. 기준값(15)은 res 파트가 이미 쓰는 "표본 15건 미만이면 결론 숨김"
// 기준을 그대로 재사용한다(res/agent-spec.md) — 어차피 그 미만 표본은 res도 분석에 안 쓰므로
// 날짜를 흐리거나 빼도 후속 작업에 실질적 손실이 없다.
//
// 그래서 v3는 "판단 가능한 최소 정보 + 재식별 안전한 최소 정밀도"만 남긴다: 새로 만든
// evidence_id(로컬 전용 키로 만든 HMAC, recommendationid와 무관), app_id, language,
// created_at/updated_at(안전한 만큼만 정밀한 날짜, 아래 date_precision 참고). 리뷰 원문·
// recommendationid·steamid·author_hash·재생시간은 스키마에도 파일 바이트 어디에도 없다.
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

// res/agent-spec.md의 "근거 15건 미만이면 결론 숨김" 기준을 그대로 재사용 — 새 숫자를 만들지 않는다.
const K_ANONYMITY_THRESHOLD = 15;

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

function toUtcDay(unixSeconds) {
  return new Date(unixSeconds * 1000).toISOString().slice(0, 10); // 'YYYY-MM-DD'
}

function toUtcMonth(unixSeconds) {
  return new Date(unixSeconds * 1000).toISOString().slice(0, 7); // 'YYYY-MM'
}

// 해당 날짜가 속한 주의 월요일 날짜(UTC 기준)로 뭉갠다 — "그 날 하루"보다 넓지만 "그 달 전체"보다는
// 좁은 중간 단계.
function toUtcWeekStart(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  const day = d.getUTCDay(); // 0=일요일
  const diffToMonday = day === 0 ? -6 : 1 - day;
  d.setUTCDate(d.getUTCDate() + diffToMonday);
  return d.toISOString().slice(0, 10);
}

// (언어, 날짜 정밀도) 조합별로 건수를 세서, K_ANONYMITY_THRESHOLD 미만인 행은 정밀도를
// 하루 → 주 → 월 → (그래도 안 되면) 완전 제외 순으로 낮춘다. 원본을 두 번 훑지만(집계+실제 기록),
// 매번 recommendationid·리뷰원문 없이 language+timestamp만 다뤄 메모리 부담이 작다.
function buildDatePrecisionPlan(src) {
  const rows = src.prepare('SELECT recommendationid, language, timestamp_created FROM reviews').all();

  const dayCount = new Map();
  const dayKeyOf = (r) => `${r.language}|${toUtcDay(r.timestamp_created)}`;
  for (const r of rows) {
    const k = dayKeyOf(r);
    dayCount.set(k, (dayCount.get(k) || 0) + 1);
  }

  const weekCount = new Map();
  const weekKeyOf = (r) => `${r.language}|${toUtcWeekStart(r.timestamp_created)}`;
  for (const r of rows) {
    if (dayCount.get(dayKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    const k = weekKeyOf(r);
    weekCount.set(k, (weekCount.get(k) || 0) + 1);
  }

  const monthCount = new Map();
  const monthKeyOf = (r) => `${r.language}|${toUtcMonth(r.timestamp_created)}`;
  for (const r of rows) {
    if (dayCount.get(dayKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    if (weekCount.get(weekKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    const k = monthKeyOf(r);
    monthCount.set(k, (monthCount.get(k) || 0) + 1);
  }

  const langOnlyCount = new Map();
  for (const r of rows) {
    if (dayCount.get(dayKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    if (weekCount.get(weekKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    if (monthCount.get(monthKeyOf(r)) >= K_ANONYMITY_THRESHOLD) continue;
    langOnlyCount.set(r.language, (langOnlyCount.get(r.language) || 0) + 1);
  }

  // recommendationid별로 최종 결정(정밀도 단계 + 그 단계의 건수)을 미리 계산해 둔다.
  const decisionById = new Map();
  let dayLevel = 0;
  let weekLevel = 0;
  let monthLevel = 0;
  let langLevel = 0;
  let suppressed = 0;
  for (const r of rows) {
    const dk = dayKeyOf(r);
    if (dayCount.get(dk) >= K_ANONYMITY_THRESHOLD) {
      decisionById.set(r.recommendationid, 'day');
      dayLevel += 1;
      continue;
    }
    const wk = weekKeyOf(r);
    if (weekCount.get(wk) >= K_ANONYMITY_THRESHOLD) {
      decisionById.set(r.recommendationid, 'week');
      weekLevel += 1;
      continue;
    }
    const mk = monthKeyOf(r);
    if (monthCount.get(mk) >= K_ANONYMITY_THRESHOLD) {
      decisionById.set(r.recommendationid, 'month');
      monthLevel += 1;
      continue;
    }
    if (langOnlyCount.get(r.language) >= K_ANONYMITY_THRESHOLD) {
      decisionById.set(r.recommendationid, 'language');
      langLevel += 1;
      continue;
    }
    decisionById.set(r.recommendationid, 'suppress');
    suppressed += 1;
  }

  return { decisionById, stats: { dayLevel, weekLevel, monthLevel, langLevel, suppressed, total: rows.length } };
}

// 위에서 결정된 정밀도 단계에 맞게 실제 날짜 문자열을 만든다. 'language' 단계는 날짜를 아예 버리고
// null로 남긴다(그 언어라는 것만 알 수 있고 시점은 특정 불가).
function resolveDateForPrecision(precision, unixSeconds) {
  switch (precision) {
    case 'day':
      return toUtcDay(unixSeconds);
    case 'week':
      return toUtcWeekStart(unixSeconds);
    case 'month':
      return toUtcMonth(unixSeconds);
    case 'language':
      return null;
    default:
      return null;
  }
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
  let precisionStats;

  try {
    const plan = buildDatePrecisionPlan(src);
    precisionStats = plan.stats;

    dst.exec('PRAGMA journal_mode = WAL;');
    dst.exec(`
      CREATE TABLE evidence (
        evidence_id TEXT PRIMARY KEY,
        app_id INTEGER NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT,
        date_precision TEXT NOT NULL
      );
      CREATE INDEX idx_evidence_app_lang_created ON evidence(app_id, language, created_at DESC);
      CREATE TABLE manifest (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `);

    const insertEvidence = dst.prepare(
      'INSERT INTO evidence (evidence_id, app_id, language, created_at, updated_at, date_precision) VALUES (?, ?, ?, ?, ?, ?)'
    );

    dst.exec('BEGIN TRANSACTION');
    for (const r of src.prepare(
      'SELECT recommendationid, appid, language, timestamp_created, timestamp_updated FROM reviews'
    ).iterate()) {
      const precision = plan.decisionById.get(r.recommendationid);
      if (precision === 'suppress') continue; // 이 언어 자체가 너무 적어 어떤 날짜 단위로도 안전하지 않음 — 제외

      insertEvidence.run(
        evidenceId(r.recommendationid),
        r.appid,
        r.language,
        resolveDateForPrecision(precision, r.timestamp_created),
        r.timestamp_updated ? resolveDateForPrecision(precision, r.timestamp_updated) : null,
        precision
      );
      reviewCount += 1;
    }
    dst.exec('COMMIT');

    const insertManifest = dst.prepare('INSERT INTO manifest (key, value) VALUES (?, ?)');
    insertManifest.run('row_count', String(reviewCount));
    insertManifest.run('exported_at', new Date().toISOString());
    insertManifest.run('schema_version', '3');
    insertManifest.run('k_anonymity_threshold', String(K_ANONYMITY_THRESHOLD));
    insertManifest.run(
      'date_precision_breakdown',
      JSON.stringify(precisionStats)
    );
    insertManifest.run(
      'note',
      'stance/summary/reason_codes 등 분류 필드는 이 스냅샷에 없음 — jelly 파트와 별도 협의 후 추가 예정. ' +
        'date_precision 컬럼은 created_at/updated_at이 얼마나 뭉개졌는지(day/week/month/language) 나타냄.'
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

  return { outputPath, reviewCount, precisionStats };
}

module.exports = {
  exportAnonymizedDb,
  OUTPUT_PATH,
  assertSafeOutputPath,
  evidenceId,
  toUtcDay,
  toUtcWeekStart,
  toUtcMonth,
  buildDatePrecisionPlan,
  K_ANONYMITY_THRESHOLD,
};

if (require.main === module) {
  const result = exportAnonymizedDb(OUTPUT_PATH);
  const size = fs.statSync(result.outputPath).size;
  console.log('안전 파생 스냅샷 생성 완료 (evidence 스키마 v3 — k-익명성 적용)');
  console.log('제외됨: 리뷰 원문, recommendationid, steamid, author_hash, 재생시간');
  console.log('경로:', result.outputPath);
  console.log('건수(제외된 행 빼고):', result.reviewCount);
  console.log('날짜 정밀도 분포:', JSON.stringify(result.precisionStats, null, 2));
  console.log('파일 크기:', (size / 1024 / 1024).toFixed(1), 'MB');
}
