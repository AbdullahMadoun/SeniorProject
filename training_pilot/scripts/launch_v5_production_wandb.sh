#!/usr/bin/env bash
set -euo pipefail

cd /root/SeniorProject/training_pilot

SESSION_WANDB="production_v5_wandb"
RUN_PREFIX="yolov8m_v5_production_final"
WANDB_MODE="${WANDB_MODE:-offline}"
STAMP="$(date +%Y%m%d_%H%M%S)"
WANDB_LOG="artifacts/logs/production_v5_wandb_${STAMP}.log"

mkdir -p artifacts/logs

if tmux has-session -t "${SESSION_WANDB}" 2>/dev/null; then
  echo "[FAIL] tmux session '${SESSION_WANDB}' already exists" >&2
  exit 1
fi

tmux new-session -d -s "${SESSION_WANDB}" \
  "cd /root/SeniorProject/training_pilot && while true; do RUN_DIR=\$(python3 - <<'PY'
from pathlib import Path
matches = sorted(Path('runs').glob('${RUN_PREFIX}*'), key=lambda p: p.stat().st_mtime)
print(matches[-1].resolve() if matches else '')
PY
); if [ -n \"\$RUN_DIR\" ] && [ -f \"\$RUN_DIR/results.csv\" ]; then python3 scripts/wandb_results_sidecar.py --results-csv \"\$RUN_DIR/results.csv\" --run-dir \"\$RUN_DIR\" --project SeniorProject --run-name \"\$(basename \"\$RUN_DIR\")\" --mode ${WANDB_MODE} --poll-seconds 20 --finish-on-best > ${WANDB_LOG} 2>&1; break; fi; sleep 10; done"

cat <<EOF
[READY] V5 W&B sidecar staged
wandb_session=${SESSION_WANDB}
wandb_mode=${WANDB_MODE}
wandb_log=${WANDB_LOG}
run_prefix=${RUN_PREFIX}
EOF

