'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { callAgent } = require('./call-agent.js');

const PORT = process.env.PORT || 8787;
const SCREEN_HTML_PATH = path.join(__dirname, 'screen.html');

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
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

  if (req.method === 'POST' && req.url === '/call-agent') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', async () => {
      try {
        const { text, costLimitAmount, costLimitCurrency, gameName, periodStartMs, periodEndMs, languages } = JSON.parse(body || '{}');
        if (!text || !text.trim()) {
          sendJson(res, 400, { error: '입력이 비어 있습니다.' });
          return;
        }
        const result = await callAgent(text, { costLimitAmount, costLimitCurrency, gameName, periodStartMs, periodEndMs, languages });
        sendJson(res, 200, { result });
      } catch (err) {
        sendJson(res, 500, { error: err.message });
      }
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`hy 담당자 호출 서버 실행 중: http://localhost:${PORT}`);
});
