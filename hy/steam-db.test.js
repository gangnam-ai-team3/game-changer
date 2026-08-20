'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { STEAM_LANGUAGE_CODES, STEAM_LANGUAGES } = require('./steam-db.js');

test('vietnamese language code is spelled out, not the ISO "vi" code', () => {
  assert.ok(STEAM_LANGUAGE_CODES.includes('vietnamese'), 'STEAM_LANGUAGE_CODES should include "vietnamese"');
  assert.ok(!STEAM_LANGUAGE_CODES.includes('vi'), 'STEAM_LANGUAGE_CODES should not include the wrong code "vi"');
});

test('STEAM_LANGUAGES and STEAM_LANGUAGE_CODES stay in sync', () => {
  assert.deepEqual(
    STEAM_LANGUAGES.map((l) => l.code),
    STEAM_LANGUAGE_CODES
  );
});
