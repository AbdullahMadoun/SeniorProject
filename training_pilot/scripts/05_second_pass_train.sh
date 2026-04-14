#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
DEVICE="${DEVICE:-0}"
WORKERS="${WORKERS:-4}"

for model_id in yolo12s_rezzzq ozair_yolov8 oracl4_yolov8 obc_yolov8; do
  echo "==> hard-negative fine-tune ${model_id}"
  "${PYTHON_BIN}" "${ROOT_DIR}/scripts/train_model.py" \
    --project-root "${ROOT_DIR}" \
    --model-id "${model_id}" \
    --device "${DEVICE}" \
    --workers "${WORKERS}" \
    --stage hard_negative
done
