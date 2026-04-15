#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/SeniorProject/training_pilot
CURATED="$ROOT/tensorboard_curated"
RUNS="$ROOT/runs"
LOG="$ROOT/artifacts/logs/ensemble_tensorboard.log"

rm -rf "$CURATED"
mkdir -p "$CURATED/v5" "$CURATED/ensemble"

link_if_exists() {
  local target="$1"
  local alias_path="$2"
  if [[ -d "$target" ]]; then
    ln -s "$target" "$alias_path"
  fi
}

link_if_exists "$RUNS/yolov8m_v5_production_final2" "$CURATED/v5/production"

link_if_exists "$RUNS/yolo12s_rezzzq_custom" "$CURATED/ensemble/yolo12_rdd"
link_if_exists "$RUNS/ozair_yolov8_custom" "$CURATED/ensemble/ozair_rdd"
link_if_exists "$RUNS/oracl4_yolov8_custom" "$CURATED/ensemble/oracl4_rdd"
link_if_exists "$RUNS/obc_yolov8_custom" "$CURATED/ensemble/obc_rdd"

link_if_exists "$RUNS/yolo12s_rezzzq_v5align" "$CURATED/ensemble/yolo12_v5align"
link_if_exists "$RUNS/ozair_yolov8_v5align" "$CURATED/ensemble/ozair_v5align"
link_if_exists "$RUNS/oracl4_yolov8_v5align" "$CURATED/ensemble/oracl4_v5align"
link_if_exists "$RUNS/obc_yolov8_v5align" "$CURATED/ensemble/obc_v5align"
link_if_exists "$RUNS/yolo12s_rezzzq_v5align2" "$CURATED/ensemble/yolo12_v5align2"
link_if_exists "$RUNS/ozair_yolov8_v5align2" "$CURATED/ensemble/ozair_v5align2"
link_if_exists "$RUNS/oracl4_yolov8_v5align2" "$CURATED/ensemble/oracl4_v5align2"
link_if_exists "$RUNS/obc_yolov8_v5align2" "$CURATED/ensemble/obc_v5align2"
link_if_exists "$RUNS/ensemble_metrics" "$CURATED/ensemble_metrics"

tmux kill-session -t ensemble_tensorboard 2>/dev/null || true
tmux new -d -s ensemble_tensorboard "tensorboard --logdir $CURATED --host 127.0.0.1 --port 6006 > $LOG 2>&1"

sleep 4
echo "CURATED=$CURATED"
find "$CURATED" -maxdepth 3 -type l | sort
python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:6006/", timeout=5).status)
PY
