'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { prepareEvidence } = require('./prepare-evidence.js');

const PORT = process.env.PORT || 8787;
const SCREEN_HTML_PATH = path.join(__dirname, 'screen.html');
const MAX_BODY_BYTES = 2 * 1024 * 1024; // 2MB — 비정상적으로 큰 요청으로 서버가 멎지 않도록
const MAX_EVIDENCE_ITEMS_IN_RESPONSE = 20000; // 응답이 지나치게 커지는 것 방지(예: english 언어권)
const EVIDENCE_TIMEOUT_MS = 30 * 1000; // 처리 시간 상한 — 너무 넓은 기간/언어 요청이 서버를 오래 붙잡지 않도록

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}

// 요청 본문을 모으면서 크기 제한을 넘으면 즉시 끊는다. 넘지 않으면 문자열로 완성해서 돌려준다.
function readJsonBody(req, res) {
  return new Promise((resolve) => {
    const contentType = req.headers['content-type'] || '';
    if (!contentType.includes('application/json')) {
      sendJson(res, 415, { error: 'Content-Type은 application/json이어야 합니다.' });
      resolve(null);
      return;
    }

    let body = '';
    let tooLarge = false;
    req.on('data', (chunk) => {
      if (tooLarge) return;
      body += chunk;
      if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
        tooLarge = true;
        sendJson(res, 413, { error: '요청 본문이 너무 큽니다(최대 2MB).' });
        req.destroy();
        resolve(null);
      }
    });
    req.on('end', () => {
      if (tooLarge) return;
      try {
        resolve(JSON.parse(body || '{}'));
      } catch (err) {
        sendJson(res, 400, { error: '요청 본문이 올바른 JSON이 아닙니다.' });
        resolve(null);
      }
    });
    req.on('error', () => {
      if (!tooLarge) resolve(null);
    });
  });
}

// 리뷰 원문·작성자 해시는 HTTP 응답으로 내보내지 않는다(로컬 전용 서버라도 원칙은 지킨다) —
// 화면에서 원문을 보고 싶으면 로컬에서 직접 DB를 조회한다.
function stripSensitiveFields(evidenceResult) {
  if (!Array.isArray(evidenceResult.evidence)) return evidenceResult;
  let evidence = evidenceResult.evidence.map(({ review, authorHash, mergedIds, ...rest }) => rest);
  let truncatedForResponse = false;
  if (evidence.length > MAX_EVIDENCE_ITEMS_IN_RESPONSE) {
    evidence = evidence.slice(0, MAX_EVIDENCE_ITEMS_IN_RESPONSE);
    truncatedForResponse = true;
  }
  return { ...evidenceResult, evidence, truncatedForResponse };
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && (req.url === '/' || req.url === '/screen.html')) {
    fs.readFile(SCREEN_HTML_PATH, 'utf8', (err, html) => {
      if (err) {
        res.writeHead(500);
        res.end('screen.html을 읽지 못했습니다.');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(html);
    });
    return;
  }

  if (req.method === 'POST' && req.url === '/evidence') {
    (async () => {
      const parsed = await readJsonBody(req, res);
      if (parsed === null) return; // readJsonBody가 이미 응답을 보냈음(에러 또는 크기 초과)
      try {
        const { gameName, periodStartMs, periodEndMs, languages } = parsed;
        if (!gameName || !Number.isFinite(periodStartMs) || !Number.isFinite(periodEndMs)) {
          sendJson(res, 400, { error: '게임이름/기간이 필요합니다.' });
          return;
        }
        // Claude(Anthropic API)를 전혀 거치지 않는다 — 기간필터+짧은리뷰제거+중복병합+벡터화까지 전부 로컬 계산
        const evidenceResult = await Promise.race([
          prepareEvidence({ gameName, periodStartMs, periodEndMs, languages }),
          new Promise((_, reject) => setTimeout(() => reject(new Error('EVIDENCE_TIMEOUT')), EVIDENCE_TIMEOUT_MS)),
        ]);
        sendJson(res, 200, stripSensitiveFields(evidenceResult));
      } catch (err) {
        if (err.message === 'EVIDENCE_TIMEOUT') {
          sendJson(res, 504, { error: '처리 시간이 너무 오래 걸려 중단했습니다(기간·언어 범위를 좁혀 다시 시도하세요).' });
          return;
        }
        console.error('evidence 처리 오류:', err);
        sendJson(res, 500, { error: '처리 중 오류가 발생했습니다.' });
      }
    })();
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

// 127.0.0.1에만 바인딩 — 같은 네트워크의 다른 기기에서 접근 못 하게 막는다.
// (call-agent.js를 이용한 Claude 보고서 생성은 이번 개정에서 기본 서버 경로에서 제거했다 —
//  필요하면 hy/call-agent.js를 별도 스크립트로 직접 실행한다.)
// require.main === module 가드: 테스트 코드에서 require할 때 실제 포트를 점유하지 않기 위함
// (테스트는 server를 직접 listen(0, '127.0.0.1')로 임시 포트에 띄운다).
if (require.main === module) {
  server.listen(PORT, '127.0.0.1', () => {
    console.log(`hy 담당자 호출 서버 실행 중: http://127.0.0.1:${PORT}`);
  });
}

module.exports = { server, MAX_BODY_BYTES };
