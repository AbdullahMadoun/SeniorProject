#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
AUTONOMY_ROOT="$REPO_ROOT/autonomy"
PX4_REPO="$REPO_ROOT/vendor/PX4-Autopilot"
VENV_DIR="$AUTONOMY_ROOT/.venv"
STATUS_DIR="$REPO_ROOT/artifacts/px4_bootstrap"
STATUS_PATH="$STATUS_DIR/remote_status.json"
LOG_PATH="$STATUS_DIR/bootstrap_remote.log"

mkdir -p "$STATUS_DIR"
exec > >(tee -a "$LOG_PATH") 2>&1

log() {
  printf '[%s] %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

ensure_repo_layout() {
  if [ ! -d "$PX4_REPO" ]; then
    log "Missing PX4 checkout at $PX4_REPO"
    exit 1
  fi
  if [ ! -d "$AUTONOMY_ROOT" ]; then
    log "Missing autonomy checkout at $AUTONOMY_ROOT"
    exit 1
  fi
}

install_os_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get not available; skipping OS package bootstrap"
    return
  fi
  log "Installing OS packages required for PX4 SITL and Python tooling"
  as_root apt-get update
  as_root apt-get install -y --no-install-recommends \
    bash ca-certificates curl git jq lsb-release python3 python3-pip python3-venv rsync wget
}

sync_submodules() {
  if [ ! -d "$REPO_ROOT/.git" ]; then
    log "Skipping git submodule sync because .git metadata is not present"
    return
  fi
  log "Syncing git submodules"
  git -C "$REPO_ROOT" submodule sync --recursive
  git -C "$REPO_ROOT" submodule update --init --recursive
}

install_px4_dependencies() {
  log "Running PX4 Ubuntu setup"
  (
    cd "$PX4_REPO"
    bash ./Tools/setup/ubuntu.sh --no-nuttx
  )
}

ensure_venv() {
  log "Preparing autonomy virtual environment"
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip wheel "setuptools<82"
  python -m pip install mavsdk pymavlink psutil numpy pyulog fastapi uvicorn
}

build_px4() {
  log "Building PX4 SITL (first build can take several minutes)"
  (
    cd "$PX4_REPO"
    env HEADLESS=1 make px4_sitl gz_x500
  )
}

write_status() {
  python3 - "$STATUS_PATH" "$REPO_ROOT" "$AUTONOMY_ROOT" "$PX4_REPO" "$VENV_DIR" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
autonomy_root = Path(sys.argv[3])
px4_repo = Path(sys.argv[4])
venv_dir = Path(sys.argv[5])
venv_python = venv_dir / "bin" / "python"
px4_binary = px4_repo / "build" / "px4_sitl_default" / "bin" / "px4"


def run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return (completed.stdout.strip() or completed.stderr.strip() or "").strip()


payload = {
    "repo_root": str(repo_root),
    "autonomy_root": str(autonomy_root),
    "px4_repo": str(px4_repo),
    "venv_python": str(venv_python),
    "venv_python_present": venv_python.exists(),
    "px4_binary": str(px4_binary),
    "px4_binary_present": px4_binary.exists(),
    "python_version": run(["python3", "--version"]),
    "venv_python_version": run([str(venv_python), "--version"]) if venv_python.exists() else "missing",
    "gz_version": run(["bash", "-lc", "if command -v gz >/dev/null 2>&1; then gz sim --versions | head -n 1; else echo missing; fi"]),
}
status_path.parent.mkdir(parents=True, exist_ok=True)
status_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2))
PY
}

bootstrap() {
  ensure_repo_layout
  install_os_packages
  sync_submodules
  install_px4_dependencies
  ensure_venv
  build_px4
  write_status
}

install_only() {
  ensure_repo_layout
  install_os_packages
  sync_submodules
  install_px4_dependencies
  ensure_venv
  write_status
}

usage() {
  cat <<'EOF'
Usage: bootstrap_remote.sh <bootstrap|install|build|status>

bootstrap  Install OS deps, sync submodules, prepare autonomy venv, and build PX4 SITL.
install    Install OS deps, sync submodules, and prepare the autonomy venv.
build      Build PX4 SITL only.
status     Emit a JSON status snapshot to artifacts/px4_bootstrap/remote_status.json.
EOF
}

main() {
  local command="${1:-bootstrap}"
  case "$command" in
    bootstrap)
      bootstrap
      ;;
    install)
      install_only
      ;;
    build)
      ensure_repo_layout
      build_px4
      write_status
      ;;
    status)
      ensure_repo_layout
      write_status
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
