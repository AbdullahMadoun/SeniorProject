#!/usr/bin/env bash
# Run the Road Inspection VLM API server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  # shellcheck disable=SC1091
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

export API_KEY="${API_KEY:-road-inspector-secret-key-2024}"
export MODEL_NAME="${MODEL_NAME:-${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct-AWQ}}"
export VLM_MODEL="${VLM_MODEL:-$MODEL_NAME}"
export ENABLE_VLM="${ENABLE_VLM:-true}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-17612}"
export GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
export MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
export MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-16384}"
export PROMPT_FILE="${PROMPT_FILE:-$SCRIPT_DIR/prompt.txt}"

echo "=== Road Inspection VLM API ==="
echo "Model:    $MODEL_NAME"
echo "VLM:      $ENABLE_VLM"
echo "Host:     $HOST:$PORT"
echo "API Key:  ${API_KEY:0:8}..."
echo "Prompt:   $PROMPT_FILE"
echo "==============================="

cd "$SCRIPT_DIR"
exec python3 main.py
