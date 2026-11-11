#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/studybuddy-backend"
CLIENT_DIR="$ROOT_DIR/studybuddy-client"

API_BASE="$(grep -E '^VITE_API_BASE=' "$CLIENT_DIR/.env.local" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
API_BASE="${API_BASE:-http://127.0.0.1:8001}"
BACKEND_PORT="$(python3 - <<PY
from urllib.parse import urlparse
url = urlparse("$API_BASE")
print(url.port or 80)
PY
)"

echo "前端 API: $API_BASE"
echo "后端端口: $BACKEND_PORT"

if ! command -v lsof >/dev/null 2>&1; then
  echo "缺少 lsof，无法检查端口占用" >&2
  exit 1
fi

if lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $BACKEND_PORT 已被占用，请先关闭旧后端进程。"
  lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN
  exit 1
fi

if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 5173 已被占用，请先关闭旧前端进程。"
  lsof -nP -iTCP:5173 -sTCP:LISTEN
  exit 1
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${CLIENT_PID:-}" ]]; then
    kill "$CLIENT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

(
  cd "$BACKEND_DIR"
  ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

(
  cd "$CLIENT_DIR"
  npm run dev -- --host 127.0.0.1 --port 5173
) &
CLIENT_PID=$!

echo "本地服务启动中："
echo "- 后端 $API_BASE"
echo "- 前端 http://127.0.0.1:5173/"
echo "按 Ctrl+C 停止两个服务。"

wait
