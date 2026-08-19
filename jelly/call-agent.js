const fs = require("fs");
const path = require("path");
const http = require("http");

const ROOT_DIR = path.join(__dirname, "..");
const ENV_PATH = path.join(ROOT_DIR, ".env");
const ROLE_PATH = path.join(__dirname, "..", ".claude", "agents", "jelly.md");
const MODEL = process.env.CLAUDE_REDTEAM_MODEL?.trim() || "claude-haiku-4-5-20251001";
const configuredMaxTokens = Number(process.env.CLAUDE_MAX_OUTPUT_TOKENS || "3000");
const MAX_TOKENS = Number.isSafeInteger(configuredMaxTokens) && configuredMaxTokens > 0
  ? Math.min(configuredMaxTokens, 3000)
  : 3000;
const PORT = process.env.CALL_AGENT_PORT || 8787;

function loadApiKey() {
  const environmentKey = process.env.ANTHROPIC_API_KEY?.trim();
  if (environmentKey) return environmentKey;
  if (!fs.existsSync(ENV_PATH)) {
    throw new Error(`ANTHROPIC_API_KEY가 ${ENV_PATH} 에 없습니다.`);
  }
  const envText = fs.readFileSync(ENV_PATH, "utf8");
  for (const line of envText.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim();
    if (key === "ANTHROPIC_API_KEY") return value;
  }
  throw new Error(`ANTHROPIC_API_KEY가 ${ENV_PATH} 에 없습니다.`);
}

function loadRolePrompt() {
  return fs.readFileSync(ROLE_PATH, "utf8");
}

async function callAgent(inputText) {
  const apiKey = loadApiKey();
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY 값이 비어 있습니다.");
  const rolePrompt = loadRolePrompt();

  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: rolePrompt,
      messages: [{ role: "user", content: inputText }],
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(`API 오류 (${response.status}): ${data.error?.message || JSON.stringify(data)}`);
  }
  if (data.stop_reason === "refusal") {
    throw new Error("모델이 요청을 거부했습니다.");
  }

  const textBlock = data.content.find((block) => block.type === "text");
  return textBlock ? textBlock.text : "";
}

// index.html의 [정보 입력] 표가 그대로 넘기는 행 배열을 분석해서, 행마다 동향/원인/개선과
// 전체 종합 문단을 담당자(Claude, jelly.md 역할)가 직접 판단하게 합니다.
const ANALYZE_SCHEMA = {
  type: "object",
  properties: {
    rows: {
      type: "array",
      items: {
        type: "object",
        properties: {
          index: { type: "integer" },
          trend: { type: "string", enum: ["긍정", "중립", "부정", "위험"] },
          cause: { type: "string" },
          fix: { type: "string" },
        },
        required: ["index", "trend", "cause", "fix"],
        additionalProperties: false,
      },
    },
    // synthesis는 하나의 긴 문단이 아니라, 우선순위 순서대로 나눈 개선 방향 목록입니다.
    // 화면에서 번호가 매겨진 구조도(순서도) 형태로 그립니다.
    synthesis: {
      type: "array",
      items: {
        type: "object",
        properties: {
          title: { type: "string" },
          description: { type: "string" },
        },
        required: ["title", "description"],
        additionalProperties: false,
      },
    },
  },
  required: ["rows", "synthesis"],
  additionalProperties: false,
};

async function analyzeRows(rows) {
  const apiKey = loadApiKey();
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY 값이 비어 있습니다.");
  const rolePrompt = loadRolePrompt();

  const userText =
    "아래는 화면의 [정보 입력] 표에서 넘어온 근거 행 목록입니다(JSON 배열). 각 행은 index로 구분됩니다.\n" +
    "각 행마다 근거 내용(content)을 보고 동향(긍정/중립/부정/위험 중 하나), 원인(한 문장), " +
    "개선 방향(한 문장, 판단하기 어려우면 빈 문자열)을 정하세요. " +
    "원인과 개선 방향 문장은 완전한 문장으로 쓰고 반드시 마침표(.)로 끝내세요. " +
    "근거 내용이 비어 있는 행은 동향을 중립으로 두고 원인·개선 방향은 빈 문자열로 두세요.\n" +
    "그리고 전체 행을 종합한 개선 방향(synthesis)을 하나의 긴 문단이 아니라, " +
    "가장 근거가 많고 시급한 것부터 순서대로 2~4개의 항목으로 나눠 작성하세요. " +
    "각 항목은 title(5~15자 정도의 짧은 테마명, 마침표 없이)과 description(1~2문장, 마침표로 끝냄)으로 구성합니다.\n\n" +
    JSON.stringify(rows, null, 2);

  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: rolePrompt,
      messages: [{ role: "user", content: userText }],
      output_config: { format: { type: "json_schema", schema: ANALYZE_SCHEMA } },
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(`API 오류 (${response.status}): ${data.error?.message || JSON.stringify(data)}`);
  }
  if (data.stop_reason === "refusal") {
    throw new Error("모델이 요청을 거부했습니다.");
  }

  const textBlock = data.content.find((block) => block.type === "text");
  if (!textBlock) throw new Error("응답에서 결과를 찾지 못했습니다.");
  const parsed = JSON.parse(textBlock.text);

  // 모델이 마침표를 빼먹는 경우에 대비해 원인·개선 문장 끝에 마침표를 보장합니다.
  const ensureFullStop = (s) => {
    const t = (s ?? "").trim();
    if (!t) return t;
    return /[.!?]$/.test(t) ? t : `${t}.`;
  };
  parsed.rows = (parsed.rows || []).map((r) => ({
    ...r,
    cause: ensureFullStop(r.cause),
    fix: ensureFullStop(r.fix),
  }));
  parsed.synthesis = (parsed.synthesis || []).map((s) => ({
    title: (s.title ?? "").trim(),
    description: ensureFullStop(s.description),
  }));

  return parsed;
}

module.exports = { callAgent, analyzeRows };

function startServer() {
  const server = http.createServer((req, res) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    if (req.method !== "POST" || (req.url !== "/call-agent" && req.url !== "/analyze")) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
      return;
    }

    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", async () => {
      try {
        const parsed = JSON.parse(body || "{}");

        if (req.url === "/analyze") {
          if (!Array.isArray(parsed.rows) || parsed.rows.length === 0) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "rows가 비어 있습니다." }));
            return;
          }
          const result = await analyzeRows(parsed.rows);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ result }));
          return;
        }

        if (!parsed.text || !parsed.text.trim()) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "text가 비어 있습니다." }));
          return;
        }
        const result = await callAgent(parsed.text);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ result }));
      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
  });

  server.listen(PORT, () => {
    console.log(`call-agent 서버 실행 중: http://localhost:${PORT}  (Ctrl+C로 종료)`);
  });
}

function runCli(input) {
  callAgent(input)
    .then((result) => console.log(result))
    .catch((err) => {
      console.error(err.message);
      process.exit(1);
    });
}

if (require.main === module) {
  const args = process.argv.slice(2);

  if (args[0] === "serve") {
    startServer();
  } else if (args.length > 0) {
    runCli(args.join(" "));
  } else if (!process.stdin.isTTY) {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => {
      if (!data.trim()) {
        console.error("사용법: node call-agent.js \"처리할 글\"  (또는 표준입력으로 전달, 또는 node call-agent.js serve)");
        process.exit(1);
      }
      runCli(data);
    });
  } else {
    // 인자도 표준입력도 없으면 index.html 버튼이 부를 로컬 서버를 띄웁니다.
    startServer();
  }
}
