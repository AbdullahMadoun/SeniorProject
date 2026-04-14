#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/skylink-model-server}"
APP_DIR="${APP_DIR:-$ROOT_DIR/model_server}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/runtime}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
BIN_DIR="${BIN_DIR:-$ROOT_DIR/bin}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$BIN_DIR/cloudflared}"
STATUS_FILE="$RUNTIME_DIR/status.json"
SERVER_LOG="$RUNTIME_DIR/server.log"
TUNNEL_LOG="$RUNTIME_DIR/tunnel.log"
SERVER_PID_FILE="$RUNTIME_DIR/server.pid"
TUNNEL_PID_FILE="$RUNTIME_DIR/tunnel.pid"
TUNNEL_URL_FILE="$RUNTIME_DIR/tunnel_url.txt"

mkdir -p "$ROOT_DIR" "$RUNTIME_DIR" "$BIN_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

load_env() {
  if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a
    source "$ENV_FILE"
    set +a
  fi
  export API_KEY="${API_KEY:-road-inspector-secret-key-2024}"
  export HOST="${HOST:-0.0.0.0}"
  export PORT="${PORT:-17612}"
  export ENABLE_VLM="${ENABLE_VLM:-true}"
  if [ -z "${ENABLE_YOLO_V8:-}" ]; then
    if [ "$ENABLE_VLM" = "true" ]; then
      export ENABLE_YOLO_V8="true"
    else
      export ENABLE_YOLO_V8="false"
    fi
  else
    export ENABLE_YOLO_V8="${ENABLE_YOLO_V8}"
  fi
  export MODEL_NAME="${MODEL_NAME:-${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct-AWQ}}"
  export VLM_MODEL="${VLM_MODEL:-$MODEL_NAME}"
  export GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.80}"
  export MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
  export MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-16384}"
  export YOLO_MODEL_V8="${YOLO_MODEL_V8:-$APP_DIR/models/YOLOv8_Small_RDD.pt}"
  export YOLO_MODEL_V12="${YOLO_MODEL_V12:-rezzzq/yolo12s-road-damage-rdd2022}"
  export YOLO_V8_WEIGHTS_URL="${YOLO_V8_WEIGHTS_URL:-https://huggingface.co/oracl4/YOLOv8_Small_RDD/resolve/main/YOLOv8_Small_RDD.pt}"
  export HF_HOME="${HF_HOME:-$ROOT_DIR/.cache/huggingface}"
  export ENABLE_QUICK_TUNNEL="${ENABLE_QUICK_TUNNEL:-true}"
  export WAIT_FOR_HEALTH="${WAIT_FOR_HEALTH:-true}"
  export WAIT_FOR_TUNNEL="${WAIT_FOR_TUNNEL:-true}"
  export PREFETCH_MODELS="${PREFETCH_MODELS:-true}"
  export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
  export PUBLIC_HOST="${PUBLIC_HOST:-}"
  export PROMPT_FILE="${PROMPT_FILE:-$APP_DIR/prompt.txt}"
}

ensure_requirements() {
  if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    log "Installing OS packages"
    apt-get update
    apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv git curl wget ca-certificates \
      ffmpeg libsm6 libxext6 libglib2.0-0 lsof
    rm -rf /var/lib/apt/lists/*
  fi
}

ensure_venv() {
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtualenv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip wheel "setuptools<82"
}

install_deps() {
  load_env
  ensure_requirements
  ensure_venv
  local requirements_file="$APP_DIR/requirements.txt"
  if [ "$ENABLE_VLM" != "true" ]; then
    requirements_file="$APP_DIR/requirements-yolo.txt"
  fi
  log "Installing Python dependencies from $requirements_file"
  python -m pip install -r "$requirements_file"
}

prefetch_models() {
  load_env
  ensure_venv
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  if [ "$PREFETCH_MODELS" != "true" ]; then
    log "Skipping model prefetch"
    return
  fi
  log "Prefetching model assets"
  cmd=(python "$APP_DIR/prefetch_models.py" \
    --vlm-model "$VLM_MODEL" \
    --yolo-v12-repo "$YOLO_MODEL_V12" \
    --yolo-v8-url "$YOLO_V8_WEIGHTS_URL" \
    --yolo-v8-dest "$YOLO_MODEL_V8" \
    --cache-dir "$HF_HOME")
  if [ "$ENABLE_VLM" != "true" ]; then
    cmd+=(--skip-vlm)
  fi
  if [ "$ENABLE_YOLO_V8" != "true" ]; then
    cmd+=(--skip-yolo-v8)
  fi
  if [ -n "${HUGGINGFACE_HUB_TOKEN:-}" ]; then
    cmd+=(--hf-token "$HUGGINGFACE_HUB_TOKEN")
  fi
  "${cmd[@]}"
}

stop_server() {
  if [ -f "$SERVER_PID_FILE" ]; then
    local pid
    pid="$(cat "$SERVER_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log "Stopping existing model server ($pid)"
      kill "$pid"
      wait "$pid" || true
    fi
    rm -f "$SERVER_PID_FILE"
  fi
}

stop_tunnel() {
  if [ -f "$TUNNEL_PID_FILE" ]; then
    local pid
    pid="$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log "Stopping existing tunnel ($pid)"
      kill "$pid"
      wait "$pid" || true
    fi
    rm -f "$TUNNEL_PID_FILE"
  fi
}

wait_for_health() {
  if [ "$WAIT_FOR_HEALTH" != "true" ]; then
    return
  fi
  local health_url="http://127.0.0.1:${PORT}/health"
  log "Waiting for health endpoint: $health_url"
  for _ in $(seq 1 180); do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      log "Health endpoint is ready"
      return
    fi
    sleep 5
  done
  log "Model server health check timed out"
  return 1
}

ensure_cloudflared() {
  if [ -x "$CLOUDFLARED_BIN" ]; then
    return
  fi
  log "Downloading cloudflared"
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o "$CLOUDFLARED_BIN"
  chmod +x "$CLOUDFLARED_BIN"
}

wait_for_tunnel() {
  if [ "$WAIT_FOR_TUNNEL" != "true" ]; then
    return
  fi
  log "Waiting for Cloudflare tunnel URL"
  for _ in $(seq 1 60); do
    if grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -n 1 > "$TUNNEL_URL_FILE"; then
      if [ -s "$TUNNEL_URL_FILE" ]; then
        log "Tunnel URL ready"
        return
      fi
    fi
    sleep 2
  done
  log "Tunnel URL did not appear in time"
  return 1
}

start_server() {
  load_env
  ensure_venv
  stop_server
  mkdir -p "$(dirname "$YOLO_MODEL_V8")"
  : > "$SERVER_LOG"
  chmod +x "$APP_DIR/run.sh"
  log "Starting model server"
  (
    cd "$APP_DIR"
    nohup "$APP_DIR/run.sh" >>"$SERVER_LOG" 2>&1 &
    echo $! > "$SERVER_PID_FILE"
  )
  wait_for_health
}

start_tunnel() {
  load_env
  stop_tunnel
  if [ "$ENABLE_QUICK_TUNNEL" != "true" ]; then
    log "Remote quick tunnel disabled"
    rm -f "$TUNNEL_URL_FILE"
    return
  fi
  ensure_cloudflared
  : > "$TUNNEL_LOG"
  log "Starting Cloudflare quick tunnel"
  nohup "$CLOUDFLARED_BIN" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >>"$TUNNEL_LOG" 2>&1 &
  echo $! > "$TUNNEL_PID_FILE"
  wait_for_tunnel
}

write_status() {
  load_env
  python3 - "$STATUS_FILE" "$PORT" "$SERVER_PID_FILE" "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$PUBLIC_BASE_URL" "$PUBLIC_HOST" "$MODEL_NAME" <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

status_file = Path(sys.argv[1])
port = sys.argv[2]
server_pid_file = Path(sys.argv[3])
tunnel_pid_file = Path(sys.argv[4])
tunnel_url_file = Path(sys.argv[5])
public_base_url = sys.argv[6].strip()
public_host = sys.argv[7].strip()
model_name = sys.argv[8].strip()


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


tunnel_url = read_text(tunnel_url_file)
reachable_base_url = public_base_url or tunnel_url
if not reachable_base_url and public_host:
    reachable_base_url = f"http://{public_host}:{port}"
elif not reachable_base_url:
    reachable_base_url = f"http://127.0.0.1:{port}"

health_url = f"http://127.0.0.1:{port}/health"
health = fetch_json(health_url)
ready = bool(health.get("status") == "ok")

payload = {
    "status": "ready" if ready else "starting",
    "model": model_name,
    "enable_vlm": os.getenv("ENABLE_VLM", "true").strip().lower() in {"1", "true", "yes", "on"},
    "local_health_url": health_url,
    "local_analyze_url": f"http://127.0.0.1:{port}/analyze",
    "reachable_base_url": reachable_base_url.rstrip("/"),
    "analyze_url": f"{reachable_base_url.rstrip('/')}/analyze",
    "tunnel_url": tunnel_url,
    "public_base_url": public_base_url,
    "public_host": public_host,
    "server_pid": read_pid(server_pid_file),
    "tunnel_pid": read_pid(tunnel_pid_file),
    "health": health,
}

status_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=True))
PY
}

bootstrap() {
  install_deps
  prefetch_models
  start_server
  start_tunnel
  write_status >/dev/null
  log "Bootstrap completed"
}

status_cmd() {
  write_status
}

case "${1:-bootstrap}" in
  bootstrap)
    bootstrap
    ;;
  install)
    install_deps
    ;;
  prefetch)
    prefetch_models
    ;;
  start)
    start_server
    ;;
  tunnel)
    start_tunnel
    ;;
  stop)
    stop_tunnel
    stop_server
    ;;
  status)
    status_cmd
    ;;
  *)
    echo "Usage: $0 {bootstrap|install|prefetch|start|tunnel|stop|status}" >&2
    exit 1
    ;;
esac
