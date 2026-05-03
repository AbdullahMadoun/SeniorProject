#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PX4_BINARY="$REPO_ROOT/vendor/PX4-Autopilot/build/px4_sitl_default/bin/px4"
GZ_ENV="$REPO_ROOT/vendor/PX4-Autopilot/build/px4_sitl_default/rootfs/gz_env.sh"
PYTHON_BIN="${SKYLINK_AUTONOMY_PYTHON:-$REPO_ROOT/autonomy/.venv/bin/python}"

mkdir -p \
  "$REPO_ROOT/artifacts/dashboard" \
  "$REPO_ROOT/artifacts/generated_worlds" \
  "$REPO_ROOT/artifacts/live_px4" \
  "$REPO_ROOT/artifacts/planner" \
  "$REPO_ROOT/artifacts/px4_bootstrap" \
  "$REPO_ROOT/artifacts/remote_jobs" \
  "$REPO_ROOT/artifacts/replay_bundle/latest" \
  "$REPO_ROOT/artifacts/showcase/latest" \
  "$REPO_ROOT/artifacts/sitl_logs"

cd "$REPO_ROOT"

if [[ "${SKYLINK_BOOTSTRAP_ON_START:-false}" =~ ^(1|true|yes|on)$ ]]; then
  bash deploy/simulation/bootstrap_remote.sh install
fi

if [[ ! -x "$PX4_BINARY" || ! -f "$GZ_ENV" ]]; then
  bash deploy/simulation/bootstrap_remote.sh build
fi

if [[ "${SKYLINK_COMPANION_AUTOSTART:-true}" =~ ^(1|true|yes|on)$ ]]; then
  companion_port="${SKYLINK_COMPANION_MJPEG_PORT:-8765}"
  if ! ss -ltn | grep -q ":${companion_port} "; then
    PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" \
    SKYLINK_COMPANION_MJPEG_PORT="$companion_port" \
    SKYLINK_COMPANION_CAMERA_HZ="${SKYLINK_COMPANION_CAMERA_HZ:-15.0}" \
      "$PYTHON_BIN" "$REPO_ROOT/autonomy/companion/rpi_companion_sim.py" \
      >> "$REPO_ROOT/artifacts/sitl_logs/companion_autostart.log" 2>&1 &
    echo "[ENTRYPOINT] companion MJPEG autostart pid=$! port=$companion_port"
  fi
fi

exec "$PYTHON_BIN" "$REPO_ROOT/autonomy/scripts/mission_api.py" \
  --host 0.0.0.0 \
  --port "${SKYLINK_MISSION_API_PORT:-8625}" \
  --cpu-core "${SKYLINK_API_CPU_CORE:-0}"
