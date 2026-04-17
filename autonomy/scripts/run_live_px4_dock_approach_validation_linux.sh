#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export LIVE_PX4_VALIDATOR_SCRIPT="$SCRIPT_DIR/validate_live_px4_dock_approach.py"
export LIVE_PX4_VALIDATOR_LABEL="DOCK_APPROACH_VALIDATION"
export LANDING_TARGET_DIRECT_PX4="${LANDING_TARGET_DIRECT_PX4:-1}"
exec "$SCRIPT_DIR/live_px4_probe_linux.sh" "$@"
