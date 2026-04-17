#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AUTONOMY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$AUTONOMY_ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Linux autonomy venv python not found: $VENV_PYTHON" >&2
  exit 1
fi

export SKYLINK_PX4_HOST_MODE="${SKYLINK_PX4_HOST_MODE:-linux}"
export LANDING_TARGET_DIRECT_PX4="${LANDING_TARGET_DIRECT_PX4:-1}"
exec "$VENV_PYTHON" "$SCRIPT_DIR/prove_live_px4_landing_target_consumption.py" "$@"
