'use strict';

const fs = require('fs');
const path = require('path');
const Anthropic = require('@anthropic-ai/sdk');

const REPO_ROOT = path.resolve(__dirname, '..');
const ENV_PATH = path.join(REPO_ROOT, '.env');
const AGENT_SPEC_PATH = path.join(REPO_ROOT, '.claude', 'agents', 'hy.md');
const MODEL = 'claude-opus-5';

function loadApiKey() {
  const envText = fs.readFileSync(ENV_PATH, 'utf8');
  const match = envText.match(/^ANTHROPIC_API_KEY=(.*)$/m);
  const key = match ? match[1].trim() : '';
  if (!key) {
    throw new Error(`${ENV_PATH} 에 ANTHROPIC_API_KEY 값이 비어 있습니다.`);
  }
  return key;
}

const RUNTIME_NOTE =
  '\n\n---\n' +
  '# 이 호출의 실행 환경 안내\n' +
  '이번 호출에서 실제로 쓸 수 있는 도구는 web_search, web_fetch 두 가지뿐입니다. ' +
  '위에 적힌 Read/Write 도구는 이 호출에서는 주어지지 않았으므로 사용할 수 없습니다. ' +
  '파일을 만들었다거나 hy/ 폴더에 저장했다고 말하지 마세요. 실제로 저장되지 않습니다. ' +
  '모든 결과(피드백 번들 전체)는 파일이 아니라 이 응답의 텍스트로만 출력하세요.\n\n' +
  '아래에 "스팀 공식 appreviews 엔드포인트로 미리 수집한 원본 데이터" 블록이 있다면, ' +
  '그건 사용자가 입력한 승인 출처 목록과 무관하게 코드가 스팀 공식 API로 직접 가져온 것이라 1단계(출처 확인)를 이미 통과한 데이터입니다. ' +
  '별도의 승인된 출처 목록이 없다는 이유로 이 데이터를 반려하지 마세요.';

function loadSystemPrompt() {
  return fs.readFileSync(AGENT_SPEC_PATH, 'utf8') + RUNTIME_NOTE;
}

const APPROVED_DOMAINS = [
  'store.steampowered.com',
  'steamcommunity.com',
  'x.com',
  'twitter.com',
];

// claude-opus-5 가격, 100만 토큰당 USD
const PRICING = { input: 5.0, output: 25.0 };

// 화면의 환율 표시와 동일한 고정 환율(예시값) — 상한 비용을 USD로 환산하는 용도
const FX_TO_KRW = { USD: 1380, JPY: 9.2, EUR: 1490, CNY: 190, KRW: 1 };

function toUsd(amount, currency) {
  const rate = FX_TO_KRW[currency];
  if (!rate) {
    throw new Error(`알 수 없는 통화입니다: ${currency}`);
  }
  return (amount * rate) / FX_TO_KRW.USD;
}

const MAX_OUTPUT_TOKENS = 16000;

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
  { code: 'vi', label: '베트남어' },
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

// 스팀 리뷰 수집 안전장치(언어 하나=병렬 체인 하나 기준). 기간이 오래된 과거일수록 그 구간에 닿기까지
// 최신 리뷰를 계속 넘겨야 하므로 무한정 페이지를 넘기지 않도록 상한을 둔다
// (둘 다 Anthropic 비용과 무관 — 순수 HTTP 요청. 언어별로 병렬 실행되므로 체감 시간은 이 값 하나 기준과 비슷하다).
const STEAM_MAX_PAGES = 300; // 언어 하나당 페이지당 최대 100건 → 최대 30,000건 스캔
const STEAM_MAX_REVIEWS_IN_WINDOW = 300; // 언어 하나당 기간 내에서 실제로 담아갈 리뷰 수 상한
const STEAM_REVIEW_TEXT_LIMIT = 1000; // 리뷰 하나당 담아갈 텍스트 길이 상한(문자)

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

async function fetchSteamReviewsForLanguage({ appid, language, periodStartMs, periodEndMs }) {
  const reviews = [];
  let cursor = '*';
  let scannedPages = 0;
  let scannedCount = 0;
  // 스캔이 어떻게 끝났는지 정확한 이유를 남긴다 — "결과가 적다"가 "실제로 적어서"인지
  // "다 못 봐서"인지를 코드가 직접 구분해서 나중에 사용자에게 정직하게 알려주기 위함
  let stopReason = null; // 'reachedWindowStart' | 'windowTruncated' | 'cursorExhausted' | 'pageCap'

  for (let page = 0; page < STEAM_MAX_PAGES; page += 1) {
    const url =
      `https://store.steampowered.com/appreviews/${appid}?json=1&filter=recent&language=${language}` +
      `&num_per_page=100&purchase_type=all&filter_offtopic_activity=0&cursor=${encodeURIComponent(cursor)}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`스팀 리뷰 조회 실패(${language}): HTTP ${res.status}`);
    }
    const data = await res.json();
    scannedPages += 1;

    const batch = data.reviews || [];
    if (batch.length === 0) {
      stopReason = 'cursorExhausted';
      break;
    }
    scannedCount += batch.length;

    for (const review of batch) {
      const tsMs = review.timestamp_created * 1000;
      if (tsMs < periodStartMs) {
        stopReason = 'reachedWindowStart';
        break;
      }
      if (tsMs <= periodEndMs) {
        reviews.push({
          recommendationid: review.recommendationid,
          steamid: review.author && review.author.steamid,
          language: review.language,
          review: (review.review || '').slice(0, STEAM_REVIEW_TEXT_LIMIT),
          voted_up: review.voted_up,
          timestamp_created: review.timestamp_created,
          playtime_forever_minutes: review.author && review.author.playtime_forever,
        });
        if (reviews.length >= STEAM_MAX_REVIEWS_IN_WINDOW) {
          stopReason = 'windowTruncated';
          break;
        }
      }
    }

    if (stopReason) {
      break;
    }
    if (!data.cursor || data.cursor === cursor) {
      stopReason = 'cursorExhausted';
      break;
    }
    cursor = data.cursor;
  }

  if (!stopReason) {
    stopReason = 'pageCap';
  }

  return {
    language,
    reviews,
    scannedPages,
    scannedCount,
    stopReason,
    // 이 기간의 리뷰를 빠짐없이 다 봤다고 확신할 수 있는 경우만 true
    complete: stopReason === 'reachedWindowStart' || stopReason === 'cursorExhausted',
  };
}

async function fetchSteamReviews({ gameName, periodStartMs, periodEndMs, languages }) {
  const resolved = await resolveSteamAppId(gameName);
  if (!resolved) {
    return { found: false, gameName };
  }

  const { appid, matchedName } = resolved;
  const targetLanguages =
    Array.isArray(languages) && languages.length > 0
      ? languages.filter((code) => STEAM_LANGUAGE_CODES.includes(code))
      : STEAM_LANGUAGE_CODES;

  // 언어별로 독립된 커서 체인이라 동시에(병렬로) 실행한다 — 순차로 하나씩 하면 언어 수만큼 시간이 곱해지지만,
  // 병렬로 하면 (실측 기준) 언어 수와 거의 무관하게 가장 느린 언어 하나만큼의 시간으로 끝난다.
  const perLanguage = await Promise.all(
    targetLanguages.map((language) => fetchSteamReviewsForLanguage({ appid, language, periodStartMs, periodEndMs }))
  );

  const reviews = perLanguage.flatMap((r) => r.reviews);

  return {
    found: true,
    appid,
    matchedName,
    languagesQueried: targetLanguages,
    perLanguage: perLanguage.map(({ language, scannedPages, scannedCount, stopReason, complete, reviews: langReviews }) => ({
      language,
      scannedPages,
      scannedCount,
      stopReason,
      complete,
      collected: langReviews.length,
    })),
    reviews,
  };
}

function describeSteamCollectionStatus(steamResult) {
  if (!steamResult.found) {
    return (
      `[스팀 수집 상태: 실패] "${steamResult.gameName}"에 해당하는 게임을 스팀에서 찾지 못했습니다. ` +
      `공식 영문/정식 명칭에 가깝게 다시 확인해주세요.`
    );
  }
  const totalCollected = steamResult.reviews.length;
  const base = `대상: ${steamResult.matchedName}(appid ${steamResult.appid}) · 조회한 언어 ${steamResult.perLanguage.length}개 · 기간 내 수집 합계 ${totalCollected}건`;

  const incomplete = steamResult.perLanguage.filter((p) => !p.complete && p.scannedCount > 0);
  if (incomplete.length === 0) {
    return `[스팀 수집 상태: 완전 수집] 조회한 모든 언어권에서 요청한 기간을 끝까지 스캔했습니다 — 아래는 이 기간의 전체 리뷰입니다. ${base}`;
  }

  const reasonLabel = (r) =>
    r === 'windowTruncated'
      ? `기간 내 리뷰가 ${STEAM_MAX_REVIEWS_IN_WINDOW}건을 넘어 일부만 담음`
      : `페이지 상한(${STEAM_MAX_PAGES})에 도달했지만 기간 시작점에 도달 못함`;
  const detail = incomplete.map((p) => `${p.language}(${reasonLabel(p.stopReason)}, ${p.collected}건까지만)`).join(', ');

  return (
    `[스팀 수집 상태: 일부만 수집됨(미완료)] 다음 언어권은 요청한 기간을 끝까지 못 봤습니다 — ${detail}. ` +
    `나머지 언어권은 완전 수집됨. 지금 데이터가 이 기간의 "전부"라는 보장이 없습니다. ${base}`
  );
}

async function callAgent(inputText, options = {}) {
  const client = new Anthropic({ apiKey: loadApiKey() });
  const system = loadSystemPrompt();

  let steamBlock = '';
  let steamStatusLine = '';
  if (options.gameName && Number.isFinite(options.periodStartMs) && Number.isFinite(options.periodEndMs)) {
    const steamResult = await fetchSteamReviews({
      gameName: options.gameName,
      periodStartMs: options.periodStartMs,
      periodEndMs: options.periodEndMs,
      languages: options.languages,
    });
    steamStatusLine = describeSteamCollectionStatus(steamResult);
    steamBlock =
      '\n\n---\n# 스팀 공식 appreviews 엔드포인트로 미리 수집한 원본 데이터(코드가 직접 가져옴, 가공 전)\n' +
      steamStatusLine +
      '\n\n' +
      JSON.stringify(steamResult, null, 2) +
      '\n\n(steamid는 아직 비식별화 전입니다 — 4단계 게이트에서 근거ID로 치환해서 최종 결과에는 원본 steamid가 남지 않게 하세요.)' +
      '\n(위 [스팀 수집 상태] 줄을 결과 맨 앞에 그대로 옮겨 적으세요. "완전 수집"이 아닌데 "기간 내 자료 전부"인 것처럼 쓰지 마세요.)';
  }

  const messages = [{ role: 'user', content: inputText + steamBlock }];
  const tools = [
    {
      type: 'web_search_20260209',
      name: 'web_search',
      max_uses: 8,
      allowed_domains: APPROVED_DOMAINS,
    },
    {
      type: 'web_fetch_20260209',
      name: 'web_fetch',
      max_uses: 8,
      allowed_domains: APPROVED_DOMAINS,
    },
  ];

  const costLimitUsd =
    Number.isFinite(options.costLimitAmount) && options.costLimitCurrency
      ? toUsd(options.costLimitAmount, options.costLimitCurrency)
      : undefined;

  let estimatedInputCost = 0;
  if (typeof costLimitUsd === 'number') {
    // 비용 없는 사전 확인: 실제 호출 전에 입력 토큰 수만 미리 센다
    // count_tokens 엔드포인트는 web_search/web_fetch 같은 서버 도구를 지원하지 않아 tools 없이 계산한다
    const counted = await client.messages.countTokens({ model: MODEL, system, messages });
    estimatedInputCost = (counted.input_tokens / 1e6) * PRICING.input;
    if (estimatedInputCost >= costLimitUsd) {
      throw new Error(
        `[호출 거부] 이유: 지시문+입력값만으로도 예상 비용($${estimatedInputCost.toFixed(4)})이 이미 설정한 상한($${costLimitUsd.toFixed(4)})을 넘습니다. ` +
        `이 요청은 최소 $${estimatedInputCost.toFixed(4)}보다 큰 상한을 줘야 시도라도 됩니다.`
      );
    }
  }

  const stream = client.messages.stream({ model: MODEL, max_tokens: MAX_OUTPUT_TOKENS, system, messages, tools });

  let text = '';
  let cutOff = false;
  let costAtCutoff = 0;

  for await (const event of stream) {
    if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
      text += event.delta.text;
    }
    if (
      typeof costLimitUsd === 'number' &&
      event.type === 'message_delta' &&
      event.usage &&
      typeof event.usage.output_tokens === 'number'
    ) {
      const runningCost = estimatedInputCost + (event.usage.output_tokens / 1e6) * PRICING.output;
      if (runningCost >= costLimitUsd) {
        cutOff = true;
        costAtCutoff = runningCost;
        stream.abort();
        break;
      }
    }
  }

  // 스팀 수집 상태는 Claude의 서술에 맡기지 않고, 코드가 직접 결과 맨 앞에 못박아 둔다
  // (모델이 빠뜨리거나 완곡하게 바꿔 써도 사용자가 항상 진짜 상태를 볼 수 있도록)
  const steamStatusPrefix = steamStatusLine ? steamStatusLine + '\n\n' : '';

  if (cutOff) {
    // 지금 설정(최대 출력 토큰 상한 기준)대로 끝까지 갔을 때의 이론상 최대 비용 — 검색/조회 도구가 추가로 읽어들이는 내용은
    // 미리 알 수 없어 포함하지 않았으므로, 실제 필요 금액은 이보다 더 클 수 있다.
    const theoreticalCeiling = estimatedInputCost + (MAX_OUTPUT_TOKENS / 1e6) * PRICING.output;
    return (
      steamStatusPrefix +
      text +
      '\n\n[비용 상한 도달로 중단됨]\n' +
      `- 이유: 여기까지 실제로 쓴 비용(약 $${costAtCutoff.toFixed(4)})이 설정한 상한($${costLimitUsd.toFixed(4)})에 닿아서 중단했습니다.\n` +
      `- 지금 설정으로 끝까지 갔을 때 이론상 최대 비용은 약 $${theoreticalCeiling.toFixed(4)}입니다(검색·조회 도구가 읽어오는 내용에 따라 이보다 더 늘 수 있습니다).\n` +
      `- 해당 기간의 모든 자료를 빠짐없이 다 보는 데 정확히 얼마가 필요한지는 실제 게시물 수에 따라 달라 미리 정확한 금액을 알려드릴 수 없습니다. 상한을 위 최대 비용보다 넉넉히(예: 2~3배) 올려서 다시 시도해 보시는 것을 권장합니다.`
    );
  }

  const finalMessage = await stream.finalMessage();
  const finalText = finalMessage.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n');
  return steamStatusPrefix + finalText;
}

module.exports = { callAgent, fetchSteamReviews, resolveSteamAppId, describeSteamCollectionStatus, STEAM_LANGUAGES };

if (require.main === module) {
  const chunks = [];
  process.stdin.on('data', (chunk) => chunks.push(chunk));
  process.stdin.on('end', async () => {
    const inputText = Buffer.concat(chunks).toString('utf8').trim();
    if (!inputText) {
      console.error('입력이 비어 있습니다. 표준입력(stdin)으로 글 한 덩어리를 전달해주세요.');
      process.exit(1);
    }
    try {
      const result = await callAgent(inputText);
      console.log(result);
    } catch (err) {
      console.error('담당자 호출 실패:', err.message);
      process.exit(1);
    }
  });
}
