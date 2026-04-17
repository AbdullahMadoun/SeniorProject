#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AUTONOMY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$AUTONOMY_ROOT/.." && pwd)"
PX4_REPO="$REPO_ROOT/vendor/PX4-Autopilot"
VENV_PYTHON="$AUTONOMY_ROOT/.venv/bin/python"
SNAPSHOT_SCRIPT="$AUTONOMY_ROOT/scripts/check_live_px4_snapshot.py"
VALIDATOR_SCRIPT="${LIVE_PX4_VALIDATOR_SCRIPT:-$SNAPSHOT_SCRIPT}"
VALIDATOR_LABEL="${LIVE_PX4_VALIDATOR_LABEL:-SNAPSHOT}"

MODEL="${1:-gz_x500}"
WORLD="${2:-}"
LOG_PATH="${3:-$REPO_ROOT/artifacts/sitl_logs/live_probe_linux_$(date +%Y%m%d_%H%M%S).log}"

mkdir -p "$(dirname "$LOG_PATH")"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Linux autonomy venv python not found: $VENV_PYTHON" >&2
  exit 1
fi

if [[ ! -d "$PX4_REPO" ]]; then
  echo "PX4 repo not found: $PX4_REPO" >&2
  exit 1
fi

if [[ ! -f "$VALIDATOR_SCRIPT" ]]; then
  echo "Validator script not found: $VALIDATOR_SCRIPT" >&2
  exit 1
fi

launch_sitl() {
  if [[ -n "$WORLD" ]]; then
    env HEADLESS=1 PX4_GZ_WORLD="$WORLD" make px4_sitl "$MODEL"
  else
    env HEADLESS=1 make px4_sitl "$MODEL"
  fi
}

cleanup() {
  if [[ -n "${sitl_pid:-}" ]]; then
    kill "$sitl_pid" 2>/dev/null || true
    wait "$sitl_pid" 2>/dev/null || true
  fi
}

pkill -f "$PX4_REPO/build/px4_sitl_default/bin/px4" 2>/dev/null || true
pkill -f "gz sim" 2>/dev/null || true
pkill -f "make px4_sitl" 2>/dev/null || true
sleep 2

cd "$PX4_REPO"
launch_sitl >"$LOG_PATH" 2>&1 &
sitl_pid=$!
trap cleanup EXIT

for _ in $(seq 1 90); do
  if grep -Eq "Startup script returned successfully|Ready for takeoff|INFO  \[commander\] home set" "$LOG_PATH"; then
    break
  fi
  if ! kill -0 "$sitl_pid" 2>/dev/null; then
    echo "PX4 SITL exited early. See $LOG_PATH" >&2
    exit 1
  fi
  sleep 2
done

echo "--- SITL LOG ($LOG_PATH) ---"
tail -n 80 "$LOG_PATH" || true

echo "--- $VALIDATOR_LABEL ---"
export LIVE_PX4_SITL_LOG_PATH="$LOG_PATH"
"$VENV_PYTHON" "$VALIDATOR_SCRIPT"
