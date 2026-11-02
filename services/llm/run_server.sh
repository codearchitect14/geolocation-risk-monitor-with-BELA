#!/usr/bin/env bash
# Start llama.cpp's llama-server with the local model, bound to localhost only.
# All layers are offloaded to the Apple GPU (Metal). Stop with Ctrl+C or `services/llm/run_server.sh stop`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODEL="${LLM_MODEL_PATH:-$ROOT/data/raw/models/llm/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
PORT="${LLM_PORT:-8081}"
PIDFILE="$ROOT/.local/llm.pid"

if [ "${1:-}" = "stop" ]; then
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" && rm -f "$PIDFILE" && echo stopped
  exit 0
fi

mkdir -p "$ROOT/.local"
exec llama-server \
  --model "$MODEL" \
  --host 127.0.0.1 --port "$PORT" \
  --n-gpu-layers 99 \
  --ctx-size 8192 --parallel 4 \
  --temp 0 \
  --no-webui \
  --alias qwen3-4b-instruct-2507
