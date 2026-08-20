'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { server, MAX_BODY_BYTES } = require('./server.js');

function startEphemeral() {
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(server.address()));
  });
}

function stop() {
  return new Promise((resolve) => server.close(resolve));
}

test('server binds to loopback only', async () => {
  const addr = await startEphemeral();
  try {
    assert.equal(addr.address, '127.0.0.1');
  } finally {
    await stop();
  }
});

test('rejects a request body over 2MB with HTTP 413', async () => {
  const addr = await startEphemeral();
  try {
    const bigBody = JSON.stringify({ gameName: 'pubg', periodStartMs: 0, periodEndMs: 1, filler: 'x'.repeat(MAX_BODY_BYTES + 1000) });
    const res = await fetch(`http://127.0.0.1:${addr.port}/evidence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: bigBody,
    });
    assert.equal(res.status, 413);
  } finally {
    await stop();
  }
});

test('rejects a non-JSON Content-Type with HTTP 415', async () => {
  const addr = await startEphemeral();
  try {
    const res = await fetch(`http://127.0.0.1:${addr.port}/evidence`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: 'not json',
    });
    assert.equal(res.status, 415);
  } finally {
    await stop();
  }
});

test('rejects malformed JSON with HTTP 400', async () => {
  const addr = await startEphemeral();
  try {
    const res = await fetch(`http://127.0.0.1:${addr.port}/evidence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{not valid json',
    });
    assert.equal(res.status, 400);
  } finally {
    await stop();
  }
});

test('the /call-agent route is gone (removed from the default server in this revision)', async () => {
  const addr = await startEphemeral();
  try {
    const res = await fetch(`http://127.0.0.1:${addr.port}/call-agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    assert.equal(res.status, 404);
  } finally {
    await stop();
  }
});
