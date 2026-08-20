'use strict';

// Claude(Anthropic API)를 실제로 부르는 부분. 데이터 준비(수집→기간필터→중복제거/짧은글삭제→벡터화)는
// prepare-evidence.js가 API 없이 전부 처리하고, 이 파일은 그 결과 위에 Claude의 문서화 판단만 얹는다.

const fs = require('fs');
const path = require('path');
const Anthropic = require('@anthropic-ai/sdk');
const { STEAM_LANGUAGES, resolveSteamAppId } = require('./steam-db.js');
const { prepareEvidence } = require('./prepare-evidence.js');

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
  '아래에 "미리 준비된 근거 데이터" 블록이 있다면, 그건 hy/prepare-evidence.js가 로컬 DB에서 기간 필터링·너무 짧은 리뷰 제거·' +
  '근접중복 병합·벡터화까지 이미 코드로 끝내둔 결과입니다. 사용자가 입력한 승인 출처 목록과 무관하게 스팀 공식 API 근거이므로 ' +
  '1단계(출처 확인)를 이미 통과했고, 3단계(중복 판정)의 유사도 병합도 이미 끝난 상태입니다 — 스스로 다시 병합/분리하지 마세요.';

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
// prepare-evidence.js가 만든 근거는 기간 전체가 다 들어있을 수 있어, Claude에게 통째로 넘기면 비용이 커진다.
// 그래서 Claude에게 보여줄 때만 언어당 개수를 제한한다(수집·벡터화 자체의 완전성과는 무관).
const MAX_EVIDENCE_PER_LANGUAGE_IN_PROMPT = 300;

function describeEvidenceStatus(evidenceResult) {
  if (!evidenceResult.found) {
    return (
      `[근거 준비 상태: 실패] "${evidenceResult.gameName}"에 해당하는 게임을 스팀에서 찾지 못했습니다. ` +
      `공식 영문/정식 명칭에 가깝게 다시 확인해주세요.`
    );
  }
  if (evidenceResult.dbMissing) {
    return (
      `[근거 준비 상태: DB 없음] 로컬 DB(hy/steam-reviews.db)가 아직 없습니다. ` +
      `먼저 hy/collector.js를 실행해서 리뷰를 수집해야 조회할 수 있습니다.`
    );
  }

  const base =
    `대상: ${evidenceResult.matchedName}(appid ${evidenceResult.appid}) · 조회한 언어 ${evidenceResult.perLanguage.length}개 · ` +
    `원본 ${evidenceResult.totalRaw}건 → 짧은 리뷰 제거·중복 병합 후 최종 ${evidenceResult.totalFinal}건`;

  // collectionStatus: 'complete' | 'partial'(직전 수집/동기화에 오류 있었음) | 'incomplete'(더 과거 쪽 아직 미수집) | 'unknown'(기록 없음)
  const notComplete = evidenceResult.perLanguage.filter((p) => p.collectionStatus !== 'complete');
  if (notComplete.length === 0) {
    return `[근거 준비 상태: 완전 수집] 조회한 모든 언어권의 DB 수집이 이 기간에 대해 완료된 상태입니다. ${base}`;
  }
  const detail = notComplete.map((p) => `${p.language}(${p.collectionStatus})`).join(', ');
  return (
    `[근거 준비 상태: 일부만 수집됨(미완료/오류/기록없음)] 다음 언어권은 신뢰할 수 없습니다 — ${detail}. ` +
    `지금 있는 게 이 기간의 "전부"라는 보장이 없습니다(hy/collector.js를 더 돌리면 채워집니다). ${base}`
  );
}

async function callAgent(inputText, options = {}) {
  const client = new Anthropic({ apiKey: loadApiKey() });
  const system = loadSystemPrompt();

  let evidenceBlock = '';
  let evidenceStatusLine = '';
  let evidenceResult = null;
  if (options.gameName && Number.isFinite(options.periodStartMs) && Number.isFinite(options.periodEndMs)) {
    evidenceResult = await prepareEvidence({
      gameName: options.gameName,
      periodStartMs: options.periodStartMs,
      periodEndMs: options.periodEndMs,
      languages: options.languages,
    });
    evidenceStatusLine = describeEvidenceStatus(evidenceResult);

    // Claude에게 보여줄 때만 언어당 개수 제한(비용 때문) — evidenceResult.evidence 자체(반환값)는 그대로 둔다.
    const perLanguageCount = new Map();
    const evidenceForPrompt = (evidenceResult.evidence || []).filter((item) => {
      const count = perLanguageCount.get(item.language) || 0;
      if (count >= MAX_EVIDENCE_PER_LANGUAGE_IN_PROMPT) return false;
      perLanguageCount.set(item.language, count + 1);
      return true;
    });

    evidenceBlock =
      '\n\n---\n# 미리 준비된 근거 데이터(hy/prepare-evidence.js가 API 없이 처리, 가공 전 텍스트 원문 포함)\n' +
      evidenceStatusLine +
      '\n\n' +
      JSON.stringify({ perLanguage: evidenceResult.perLanguage, evidence: evidenceForPrompt }, null, 2) +
      '\n\n(steamid는 아직 비식별화 전입니다 — 4단계 게이트에서 근거ID로 치환해서 최종 결과에는 원본 steamid가 남지 않게 하세요.)' +
      '\n(위 [근거 준비 상태] 줄을 결과 맨 앞에 그대로 옮겨 적으세요. "완전 수집"이 아닌데 "기간 내 자료 전부"인 것처럼 쓰지 마세요.)' +
      '\n(duplicateCount는 이미 코드로 병합된 개수입니다 — 3단계 게이트의 중복 카운트로 그대로 쓰세요.)' +
      '\n(vector 필드는 통계적 벡터화(해싱 트릭) 결과입니다 — 다음 단계(res 등)로 넘길 때를 위한 것이니, ' +
      '피드백 번들 본문에 숫자 벡터를 그대로 나열하거나 설명하지 마세요. 번들은 사람이 읽는 문서 형태 그대로 유지하세요.)';
  }

  const messages = [{ role: 'user', content: inputText + evidenceBlock }];
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

  // 근거 준비 상태는 Claude의 서술에 맡기지 않고, 코드가 직접 결과 맨 앞에 못박아 둔다
  // (모델이 빠뜨리거나 완곡하게 바꿔 써도 사용자가 항상 진짜 상태를 볼 수 있도록)
  const statusPrefix = evidenceStatusLine ? evidenceStatusLine + '\n\n' : '';
  // 다음 단계(res 등)로 실제로 넘어가는 벡터화 결과 — 텍스트 번들과 별도로 항상 같이 반환한다.
  const evidence = evidenceResult && evidenceResult.evidence ? evidenceResult.evidence : [];

  if (cutOff) {
    // 지금 설정(최대 출력 토큰 상한 기준)대로 끝까지 갔을 때의 이론상 최대 비용 — 검색/조회 도구가 추가로 읽어들이는 내용은
    // 미리 알 수 없어 포함하지 않았으므로, 실제 필요 금액은 이보다 더 클 수 있다.
    const theoreticalCeiling = estimatedInputCost + (MAX_OUTPUT_TOKENS / 1e6) * PRICING.output;
    return {
      text:
        statusPrefix +
        text +
        '\n\n[비용 상한 도달로 중단됨]\n' +
        `- 이유: 여기까지 실제로 쓴 비용(약 $${costAtCutoff.toFixed(4)})이 설정한 상한($${costLimitUsd.toFixed(4)})에 닿아서 중단했습니다.\n` +
        `- 지금 설정으로 끝까지 갔을 때 이론상 최대 비용은 약 $${theoreticalCeiling.toFixed(4)}입니다(검색·조회 도구가 읽어오는 내용에 따라 이보다 더 늘 수 있습니다).\n` +
        `- 해당 기간의 모든 자료를 빠짐없이 다 보는 데 정확히 얼마가 필요한지는 실제 게시물 수에 따라 달라 미리 정확한 금액을 알려드릴 수 없습니다. 상한을 위 최대 비용보다 넉넉히(예: 2~3배) 올려서 다시 시도해 보시는 것을 권장합니다.`,
      evidence,
    };
  }

  const finalMessage = await stream.finalMessage();
  const finalText = finalMessage.content
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n');
  return { text: statusPrefix + finalText, evidence };
}

module.exports = { callAgent, resolveSteamAppId, STEAM_LANGUAGES };

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
      const { text: resultText, evidence } = await callAgent(inputText);
      console.log(resultText);
      console.error(`(참고: 벡터화된 근거 ${evidence.length}건도 반환값에 함께 담겨 있습니다 — CLI에서는 텍스트만 출력)`);
    } catch (err) {
      console.error('담당자 호출 실패:', err.message);
      process.exit(1);
    }
  });
}
