#!/usr/bin/env bash
# Run the Road Inspection VLM API server
set -euo pipefail

export API_KEY="${API_KEY:-road-inspector-secret-key-2024}"
export MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-VL-7B-Instruct}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-17612}"
export GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
export MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
export MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-16384}"
export PROMPT_FILE="${PROMPT_FILE:-/root/prompt.txt}"

echo "=== Road Inspection VLM API ==="
echo "Model:    $MODEL_NAME"
echo "Host:     $HOST:$PORT"
echo "API Key:  ${API_KEY:0:8}..."
echo "Prompt:   $PROMPT_FILE"
echo "==============================="

cd /root/road_inspector
exec python3 main.py
