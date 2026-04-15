#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="${SESSION_NAME:-maxrecall_ensemble}"
DEVICE="${DEVICE:-0}"
WORKERS="${WORKERS:-8}"
PYTHON_BIN="${PYTHON_BIN:-python}"

LOG_DIR="${ROOT_DIR}/artifacts/logs"
mkdir -p "${LOG_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BOOTSTRAP_LOG="${LOG_DIR}/ensemble_bootstrap_${STAMP}.log"

tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true

tmux new -d -s "${SESSION_NAME}" "bash -lc '
cd \"${ROOT_DIR}\"
DEVICE=\"${DEVICE}\" WORKERS=\"${WORKERS}\" PYTHON_BIN=\"${PYTHON_BIN}\" \
  bash scripts/run_ensemble_bootstrap_and_train.sh > \"${BOOTSTRAP_LOG}\" 2>&1
'"

echo "session=${SESSION_NAME}"
echo "bootstrap_log=${BOOTSTRAP_LOG}"
