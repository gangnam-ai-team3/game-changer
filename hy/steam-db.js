'use strict';

// 스팀 공식 API + 로컬 DB 접근 공용 모듈. Anthropic API와 무관 — 이 파일은 절대 Claude를 부르지 않는다.

const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

const DB_PATH = path.join(__dirname, 'steam-reviews.db');

// 스팀 공식 API 언어 코드 전체 목록(출처: partner.steamgames.com/doc/store/localization/languages)
const STEAM_LANGUAGES = [
  { code: 'english', label: '영어' },
  { code: 'koreana', label: '한국어' },
  { code: 'japanese', label: '일본어' },
  { code: 'schinese', label: '중국어(간체)' },
  { code: 'tchinese', label: '중국어(번체)' },
  { code: 'russian', label: '러시아어' },
  { code: 'spanish', label: '스페인어' },
  { code: 'latam', label: '스페인어(중남미)' },
  { code: 'portuguese', label: '포르투갈어' },
  { code: 'brazilian', label: '포르투갈어(브라질)' },
  { code: 'french', label: '프랑스어' },
  { code: 'german', label: '독일어' },
  { code: 'italian', label: '이탈리아어' },
  { code: 'polish', label: '폴란드어' },
  { code: 'dutch', label: '네덜란드어' },
  { code: 'turkish', label: '터키어' },
  { code: 'thai', label: '태국어' },
  { code: 'vietnamese', label: '베트남어' },
  { code: 'indonesian', label: '인도네시아어' },
  { code: 'malay', label: '말레이어' },
  { code: 'arabic', label: '아랍어' },
  { code: 'ukrainian', label: '우크라이나어' },
  { code: 'czech', label: '체코어' },
  { code: 'hungarian', label: '헝가리어' },
  { code: 'romanian', label: '루마니아어' },
  { code: 'bulgarian', label: '불가리아어' },
  { code: 'greek', label: '그리스어' },
  { code: 'swedish', label: '스웨덴어' },
  { code: 'danish', label: '덴마크어' },
  { code: 'finnish', label: '핀란드어' },
  { code: 'norwegian', label: '노르웨이어' },
];
const STEAM_LANGUAGE_CODES = STEAM_LANGUAGES.map((l) => l.code);

// 자주 쓰는 게임은 스팀 검색 API 호출 없이 바로 appid로 고정 — 검색 실패(예: "배틀그라운드" 같은 한글 약칭
// 미인식) 문제도 같이 해결된다. key는 소문자로 비교.
const STEAM_APPID_ALIASES = {
  '배틀그라운드': { appid: 578080, matchedName: 'PUBG: BATTLEGROUNDS' },
  'pubg': { appid: 578080, matchedName: 'PUBG: BATTLEGROUNDS' },
  'pubg: battlegrounds': { appid: 578080, matchedName: 'PUBG: BATTLEGROUNDS' },
  'battlegrounds': { appid: 578080, matchedName: 'PUBG: BATTLEGROUNDS' },
};

async function resolveSteamAppId(gameName) {
  const alias = STEAM_APPID_ALIASES[gameName.trim().toLowerCase()];
  if (alias) {
    return alias;
  }

  const url = `https://store.steampowered.com/api/storesearch/?term=${encodeURIComponent(gameName)}&l=korean&cc=kr`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`스팀 게임 검색 실패: HTTP ${res.status}`);
  }
  const data = await res.json();
  if (!data.items || data.items.length === 0) {
    return null;
  }
  return { appid: data.items[0].id, matchedName: data.items[0].name };
}

function openReadOnlyDb(dbPath = DB_PATH) {
  if (!fs.existsSync(dbPath)) {
    return null;
  }
  return new DatabaseSync(dbPath, { readOnly: true });
}

module.exports = {
  DB_PATH,
  STEAM_LANGUAGES,
  STEAM_LANGUAGE_CODES,
  STEAM_APPID_ALIASES,
  resolveSteamAppId,
  openReadOnlyDb,
};
