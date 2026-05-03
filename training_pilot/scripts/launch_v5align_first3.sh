#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
DEVICE="${DEVICE:-0}"
WORKERS="${WORKERS:-8}"

run_dir_for_model() {
  local model_id="$1"
  case "$model_id" in
    yolo12s_rezzzq) echo "${ROOT_DIR}/runs/yolo12s_rezzzq_v5align" ;;
    ozair_yolov8) echo "${ROOT_DIR}/runs/ozair_yolov8_v5align" ;;
    oracl4_yolov8) echo "${ROOT_DIR}/runs/oracl4_yolov8_v5align" ;;
    *) return 1 ;;
  esac
}

run_or_resume_model() {
  local model_id="$1"
  local run_dir
  run_dir="$(run_dir_for_model "$model_id")"
  if [[ -f "${run_dir}/weights/last.pt" && -f "${run_dir}/args.yaml" ]]; then
    echo "==> resuming ${model_id} from ${run_dir}"
    "${PYTHON_BIN}" "${ROOT_DIR}/scripts/resume_model.py" \
      --project-root "${ROOT_DIR}" \
      --model-id "${model_id}" \
      --run-dir "${run_dir}" \
      --device "${DEVICE}" \
      --workers "${WORKERS}"
  else
    echo "==> training ${model_id}"
    "${PYTHON_BIN}" "${ROOT_DIR}/scripts/train_model.py" \
      --project-root "${ROOT_DIR}" \
      --model-id "${model_id}" \
      --device "${DEVICE}" \
      --workers "${WORKERS}" \
      --stage initial
  fi
}

for model_id in yolo12s_rezzzq ozair_yolov8 oracl4_yolov8; do
  run_or_resume_model "${model_id}"
done
