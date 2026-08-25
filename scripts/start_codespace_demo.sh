#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
corpus_source="$repo_dir/fixtures/corpus/pubg_steam_demo.sqlite3"
corpus_target="$repo_dir/.data/corpus/pubg_steam.sqlite3"
backend_pid=""
frontend_pid=""

cleanup() {
  local pid
  for pid in "$frontend_pid" "$backend_pid"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$frontend_pid" "$backend_pid"; do
    [[ -z "$pid" ]] || wait "$pid" 2>/dev/null || true
  done
}

wait_for_url() {
  local name="$1" url="$2" pid="$3" attempt
  for ((attempt = 1; attempt <= 60; attempt++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '%s\n' "$name이(가) 준비되기 전에 종료됐습니다." >&2
      return 1
    fi
    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf '%s\n' "$name 준비 시간을 초과했습니다: $url" >&2
  return 1
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  printf '%s\n' "Codespaces secret ANTHROPIC_API_KEY가 필요합니다." >&2
  exit 1
fi
if [[ ! -f "$corpus_source" ]]; then
  printf '%s\n' "안전 시연 코퍼스가 없습니다: $corpus_source" >&2
  exit 1
fi

cd "$repo_dir"
mkdir -p "$(dirname -- "$corpus_target")"
install -m 600 "$corpus_source" "$corpus_target"

export PUBLIC_DEMO_MODE=1
export PUBLIC_DEMO_MAX_REQUESTS="${PUBLIC_DEMO_MAX_REQUESTS:-12}"
export PUBLIC_DEMO_MAX_USD="${PUBLIC_DEMO_MAX_USD:-3}"
export LLM_PROVIDER=claude
export CLAUDE_RAG_MODEL=claude-sonnet-5
export CLAUDE_REDTEAM_MODEL=claude-sonnet-5
export CLAUDE_AUDIT_MODEL=claude-sonnet-5
export CLAUDE_UPDATE_EVIDENCE_MODEL=claude-sonnet-5
export CLAUDE_UPDATE_PERSONA_MODEL=claude-haiku-4-5-20251001
export CLAUDE_UPDATE_REDTEAM_MODEL=claude-sonnet-5
export CLAUDE_UPDATE_AUDIT_MODEL=claude-sonnet-5
export CLAUDE_UPDATE_COLLECTOR_MODEL=claude-sonnet-5
export NEXT_TELEMETRY_DISABLED=1

NEXT_PUBLIC_API_URL="" npm --prefix frontend run build

"$repo_dir/.venv/bin/uvicorn" backend.app.main:app --host 127.0.0.1 --port 8000 &
backend_pid="$!"
wait_for_url "FastAPI" "http://127.0.0.1:8000/health" "$backend_pid"

NEXT_PUBLIC_API_URL="" frontend/node_modules/.bin/next start frontend --hostname 0.0.0.0 --port 3000 &
frontend_pid="$!"
wait_for_url "Next.js" "http://127.0.0.1:3000" "$frontend_pid"

if [[ -n "${CODESPACE_NAME:-}" ]]; then
  forwarding_domain="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  printf '\n%s\n' "시연 URL: https://${CODESPACE_NAME}-3000.${forwarding_domain}"
else
  printf '\n%s\n' "로컬 URL: http://localhost:3000"
fi
printf '%s\n\n' "Codespaces Ports 탭에서 3000 포트를 Public으로 바꾼 뒤 URL을 공유하세요. 8000과 8787은 공개하지 마세요."

# ponytail: 데모는 한 프로세스 쌍만 실행한다. 서비스를 수평 확장할 때 프로세스 관리자로 교체한다.
set +e
wait -n "$backend_pid" "$frontend_pid"
status="$?"
set -e
exit "$status"
