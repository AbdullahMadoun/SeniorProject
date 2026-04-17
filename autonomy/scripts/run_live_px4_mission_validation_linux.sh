#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export LIVE_PX4_VALIDATOR_SCRIPT="$SCRIPT_DIR/validate_live_px4_mission.py"
export LIVE_PX4_VALIDATOR_LABEL="MISSION_VALIDATION"
exec "$SCRIPT_DIR/live_px4_probe_linux.sh" "$@"
