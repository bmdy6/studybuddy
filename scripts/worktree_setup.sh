#!/usr/bin/env bash
# 新建 worktree 后首次进入时运行：安装前端依赖 + 建后端虚拟环境。
# 用法：cd <worktree根> && scripts/worktree_setup.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/studybuddy-backend"
CLIENT_DIR="$ROOT_DIR/studybuddy-client"

echo "==> Worktree 根目录: $ROOT_DIR"
echo ""

# ---------- 前端依赖 ----------
if [[ -f "$CLIENT_DIR/package.json" ]]; then
  echo "==> 安装前端依赖 (npm install)..."
  (
    cd "$CLIENT_DIR"
    npm install
  )
  echo "前端依赖安装完成。"
else
  echo "跳过前端：未找到 $CLIENT_DIR/package.json"
fi
echo ""

# ---------- 后端虚拟环境 ----------
if [[ -f "$BACKEND_DIR/requirements.txt" ]]; then
  if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
    echo "==> 创建后端虚拟环境 (.venv)..."
    (
      cd "$BACKEND_DIR"
      python3 -m venv .venv
    )
  else
    echo "后端 .venv 已存在，跳过创建。"
  fi
  echo "==> 安装后端依赖 (pip install -r requirements.txt)..."
  (
    cd "$BACKEND_DIR"
    .venv/bin/pip install -r requirements.txt
  )
  echo "后端依赖安装完成。"
else
  echo "跳过后端：未找到 $BACKEND_DIR/requirements.txt"
fi

echo ""
echo "==> Worktree 环境就绪。"
echo "    后端启动: cd studybuddy-backend && .venv/bin/uvicorn app.main:app --port 8001"
echo "    前端启动: cd studybuddy-client && npm run dev"
echo "    或直接用: scripts/dev_local.sh"
