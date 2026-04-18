#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/opt/skylink-model-server}"
APP_DIR="${APP_DIR:-$ROOT_DIR/model_server}"
DEPLOY_DIR="${DEPLOY_DIR:-$ROOT_DIR/deploy/model_server}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/venv}"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/runtime}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
BIN_DIR="${BIN_DIR:-$ROOT_DIR/bin}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$BIN_DIR/cloudflared}"
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-$DEPLOY_DIR/docker-compose.vm.yml}"
DOCKER_BUILD_CONTEXT="${DOCKER_BUILD_CONTEXT:-$DEPLOY_DIR/docker-context}"
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

  export ROOT_DIR APP_DIR DEPLOY_DIR VENV_DIR RUNTIME_DIR ENV_FILE BIN_DIR CLOUDFLARED_BIN
  export DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-$DEPLOY_DIR/docker-compose.vm.yml}"
  export DOCKER_BUILD_CONTEXT="${DOCKER_BUILD_CONTEXT:-$DEPLOY_DIR/docker-context}"
  export API_KEY="${API_KEY:-road-inspector-secret-key-2024}"
  export HOST="${HOST:-0.0.0.0}"
  export PORT="${PORT:-17612}"
  export ENABLE_VLM="${ENABLE_VLM:-true}"
  export VLM_BACKEND="${VLM_BACKEND:-local}"
  if [ -z "${INSTALL_LOCAL_VLM:-}" ]; then
    if [ "$ENABLE_VLM" = "true" ] && [ "$VLM_BACKEND" = "local" ]; then
      export INSTALL_LOCAL_VLM="true"
    else
      export INSTALL_LOCAL_VLM="false"
    fi
  else
    export INSTALL_LOCAL_VLM="${INSTALL_LOCAL_VLM}"
  fi
  export REMOTE_DEPLOY_MODE="${REMOTE_DEPLOY_MODE:-native}"
  export DOCKER_IMAGE_NAME="${DOCKER_IMAGE_NAME:-skylink-model-server:latest}"
  export DOCKER_CONTAINER_NAME="${DOCKER_CONTAINER_NAME:-skylink-model-server}"
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
  export ENSEMBLE_MEMBERS="${ENSEMBLE_MEMBERS:-rezzzq_yolo12s_rdd2022,ozair_yolov8_rdd2022,oracl4_yolov8_rdd2022}"
  export YOLO12_REPO_DIR="${YOLO12_REPO_DIR:-$ROOT_DIR/external/yolov12}"
  export YOLO12_REPO_URL="${YOLO12_REPO_URL:-https://github.com/sunsmarterjie/yolov12.git}"
  export YOLO12_REPO_REF="${YOLO12_REPO_REF:-}"
  export ENABLE_QUICK_TUNNEL="${ENABLE_QUICK_TUNNEL:-true}"
  export WAIT_FOR_HEALTH="${WAIT_FOR_HEALTH:-true}"
  export WAIT_FOR_TUNNEL="${WAIT_FOR_TUNNEL:-true}"
  export PREFETCH_MODELS="${PREFETCH_MODELS:-true}"
  export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
  export PUBLIC_HOST="${PUBLIC_HOST:-}"
  export PROMPT_FILE="${PROMPT_FILE:-$APP_DIR/prompt.txt}"
}

yolo12_member_enabled() {
  case ",${ENSEMBLE_MEMBERS}," in
    *,rezzzq_yolo12s_rdd2022,*) return 0 ;;
    *) return 1 ;;
  esac
}

ensure_base_packages() {
  local need_install="false"
  if ! command -v python3 >/dev/null 2>&1; then
    need_install="true"
  elif ! python3 -m venv --help >/dev/null 2>&1; then
    need_install="true"
  fi
  for binary in curl wget git lsof; do
    if ! command -v "$binary" >/dev/null 2>&1; then
      need_install="true"
      break
    fi
  done

  if [ "$need_install" = "false" ]; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    log "Installing base OS packages"
    apt-get update
    apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv git curl wget ca-certificates \
      ffmpeg libsm6 libxext6 libglib2.0-0 lsof
    rm -rf /var/lib/apt/lists/*
    return
  fi

  log "Missing required host packages and cannot install them automatically"
  return 1
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; then
      return
    fi
  fi

  if ! command -v apt-get >/dev/null 2>&1 || [ "$(id -u)" -ne 0 ]; then
    log "Docker/Compose is required for docker_vm mode and could not be installed automatically"
    return 1
  fi

  log "Installing Docker and Compose support"
  apt-get update
  if ! apt-get install -y --no-install-recommends docker.io docker-compose-plugin; then
    apt-get install -y --no-install-recommends docker.io docker-compose
  fi
  rm -rf /var/lib/apt/lists/*

  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now docker >/dev/null 2>&1 || systemctl start docker >/dev/null 2>&1 || true
  fi
  if command -v service >/dev/null 2>&1; then
    service docker start >/dev/null 2>&1 || true
  fi

  if ! command -v docker >/dev/null 2>&1; then
    log "Docker install completed but docker binary is still unavailable"
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    log "Docker Compose is still unavailable after installation"
    return 1
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    (
      cd "$DEPLOY_DIR"
      docker compose -f "$DOCKER_COMPOSE_FILE" "$@"
    )
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    (
      cd "$DEPLOY_DIR"
      docker-compose -f "$DOCKER_COMPOSE_FILE" "$@"
    )
    return
  fi
  log "Docker Compose command not found"
  return 1
}

ensure_docker_assets() {
  if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
    log "Missing Docker Compose file at $DOCKER_COMPOSE_FILE"
    return 1
  fi
  if [ ! -f "$DEPLOY_DIR/Dockerfile" ]; then
    log "Missing Dockerfile at $DEPLOY_DIR/Dockerfile"
    return 1
  fi
  if [ ! -d "$APP_DIR" ]; then
    log "Missing model_server source at $APP_DIR"
    return 1
  fi
}

prepare_docker_context() {
  load_env
  ensure_docker_assets
  mkdir -p "$DOCKER_BUILD_CONTEXT/model_server"
  rm -rf "$DOCKER_BUILD_CONTEXT/model_server"
  mkdir -p "$DOCKER_BUILD_CONTEXT/model_server"
  rm -rf "$DOCKER_BUILD_CONTEXT/external"
  mkdir -p "$DOCKER_BUILD_CONTEXT/external"
  tar \
    --exclude='models' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    -C "$APP_DIR" \
    -cf - . | tar -C "$DOCKER_BUILD_CONTEXT/model_server" -xf -
  if [ -d "$ROOT_DIR/external/yolov12" ]; then
    tar -C "$ROOT_DIR/external" -cf - yolov12 | tar -C "$DOCKER_BUILD_CONTEXT/external" -xf -
  fi
  cp "$DEPLOY_DIR/patch_yolo12_flash_fallback.py" "$DOCKER_BUILD_CONTEXT/patch_yolo12_flash_fallback.py"
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

install_deps_native() {
  ensure_base_packages
  ensure_venv
  local requirements_file="$APP_DIR/requirements.txt"
  if [ "$INSTALL_LOCAL_VLM" != "true" ]; then
    requirements_file="$APP_DIR/requirements-yolo.txt"
  fi
  log "Installing Python dependencies from $requirements_file"
  python -m pip install -r "$requirements_file"
  if yolo12_member_enabled; then
    local repo_dir="$YOLO12_REPO_DIR"
    mkdir -p "$(dirname "$repo_dir")"
    if [ ! -d "$repo_dir" ] || [ ! -f "$repo_dir/ultralytics/nn/modules/block.py" ]; then
      if [ -z "$YOLO12_REPO_URL" ]; then
        log "YOLO12 fork is required for the rezzzq member but no bundled repo or YOLO12_REPO_URL was provided."
        return 1
      fi
      log "Cloning YOLO12 fork from $YOLO12_REPO_URL"
      rm -rf "$repo_dir"
      git clone "$YOLO12_REPO_URL" "$repo_dir"
    fi
    if [ -n "$YOLO12_REPO_REF" ] && [ -d "$repo_dir/.git" ]; then
      log "Checking out YOLO12 ref $YOLO12_REPO_REF"
      git -C "$repo_dir" fetch --all --tags || true
      git -C "$repo_dir" checkout "$YOLO12_REPO_REF"
    fi
    if [ -f "$repo_dir/requirements.txt" ]; then
      sed -i 's|.*flash_attn.*\.whl.*|# removed local wheel - using runtime patch instead|' "$repo_dir/requirements.txt" || true
    fi
    python "$DEPLOY_DIR/patch_yolo12_flash_fallback.py" "$repo_dir"
    log "Installing YOLO12 fork from $repo_dir"
    python -m pip install -e "$repo_dir"
  fi
}

install_deps_docker() {
  ensure_base_packages
  ensure_docker
  ensure_docker_assets
}

install_deps() {
  load_env
  if [ "$REMOTE_DEPLOY_MODE" = "docker_vm" ]; then
    install_deps_docker
  else
    install_deps_native
  fi
}

prefetch_models_native() {
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
  if [ "$INSTALL_LOCAL_VLM" != "true" ]; then
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

prefetch_models_docker() {
  ensure_docker
  prepare_docker_context
  mkdir -p "$HF_HOME" "$(dirname "$YOLO_MODEL_V8")"
  log "Building Docker image for remote model server"
  compose build model-server
  if [ "$PREFETCH_MODELS" != "true" ]; then
    log "Skipping model prefetch"
    return
  fi
  log "Prefetching model assets in Docker"
  cmd=(python /opt/skylink-model-server/model_server/prefetch_models.py \
    --vlm-model "$VLM_MODEL" \
    --yolo-v12-repo "$YOLO_MODEL_V12" \
    --yolo-v8-url "$YOLO_V8_WEIGHTS_URL" \
    --yolo-v8-dest "$YOLO_MODEL_V8" \
    --cache-dir "$HF_HOME")
  if [ "$INSTALL_LOCAL_VLM" != "true" ]; then
    cmd+=(--skip-vlm)
  fi
  if [ "$ENABLE_YOLO_V8" != "true" ]; then
    cmd+=(--skip-yolo-v8)
  fi
  if [ -n "${HUGGINGFACE_HUB_TOKEN:-}" ]; then
    cmd+=(--hf-token "$HUGGINGFACE_HUB_TOKEN")
  fi
  compose run --rm --no-deps model-server "${cmd[@]}"
}

prefetch_models() {
  load_env
  if [ "$REMOTE_DEPLOY_MODE" = "docker_vm" ]; then
    prefetch_models_docker
  else
    prefetch_models_native
  fi
}

stop_server_native() {
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

sync_docker_server_state() {
  if docker container inspect "$DOCKER_CONTAINER_NAME" >/dev/null 2>&1; then
    local pid
    pid="$(docker inspect -f '{{.State.Pid}}' "$DOCKER_CONTAINER_NAME" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && [ "$pid" -gt 0 ]; then
      printf '%s\n' "$pid" > "$SERVER_PID_FILE"
    else
      rm -f "$SERVER_PID_FILE"
    fi
    docker logs --tail 200 "$DOCKER_CONTAINER_NAME" >"$SERVER_LOG" 2>&1 || true
  else
    rm -f "$SERVER_PID_FILE"
  fi
}

stop_server_docker() {
  ensure_docker
  ensure_docker_assets
  if compose ps -q model-server >/dev/null 2>&1; then
    log "Stopping Docker Compose model server"
    compose down --remove-orphans || true
  fi
  rm -f "$SERVER_PID_FILE"
}

stop_server() {
  load_env
  if [ "$REMOTE_DEPLOY_MODE" = "docker_vm" ]; then
    stop_server_docker
  else
    stop_server_native
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

start_server_native() {
  ensure_venv
  stop_server_native
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

start_server_docker() {
  ensure_docker
  ensure_docker_assets
  prepare_docker_context
  mkdir -p "$HF_HOME" "$(dirname "$YOLO_MODEL_V8")"
  stop_server_docker
  : > "$SERVER_LOG"
  log "Starting Docker Compose model server"
  compose up -d --build model-server
  sync_docker_server_state
  wait_for_health
  sync_docker_server_state
}

start_server() {
  load_env
  if [ "$REMOTE_DEPLOY_MODE" = "docker_vm" ]; then
    start_server_docker
  else
    start_server_native
  fi
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
  if [ "$REMOTE_DEPLOY_MODE" = "docker_vm" ]; then
    sync_docker_server_state
  fi
  python3 - "$STATUS_FILE" "$PORT" "$SERVER_PID_FILE" "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$PUBLIC_BASE_URL" "$PUBLIC_HOST" "$MODEL_NAME" "$REMOTE_DEPLOY_MODE" "$DOCKER_CONTAINER_NAME" "$DOCKER_IMAGE_NAME" <<'PY'
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
deployment_mode = sys.argv[9].strip()
docker_container = sys.argv[10].strip()
docker_image = sys.argv[11].strip()


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
    "deployment_mode": deployment_mode,
    "docker_container": docker_container if deployment_mode == "docker_vm" else "",
    "docker_image": docker_image if deployment_mode == "docker_vm" else "",
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
