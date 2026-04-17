#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export LIVE_PX4_VALIDATOR_SCRIPT="$SCRIPT_DIR/configure_live_px4_precision_landing.py"
export LIVE_PX4_VALIDATOR_LABEL="PRECISION_LANDING_PROFILE"
export MAVSDK_CONNECT_TIMEOUT_S="${MAVSDK_CONNECT_TIMEOUT_S:-30}"
exec "$SCRIPT_DIR/live_px4_probe_linux.sh" "$@"
