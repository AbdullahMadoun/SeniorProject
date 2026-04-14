#!/usr/bin/env bash
set -euo pipefail

cd /root/SeniorProject/training_pilot

CONFIG="configs/models/yolov8m_v5_production.yaml"
SESSION_TRAIN="production_v5_train"
SESSION_WANDB="production_v5_wandb"
STAMP="$(date +%Y%m%d_%H%M%S)"
TRAIN_LOG="artifacts/logs/production_v5_train_${STAMP}.log"
WANDB_LOG="artifacts/logs/production_v5_wandb_${STAMP}.log"

mkdir -p artifacts/logs

if tmux has-session -t "${SESSION_TRAIN}" 2>/dev/null; then
  echo "[FAIL] tmux session '${SESSION_TRAIN}' already exists" >&2
  exit 1
fi

if tmux has-session -t "${SESSION_WANDB}" 2>/dev/null; then
  echo "[FAIL] tmux session '${SESSION_WANDB}' already exists" >&2
  exit 1
fi

tmux new-session -d -s "${SESSION_TRAIN}" \
  "cd /root/SeniorProject/training_pilot && PYTHONPATH=. python3 -c \"from ultralytics import YOLO; import yaml; cfg = yaml.safe_load(open('${CONFIG}')); model = YOLO(cfg.pop('model')); cfg.pop('trainer', None); model.train(**cfg)\" > ${TRAIN_LOG} 2>&1"

cat <<EOF
[READY] V5 production launch staged
train_session=${SESSION_TRAIN}
wandb_session=${SESSION_WANDB}
train_log=${TRAIN_LOG}
config=${CONFIG}
EOF

