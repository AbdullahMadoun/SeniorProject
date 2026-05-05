from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

try:
    from analyze_video_pipeline import (
        analyze_video_session,
        create_mission_record,
        finalize_mission_record,
        init_supabase,
        persist_image_analysis,
    )
    VIDEO_PIPELINE_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    analyze_video_session = None
    create_mission_record = None
    finalize_mission_record = None
    init_supabase = None
    persist_image_analysis = None
    VIDEO_PIPELINE_IMPORT_ERROR = str(exc)

from managed_remote_model import ManagedRemoteModelState
from remote_model_helpers import resolve_frontend_connection


ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT_DIR / ".env")

HISTORY_FILE = Path(os.getenv("SKYLINK_HISTORY_FILE", STATIC_DIR / "history.json"))
HISTORY_IMAGES_DIR = Path(os.getenv("SKYLINK_HISTORY_IMAGES_DIR", STATIC_DIR / "history_images"))
PROCESSED_HISTORY_DIR = Path(
    os.getenv("SKYLINK_PROCESSED_HISTORY_DIR", ROOT_DIR / "data" / "h")
)
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
HISTORY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

if not HISTORY_FILE.exists():
    HISTORY_FILE.write_text("[]", encoding="utf-8")

def _safe_win_path(path: Path | str) -> str:
    r"""Add \\?\ prefix to absolute Windows paths to bypass 260-char limit."""
    p = str(Path(path).resolve())
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p

# Search for cloudflared in path, then bin/, then .env path
# Simplified tunnel binary discovery
def _resolve_cloudflared_bin(env_bin: str) -> str:
    # Use SKYLINK_CLOUDFLARED_BIN if fixed in .env, otherwise check bin/ then fallback to 'cloudflared'
    if env_bin and os.path.isabs(env_bin) and Path(env_bin).exists():
        return env_bin
    local_bin = ROOT_DIR / "bin" / "cloudflared.exe"
    if local_bin.exists():
        return str(local_bin.resolve())
    return "cloudflared"

STATIC_VLM_API_URL = os.getenv("SKYLINK_VLM_API_URL", "")
STATIC_VLM_API_KEY = os.getenv("SKYLINK_VLM_API_KEY", "")
BRIDGE_PORT = int(os.getenv("SKYLINK_BRIDGE_PORT", "8002"))
PUBLIC_BASE_URL = os.getenv("SKYLINK_PUBLIC_BASE_URL", "").strip()
USE_BRIDGE_PROXY = os.getenv("SKYLINK_USE_BRIDGE_PROXY", "true").strip().lower() in {"1", "true", "yes", "on"}
FRONTEND_DIRECT_MODEL = os.getenv("SKYLINK_FRONTEND_DIRECT_MODEL", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENABLE_QUICK_TUNNEL = os.getenv("SKYLINK_ENABLE_QUICK_TUNNEL", "true").strip().lower() in {"1", "true", "yes", "on"}
EXPOSE_VLM_API_KEY_TO_FRONTEND = os.getenv("SKYLINK_EXPOSE_VLM_API_KEY_TO_FRONTEND", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_VLM_MODE = os.getenv("SKYLINK_DEFAULT_VLM_MODE", "local").strip().lower() or "local"
STATIC_VLM_API_MODEL_OPTIONS = [
    item.strip()
    for item in str(
        os.getenv(
            "SKYLINK_VLM_API_MODEL_OPTIONS",
            "google/gemini-3.1-pro-preview,google/gemini-2.5-pro,x-ai/grok-4.20,moonshotai/kimi-k2-thinking,qwen/qwen2.5-vl-72b-instruct,openai/gpt-4o",
        )
    ).split(",")
    if item.strip()
]
CLOUDFLARED_BIN = _resolve_cloudflared_bin(os.getenv("SKYLINK_CLOUDFLARED_BIN", "cloudflared").strip())
CLOUDFLARED_CONFIG_FILE = os.getenv("SKYLINK_CLOUDFLARED_CONFIG_FILE", "").strip()
TUNNEL_INFO_FILE = Path(os.getenv("SKYLINK_TUNNEL_INFO_FILE", HISTORY_FILE.parent / "tunnel_info.json"))
TUNNEL_LOG_FILE = Path(os.getenv("SKYLINK_TUNNEL_LOG_FILE", HISTORY_FILE.parent / "cloudflared.log"))
REMOTE_MODEL_INFO_FILE = Path(
    os.getenv("SKYLINK_REMOTE_MODEL_INFO_FILE", HISTORY_FILE.parent / "remote_model_info.json")
)
REMOTE_MODEL_LOG_FILE = Path(
    os.getenv("SKYLINK_REMOTE_MODEL_LOG_FILE", HISTORY_FILE.parent / "remote_model.log")
)
REMOTE_MODEL_INSTANCE_FILE = Path(
    os.getenv("SKYLINK_REMOTE_MODEL_INSTANCE_FILE", HISTORY_FILE.parent / "remote_model_instance_id.txt")
)
TUNNEL_URL_PATTERN = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com", re.IGNORECASE)
TUNNEL_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
TUNNEL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
REMOTE_MODEL_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
REMOTE_MODEL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

BRIDGE_VLM_API_URL = os.getenv("VLM_API_URL", "").strip()
BRIDGE_VLM_API_KEY = os.getenv("VLM_API_KEY", "").strip()
BRIDGE_VLM_API_AUTH_SCHEME = os.getenv("VLM_API_AUTH_SCHEME", "bearer").strip() or "bearer"
BRIDGE_VLM_API_TYPE = os.getenv("VLM_API_TYPE", "openai").strip() or "openai"
BRIDGE_VLM_MODEL = os.getenv("VLM_MODEL", "qwen/qwen2.5-vl-72b-instruct").strip() or "qwen/qwen2.5-vl-72b-instruct"
BRIDGE_VLM_TIMEOUT = float(os.getenv("VLM_API_TIMEOUT", "180") or "180")
BRIDGE_VLM_PROMPT_FILE = ROOT_DIR / "model_server" / "prompt.txt"
BRIDGE_VLM_SYSTEM_PROMPT = (
    "You are an expert Autonomous Road Safety Verification Agent. "
    "Your role is to verify pavement distress detections (cracks, potholes) with extreme detail. "
    "You must prioritize depth and structural failure over surface area. "
    "You MUST output ONLY strictly valid JSON as specified in the instructions. "
    "Do not include any conversational text, code blocks, or preamble."
)


def _load_bridge_vlm_prompt() -> str:
    try:
        if BRIDGE_VLM_PROMPT_FILE.exists():
            return BRIDGE_VLM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return (
        "You are an Autonomous Road Safety Verification Agent. "
        "Return only valid JSON with report_markdown and severities."
    )


BRIDGE_VLM_USER_PROMPT_TEMPLATE = _load_bridge_vlm_prompt()


@dataclass
class TunnelState:
    process: subprocess.Popen[str] | None = None
    public_url: str = ""
    status: str = "disabled"
    error: str = ""
    output_tail: list[str] = field(default_factory=list)
    started_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _append_output(self, line: str) -> None:
        clean = line.rstrip()
        if not clean:
            return
        with self.lock:
            self.output_tail.append(clean)
            if len(self.output_tail) > 80:
                self.output_tail = self.output_tail[-80:]
        with TUNNEL_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(clean + "\n")

        match = TUNNEL_URL_PATTERN.search(clean)
        if match:
            with self.lock:
                self.public_url = match.group(0)
                self.status = "ready"
                self.error = ""
            self._write_info()

    def _write_info(self) -> None:
        payload = {
            "status": self.status,
            "public_url": self.public_url,
            "error": self.error,
            "started_at": self.started_at,
            "output_tail": self.output_tail[-20:],
        }
        TUNNEL_INFO_FILE.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def start(self, port: int) -> None:
        if PUBLIC_BASE_URL:
            with self.lock:
                self.public_url = PUBLIC_BASE_URL
                self.status = "configured"
                self.error = ""
                self.started_at = time.time()
            self._write_info()
            return

        if not ENABLE_QUICK_TUNNEL:
            with self.lock:
                self.status = "disabled"
                self.error = "Quick tunnel disabled by configuration."
                self.started_at = time.time()
            self._write_info()
            return

        with self.lock:
            self.status = "starting"
            self.error = ""
            self.started_at = time.time()
            self.public_url = ""
            self.output_tail = []
        TUNNEL_LOG_FILE.write_text("", encoding="utf-8")
        self._write_info()

        command = [CLOUDFLARED_BIN]
        if CLOUDFLARED_CONFIG_FILE:
            command.extend(["--config", CLOUDFLARED_CONFIG_FILE])
        command.extend(
            [
                "tunnel",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{port}",
            ]
        )
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            with self.lock:
                self.status = "failed"
                self.error = f"Failed to start cloudflared: {exc}"
            self._write_info()
            return

        self.process = process

        def _reader() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                self._append_output(line)
            exit_code = process.wait()
            with self.lock:
                if self.status != "ready":
                    self.status = "failed"
                    if not self.error:
                        self.error = f"cloudflared exited before publishing a URL (exit code {exit_code})."
                elif exit_code != 0:
                    self.status = "failed"
                    self.error = f"cloudflared exited unexpectedly (exit code {exit_code})."
            self._write_info()

        threading.Thread(target=_reader, name="skylink-cloudflared-reader", daemon=True).start()

    def stop(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        finally:
            self.process = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "public_url": self.public_url,
                "error": self.error,
                "started_at": self.started_at,
                "output_tail": list(self.output_tail[-10:]),
            }


tunnel_state = TunnelState()
remote_model_state = ManagedRemoteModelState(
    bundle_root=ROOT_DIR,
    state_file=REMOTE_MODEL_INFO_FILE,
    log_file=REMOTE_MODEL_LOG_FILE,
    instance_file=REMOTE_MODEL_INSTANCE_FILE,
)


def _request_base_url(request: Request | None) -> str:
    if request is None:
        return ""
    return str(request.base_url).rstrip("/")


def _masked_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(0, len(value) - 8)}{value[-4:]}"


def _video_pipeline_available() -> bool:
    return analyze_video_session is not None and init_supabase is not None


def _supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")))


def _resolved_model_target() -> tuple[str, str, str, dict[str, Any]]:
    remote_snapshot = remote_model_state.snapshot()
    remote_url = ""
    remote_key = ""
    if remote_snapshot.get("status") == "ready":
        remote_url = str(remote_snapshot.get("analyze_url") or "").strip()
        remote_key = remote_model_state.api_key_value()

    if STATIC_VLM_API_URL:
        return STATIC_VLM_API_URL, STATIC_VLM_API_KEY, "static-env", remote_snapshot
    if remote_url:
        return remote_url, remote_key, "managed-remote", remote_snapshot
    return "", "", "unconfigured", remote_snapshot


def _runtime_config(request: Request | None = None) -> dict[str, Any]:
    # removed blocking start() call here to fix slow UI load
    request_base = _request_base_url(request)
    tunnel = tunnel_state.snapshot()

    public_bridge_url = PUBLIC_BASE_URL or tunnel["public_url"]
    bridge_base_url = request_base or public_bridge_url
    model_api_url, model_api_key, model_source, remote_snapshot = _resolved_model_target()
    autostart_enabled = os.getenv("SKYLINK_REMOTE_MODEL_AUTOSTART", "false").strip().lower() in {"1", "true", "yes", "on"}
    frontend_connection = resolve_frontend_connection(
        bridge_base_url=bridge_base_url,
        model_api_url=model_api_url,
        model_api_key=model_api_key,
        frontend_direct_model=FRONTEND_DIRECT_MODEL,
        expose_model_key=EXPOSE_VLM_API_KEY_TO_FRONTEND,
        bridge_proxy_enabled=USE_BRIDGE_PROXY,
    )
    remote_status = remote_snapshot.get("status") or ("ready" if model_api_url else "disabled")
    remote_error = remote_snapshot.get("error") or ""
    show_remote_details = bool(autostart_enabled or model_source == "managed-remote")
    if remote_snapshot.get("public_base_url"):
        model_public_url = str(remote_snapshot.get("public_base_url"))
    elif model_api_url.endswith("/analyze"):
        model_public_url = model_api_url.rsplit("/analyze", 1)[0]
    else:
        model_public_url = model_api_url

    return {
        **frontend_connection,
        "BRIDGE_BASE_URL": bridge_base_url,
        "PUBLIC_BRIDGE_URL": public_bridge_url,
        "QUICK_TUNNEL_ENABLED": ENABLE_QUICK_TUNNEL or bool(PUBLIC_BASE_URL),
        "TUNNEL_STATUS": tunnel["status"],
        "TUNNEL_ERROR": tunnel["error"],
        "TUNNEL_OUTPUT_TAIL": tunnel["output_tail"],
        "ACTIVE_MODEL_API_URL": model_api_url,
        "SERVER_SIDE_MODEL_KEY_MASKED": _masked_key(model_api_key),
        "MODEL_SERVER_SOURCE": model_source,
        "MODEL_SERVER_STATUS": remote_status if model_source == "managed-remote" else ("ready" if model_api_url else remote_status),
        "MODEL_SERVER_ERROR": remote_error,
        "MODEL_SERVER_PROVIDER": (remote_snapshot.get("provider") or os.getenv("SKYLINK_REMOTE_MODEL_PROVIDER", "ssh")) if show_remote_details else "",
        "MODEL_SERVER_PUBLIC_URL": model_public_url,
        "MODEL_SERVER_REMOTE_HOST": (remote_snapshot.get("remote_host") or os.getenv("SKYLINK_REMOTE_MODEL_SSH_HOST", "")) if show_remote_details else "",
        "MODEL_SERVER_REMOTE_PORT": (remote_snapshot.get("remote_port") or int(os.getenv("SKYLINK_REMOTE_MODEL_SSH_PORT", "22"))) if show_remote_details else 22,
        "MODEL_SERVER_INSTANCE_ID": (remote_snapshot.get("instance_id") or os.getenv("SKYLINK_VAST_INSTANCE_ID", "")) if show_remote_details else "",
        "MODEL_SERVER_AUTOSTART": autostart_enabled,
        "MODEL_SERVER_OUTPUT_TAIL": (remote_snapshot.get("output_tail") or []) if show_remote_details else [],
        "DEFAULT_VLM_MODE": DEFAULT_VLM_MODE,
        "VLM_MODE_OPTIONS": ["local", "api", "disabled"],
        "VLM_API_MODEL_OPTIONS": STATIC_VLM_API_MODEL_OPTIONS,
        "VIDEO_ANALYSIS_ENABLED": _video_pipeline_available(),
        "VIDEO_ANALYSIS_ERROR": VIDEO_PIPELINE_IMPORT_ERROR,
        "SUPABASE_CONFIGURED": _supabase_configured(),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    tunnel_state.start(BRIDGE_PORT)
    remote_model_state.start()
    yield
    tunnel_state.stop()


app = FastAPI(title="SkyLink Bridge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_long_urls(request: Request, call_next):
    """Prevent 'stat: path too long' crashes by rejecting insane URL paths early."""
    if len(request.url.path) > 200:
        return JSONResponse(
            status_code=400,
            content={"detail": "URL path exceeds safe length limit (200 chars)"},
        )
    return await call_next(request)


def _read_history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_history(history: list[dict]) -> None:
    HISTORY_FILE.write_text(json.dumps(history[-50:]), encoding="utf-8")


def _split_data_uri(value: str) -> Tuple[str, str]:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("Invalid data URI payload.")
    if "," not in cleaned:
        return "data:image/jpeg;base64", cleaned
    header, body = cleaned.split(",", 1)
    if not body.strip():
        raise ValueError("Invalid data URI payload.")
    return header, body


def _extension_from_header(header: str, default_ext: str = "jpg") -> str:
    lowered = header.lower()
    if "png" in lowered:
        return "png"
    if "webp" in lowered:
        return "webp"
    if "jpeg" in lowered or "jpg" in lowered:
        return "jpg"
    return default_ext


def _decode_image_to_file(encoded: str, out_dir: Path, prefix: str = "image") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    header = "data:image/jpeg;base64"
    body = encoded.strip()
    if encoded.startswith("data:image"):
        header, body = _split_data_uri(encoded)

    ext = _extension_from_header(header)
    file_path = out_dir / f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    file_path.write_bytes(base64.b64decode(body, validate=True))
    return file_path


def _normalize_severity(value: str) -> str:
    lowered = (value or "").strip().lower()
    if lowered in {"high", "high severity", "critical"}:
        return "High Severity"
    if lowered in {"medium", "moderate"}:
        return "Moderate"
    return "Low Severity"


def _max_confidence_from_boxes(boxes: list[dict], default_value: float = 0.85) -> float:
    confidences = []
    for box in boxes:
        raw = box.get("confidence")
        if raw is None:
            raw = box.get("score")
        try:
            if raw is not None:
                confidences.append(float(raw))
        except (TypeError, ValueError):
            continue
    return max(confidences) if confidences else default_value


def _extract_location(payload: Dict[str, Any]) -> Tuple[Any, Any]:
    location = payload.get("location")
    if isinstance(location, dict):
        return location.get("lat"), location.get("lon")
    if isinstance(location, list) and len(location) >= 2:
        return location[0], location[1]
    return None, None


def _bridge_image_name(raw_name: Any, saved_name: str) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return f"bridge_{saved_name}"
    lowered = name.lower()
    if lowered.startswith("bridge_") or lowered.startswith("standalone_"):
        return name
    return f"bridge_{name}"


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _safe_stem(name: str, fallback: str = "artifact") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem or fallback).strip("._")
    return stem or fallback


def _processed_url(path: Path) -> str:
    # Use direct prefix /h/ for the shortened data/h directory
    try:
        relative = path.resolve().relative_to(PROCESSED_HISTORY_DIR.resolve())
        return f"/h/{relative.as_posix()}"
    except (ValueError, AttributeError):
        return ""


def _build_auth_headers(api_key: str, auth_scheme: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SkyLink-Drone/SkyLink",
        "X-Title": "SkyLink Autonomous Inspection",
    }
    if not api_key:
        return headers
    scheme = auth_scheme.strip().lower()
    if scheme == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif scheme == "x-api-key":
        headers["X-API-Key"] = api_key
    else:
        headers["Authorization"] = api_key
    return headers


def _bridge_vlm_available() -> bool:
    return bool(BRIDGE_VLM_API_URL and BRIDGE_VLM_API_KEY)


def _coerce_float(raw: Any) -> float | None:
    try:
        if raw is None or str(raw).strip() == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _location_or_default(payload: Dict[str, Any]) -> Tuple[float, float]:
    lat, lon = _extract_location(payload)
    lat_num = _coerce_float(lat)
    lon_num = _coerce_float(lon)
    return lat_num if lat_num is not None else 26.305, lon_num if lon_num is not None else 50.146


def _analysis_summary_from_report(report: Dict[str, Any]) -> str:
    summary = str(report.get("summary", "")).strip()
    if summary:
        return summary
    boxes = list(report.get("boxes", []))
    if not boxes:
        return "No visible damage detected."
    return f"{len(boxes)} defect(s) detected."


def _record_severity(boxes: list[dict]) -> str:
    severities = [str(box.get("severity", "")).strip().lower() for box in boxes]
    if any(level in {"high", "critical", "high severity", "severe"} for level in severities):
        return "High"
    if any(level in {"medium", "moderate"} for level in severities):
        return "Medium"
    if boxes:
        return "Minor"
    return "Minor"


def _bridge_prompt_from_boxes(
    boxes: list[dict[str, Any]],
    *,
    width: int | None,
    height: int | None,
    lat: float | None,
    lon: float | None,
) -> str:
    lines: list[str] = []
    for box in boxes:
        bbox = list(box.get("bbox_xyxy") or [0, 0, 0, 0])
        if len(bbox) != 4:
            bbox = [0, 0, 0, 0]
        x1, y1, x2, y2 = [int(float(value)) for value in bbox]
        w_px = max(1, x2 - x1)
        h_px = max(1, y2 - y1)
        area = w_px * h_px
        confidence = float(box.get("confidence", box.get("score", 0.0)) or 0.0) * 100.0
        support = int(box.get("support", 1) or 1)
        label = str(box.get("label") or box.get("class") or "Damage")
        box_id = str(box.get("id") or f"D{len(lines)}")
        lines.append(
            f"- ID: {box_id}, Type: {label}, Ensemble Confidence: {confidence:.1f}%, "
            f"Support: {support} model(s), Dimensions: {w_px}x{h_px} pixels "
            f"(Area: {area}), Coords: [x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}]"
        )

    gps_str = f"GPS location (lat, lon): {lat}, {lon}." if lat is not None and lon is not None else "GPS location: Not provided."
    width = int(width or 0)
    height = int(height or 0)
    box_str = "\n".join(lines) if lines else "No defects detected by the ensemble detector."
    return (
        BRIDGE_VLM_USER_PROMPT_TEMPLATE
        + f"\n\n{gps_str}\nImage resolution: {width} x {height} pixels.\n\n"
        + "### DETECTED BOUNDING BOXES (From YOLO ensemble):\n"
        + box_str
    )


def _extract_json_from_text(text: str) -> dict[str, Any]:
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        first = text.find("{")
        last = text.rfind("}")
        json_str = text[first:last + 1].strip() if first != -1 and last > first else text.strip()
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
    return json.loads(json_str)


async def _run_bridge_api_vlm(
    *,
    image_payload: str,
    report: dict[str, Any],
    requested_model: str,
    lat: float | None,
    lon: float | None,
) -> tuple[dict[str, Any], str]:
    boxes = list(report.get("boxes", []))
    if not boxes:
        return {"report_markdown": report.get("report_markdown", ""), "severities": {}}, ""

    image_header, image_body = _split_data_uri(image_payload)
    image_mime = "image/jpeg"
    if image_header.startswith("data:") and ";base64" in image_header:
        image_mime = image_header[5:].split(";", 1)[0] or image_mime

    width = report.get("image_width") or report.get("width")
    height = report.get("image_height") or report.get("height")
    user_prompt = _bridge_prompt_from_boxes(boxes, width=width, height=height, lat=lat, lon=lon)
    model_name = str(requested_model or "").strip() or BRIDGE_VLM_MODEL

    if BRIDGE_VLM_API_TYPE == "openai" or "openrouter.ai" in BRIDGE_VLM_API_URL:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": BRIDGE_VLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_body}"}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"} if "qwen" not in model_name.lower() else None,
        }
    else:
        payload = {
            "image_b64": image_body,
            "system_prompt": BRIDGE_VLM_SYSTEM_PROMPT,
            "prompt": user_prompt,
            "detections": boxes,
            "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "response_format": "report_markdown_and_severities",
        }

    async with httpx.AsyncClient(timeout=BRIDGE_VLM_TIMEOUT) as client:
        response = await client.post(
            BRIDGE_VLM_API_URL,
            json=payload,
            headers=_build_auth_headers(BRIDGE_VLM_API_KEY, BRIDGE_VLM_API_AUTH_SCHEME),
        )
    if response.status_code >= 400:
        error_body = response.text
        # Log to bridge console for debugging
        print(f"[VLM_API_ERROR] Status {response.status_code} from {BRIDGE_VLM_API_URL}")
        print(f"[VLM_API_ERROR] Body: {error_body[:1000]}")

        # If the remote returned a 500, check if it's a known pipeline failure
        detail_msg = f"VLM API Error {response.status_code}"
        if response.status_code == 500:
            detail_msg = "Remote VLM Inference Pipeline Failed. This usually indicates a GPU crash or OOM on the model server."

        raise HTTPException(
            status_code=500,  # Always return 500 to frontend for API failures to trigger error states
            detail=f"{detail_msg}: {error_body}"
        )

    data = response.json()

    if isinstance(data, dict):
        if "report_markdown" in data or "severities" in data:
            return data, model_name
        report_payload = data.get("report")
        if isinstance(report_payload, dict) and ("report_markdown" in report_payload or "severities" in report_payload):
            return report_payload, model_name
        text = data.get("text") or data.get("output_text") or data.get("content")
        if isinstance(text, str):
            return _extract_json_from_text(text), model_name

    raise RuntimeError(f"Bridge VLM API returned unsupported payload shape: {json.dumps(data)[:500]}")


async def _apply_bridge_vlm_if_requested(
    *,
    report: dict[str, Any],
    source_image_payload: str,
    location_payload: dict[str, Any] | None,
    requested_mode: str,
    requested_model: str,
) -> dict[str, Any]:
    resolved_mode = str(report.get("detector_debug", {}).get("resolved_vlm_mode", "")).strip().lower()
    if requested_mode != "api":
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "not_requested"
        return report
    if resolved_mode == "api":
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "remote_api"
        return report
    if not _bridge_vlm_available():
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "bridge_api_unconfigured"
        return report
    if not list(report.get("boxes", [])):
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "skipped_no_boxes"
        return report

    lat, lon = _location_or_default(location_payload or {})
    api_result, model_name = await _run_bridge_api_vlm(
        image_payload=source_image_payload,
        report=report,
        requested_model=requested_model,
        lat=lat,
        lon=lon,
    )

    severities = {
        str(key): str(value).strip().lower()
        for key, value in dict(api_result.get("severities", {})).items()
        if str(key).strip()
    }
    for box in report.get("boxes", []):
        box_id = str(box.get("id", "")).strip()
        if box_id and box_id in severities:
            box["severity"] = severities[box_id]

    report["report_markdown"] = str(api_result.get("report_markdown", report.get("report_markdown", "")))
    report["summary"] = _analysis_summary_from_report(report)
    report.setdefault("detector_debug", {})
    report["detector_debug"]["resolved_vlm_mode"] = "api"
    report["detector_debug"]["resolved_vlm_model"] = model_name
    report["detector_debug"]["bridge_vlm_status"] = "bridge_api"
    return report


def _finding_from_analysis(
    *,
    report: Dict[str, Any],
    mission_name: str,
    mission_id: str = "",
    image_id: str = "",
    image_name: str = "",
    image_url: str = "",
    timestamp_utc: str = "",
    location_payload: Dict[str, Any] | None = None,
    source: str = "bridge",
    persisted_to_supabase: bool = False,
) -> dict[str, Any]:
    boxes = list(report.get("boxes", []))
    lat, lon = _location_or_default(location_payload or {})
    confidence = _max_confidence_from_boxes(boxes, 0.0)
    defect_types = sorted({str(box.get("label") or box.get("class") or "damage") for box in boxes})
    # Clean image logic: ensure Base64 is prefixed correctly
    final_image = image_url
    if image_url and not image_url.startswith("/") and not image_url.startswith("http") and not image_url.startswith("data:"):
        # If it looks like raw Base64 (no spaces, long), prefix it
        if " " not in image_url and len(image_url) > 100:
            final_image = f"data:image/jpeg;base64,{image_url}"

    return {
        "source": source,
        "mission_id": mission_id,
        "mission_name": mission_name or "SkyLink Mission",
        "image_id": image_id,
        "image_name": image_name,
        "timestamp": timestamp_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lat": lat,
        "lon": lon,
        "severity": _record_severity(boxes),
        "summary": _analysis_summary_from_report(report),
        "confidence": confidence,
        "image": final_image,
        "box_count": len(boxes),
        "defect_types": defect_types,
        "cluster_key": mission_id or mission_name or "standalone",
        "persisted_to_supabase": persisted_to_supabase,
    }


def _upsert_history_record(record: dict[str, Any]) -> None:
    history = _read_history()
    record_key = (
        str(record.get("mission_id") or ""),
        str(record.get("image_id") or ""),
        str(record.get("timestamp") or ""),
        str(record.get("image") or ""),
    )
    updated = False
    for index, existing in enumerate(history):
        existing_key = (
            str(existing.get("mission_id") or ""),
            str(existing.get("image_id") or ""),
            str(existing.get("timestamp") or ""),
            str(existing.get("image") or ""),
        )
        if existing_key == record_key:
            history[index] = {**existing, **record}
            updated = True
            break
    if not updated:
        history.append(record)
    _write_history(history)


def _fetch_supabase_findings(limit: int = 120) -> list[dict[str, Any]]:
    if not _supabase_configured() or init_supabase is None:
        return []

    supabase = init_supabase()
    if supabase is None:
        return []

    images_resp = supabase.table("mission_images").select(
        "id,mission_id,image_name,processed_image_path,processing_seconds,timestamp_utc"
    ).order("timestamp_utc", desc=True).limit(limit).execute()
    image_rows = list(images_resp.data or [])
    if not image_rows:
        return []

    mission_ids = sorted({str(row.get("mission_id")) for row in image_rows if row.get("mission_id")})
    missions_by_id: dict[str, dict[str, Any]] = {}
    if mission_ids:
        missions_resp = supabase.table("missions").select(
            "id,name,status,started_at,ended_at,description"
        ).in_("id", mission_ids).execute()
        missions_by_id = {
            str(row["id"]): row
            for row in (missions_resp.data or [])
            if row.get("id") is not None
        }

    image_ids = [str(row["id"]) for row in image_rows if row.get("id") is not None]
    detections_by_image: dict[str, list[dict[str, Any]]] = {}
    if image_ids:
        detections_resp = supabase.table("damage_detections").select(
            "image_id,severity,confidence,damage_type,bounding_box"
        ).in_("image_id", image_ids).execute()
        for detection in (detections_resp.data or []):
            image_id = str(detection.get("image_id") or "")
            detections_by_image.setdefault(image_id, []).append(detection)

    findings: list[dict[str, Any]] = []
    for row in image_rows:
        image_id = str(row.get("id") or "")
        mission_id = str(row.get("mission_id") or "")
        mission = missions_by_id.get(mission_id, {})
        detections = detections_by_image.get(image_id, [])
        boxes = [
            {
                "severity": detection.get("severity"),
                "confidence": detection.get("confidence"),
                "class": detection.get("damage_type"),
                "bbox_xyxy": detection.get("bounding_box"),
            }
            for detection in detections
        ]
        report = {
            "boxes": boxes,
            "summary": mission.get("description") if detections else "No persisted detections.",
        }
        findings.append(
            {
                **_finding_from_analysis(
                    report=report,
                    mission_name=str(mission.get("name") or "SkyLink Mission"),
                    mission_id=mission_id,
                    image_id=image_id,
                    image_name=str(row.get("image_name") or ""),
                    image_url=str(row.get("processed_image_path") or ""),
                    timestamp_utc=str(row.get("timestamp_utc") or ""),
                    source="supabase",
                    persisted_to_supabase=True,
                ),
                "mission_status": mission.get("status") or "",
                "mission_description": mission.get("description") or "",
                "processing_seconds": row.get("processing_seconds"),
            }
        )
    return findings


def _combined_findings() -> list[dict[str, Any]]:
    history = list(_read_history())
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in history:
        key = (
            str(record.get("mission_id") or ""),
            str(record.get("image_id") or ""),
            str(record.get("timestamp") or ""),
            str(record.get("image") or ""),
        )
        merged[key] = dict(record)

    for record in _fetch_supabase_findings():
        key = (
            str(record.get("mission_id") or ""),
            str(record.get("image_id") or ""),
            str(record.get("timestamp") or ""),
            str(record.get("image") or ""),
        )
        merged[key] = {**merged.get(key, {}), **record}

    counts_by_cluster: dict[str, int] = {}
    for record in merged.values():
        cluster_key = str(record.get("cluster_key") or "standalone")
        counts_by_cluster[cluster_key] = counts_by_cluster.get(cluster_key, 0) + 1

    findings = list(merged.values())
    for record in findings:
        cluster_key = str(record.get("cluster_key") or "standalone")
        record["cluster_size"] = counts_by_cluster.get(cluster_key, 1)

    findings.sort(key=lambda record: str(record.get("timestamp") or ""), reverse=True)
    return findings[:150]


async def _save_upload_file(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    await upload.close()


def _materialize_video_result(session_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    annotated_dir = session_dir / "annotated"
    frames_out: list[dict[str, Any]] = []
    total_boxes = 0
    frames_with_detections = 0
    max_confidence = 0.0

    for index, frame_record in enumerate(result.get("frames", [])):
        frame_path = Path(str(frame_record.get("frame_path", "")))
        report = frame_record.get("report") or {}
        boxes = list(report.get("boxes", []))
        total_boxes += len(boxes)
        if boxes:
            frames_with_detections += 1
            max_confidence = max(max_confidence, _max_confidence_from_boxes(boxes, 0.0))

        annotated_url = ""
        annotated_payload = str(report.get("annotated_image_b64", "")).strip()
        if annotated_payload:
            annotated_file = _decode_image_to_file(
                annotated_payload,
                annotated_dir,
                prefix=f"annotated_{index:04d}",
            )
            annotated_url = _processed_url(annotated_file)

        frame_url = _processed_url(frame_path) if frame_path.exists() else ""
        mission_id = str(frame_record.get("mission_id") or result.get("mission_id") or "")
        image_id = str(frame_record.get("image_id") or "")
        image_source = frame_record.get("public_url") or annotated_url or frame_url
        finding_record = _finding_from_analysis(
            report=report,
            mission_name=str(result.get("mission_name") or "SkyLink Video Mission"),
            mission_id=mission_id,
            image_id=image_id,
            image_name=frame_path.name or f"frame_{index:04d}",
            image_url=str(image_source or ""),
            timestamp_utc=str(frame_record.get("timestamp_utc") or ""),
            source="supabase" if image_id else "bridge",
            persisted_to_supabase=bool(image_id),
        )
        frames_out.append(
            {
                "frame_index": index,
                "frame_name": frame_path.name or f"frame_{index:04d}",
                "frame_url": frame_url,
                "annotated_url": annotated_url,
                "thumb_url": annotated_url or frame_url,
                "timestamp_utc": frame_record.get("timestamp_utc"),
                "processing_seconds": frame_record.get("processing_seconds"),
                "public_url": frame_record.get("public_url", ""),
                "summary": report.get("summary", ""),
                "boxes": boxes,
                "report_markdown": report.get("report_markdown", ""),
                "detector_debug": report.get("detector_debug", {}),
                "image_id": image_id,
                "mission_id": mission_id,
                "finding_record": finding_record,
                "error": frame_record.get("error", ""),
            }
        )

    payload = {
        "session_id": session_dir.name,
        "mission_id": result.get("mission_id"),
        "mission_name": result.get("mission_name"),
        "video_path": result.get("video_path"),
        "video_url": _processed_url(Path(result["video_path"])) if result.get("video_path") else "",
        "output_dir": result.get("output_dir"),
        "frame_count": int(result.get("frame_count") or 0),
        "processed_count": int(result.get("processed_count") or 0),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "frames_with_detections": frames_with_detections,
        "total_boxes": total_boxes,
        "max_confidence": max_confidence,
        "frames": frames_out,
    }
    (session_dir / "session_result.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


@app.get("/api/health")
async def health(request: Request) -> Dict[str, Any]:
    runtime = _runtime_config(request)
    return {
        "status": "ok",
        "bridge_port": BRIDGE_PORT,
        "public_bridge_url": runtime["PUBLIC_BRIDGE_URL"],
        "tunnel_status": runtime["TUNNEL_STATUS"],
        "tunnel_error": runtime["TUNNEL_ERROR"],
        "model_api_configured": runtime["MODEL_API_CONFIGURED"],
        "model_server_status": runtime["MODEL_SERVER_STATUS"],
        "model_server_source": runtime["MODEL_SERVER_SOURCE"],
        "video_analysis_enabled": runtime["VIDEO_ANALYSIS_ENABLED"],
        "supabase_configured": runtime["SUPABASE_CONFIGURED"],
    }


@app.get("/api/runtime-config")
async def runtime_config(request: Request) -> JSONResponse:
    return JSONResponse(_runtime_config(request))


@app.get("/config.js")
async def runtime_config_js(request: Request) -> PlainTextResponse:
    body = f"window.APP_CONFIG = {json.dumps(_runtime_config(request), ensure_ascii=True)};\n"
    return PlainTextResponse(body, media_type="application/javascript")


@app.get("/api/history")
async def get_history() -> list[dict]:
    return _read_history()


@app.get("/api/findings")
async def get_findings() -> list[dict]:
    return _combined_findings()


@app.post("/api/history")
async def save_history(request: Request) -> Dict[str, str]:
    try:
        data = await request.json()
        image_value = str(data.get("image", "")).strip()
        if image_value.startswith("data:image"):
            file_path = _decode_image_to_file(image_value, HISTORY_IMAGES_DIR, prefix="thumb")
            data["image"] = f"/history_images/{file_path.name}"

        _upsert_history_record(data)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze(request: Request) -> Any:
    try:
        content_type = str(request.headers.get("content-type", "")).lower()
        request_url = ""
        request_key = ""
        forward_json: dict[str, Any] | None = None
        mission_name = "SkyLink Photo Mission"
        persist_db = False

        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read") or not hasattr(upload, "filename"):
                raise HTTPException(status_code=400, detail="Multipart analyze requests must include a file field.")

            request_url = str(form.get("api_url", "")).strip()
            request_key = str(form.get("api_key", "")).strip()
            mission_name = str(form.get("mission_name", mission_name)).strip() or mission_name
            persist_db = _coerce_bool(form.get("persist_db"), False)
            file_bytes = await upload.read()
            content_type_hint = str(upload.content_type or "application/octet-stream")
            image_b64 = base64.b64encode(file_bytes).decode("ascii")
            if content_type_hint.startswith("image/"):
                image_b64 = f"data:{content_type_hint};base64,{image_b64}"

            forward_json = {
                key: value
                for key, value in (
                    (
                        key,
                        json.loads(str(value))
                        if str(value).strip()[:1] in {"[", "{"}
                        else str(value)
                    )
                    for key, value in form.multi_items()
                    if key not in {"file", "api_url", "api_key"} and value is not None
                )
            }
            forward_json["image_b64"] = image_b64
        else:
            payload = await request.json()
            request_url = str(payload.pop("api_url", "")).strip()
            request_key = str(payload.pop("api_key", "")).strip()
            mission_name = str(payload.get("mission_name", mission_name)).strip() or mission_name
            persist_db = _coerce_bool(payload.get("persist_db"), False)
            forward_json = payload

        configured_url, configured_key, _, _ = _resolved_model_target()
        forward_url = request_url or configured_url
        forward_key = request_key or configured_key
        if not forward_url:
            runtime = _runtime_config(request)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Model API is not ready yet. "
                    f"Managed model status: {runtime['MODEL_SERVER_STATUS']}. "
                    f"{runtime['MODEL_SERVER_ERROR'] or 'Startup is still in progress.'}"
                ),
            )
        async with httpx.AsyncClient(timeout=180.0) as client:
            headers = {"X-API-Key": forward_key} if forward_key else {}
            json_headers = dict(headers)
            json_headers["Content-Type"] = "application/json"
            response = await client.post(
                forward_url,
                json=forward_json or {},
                headers=json_headers,
            )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        response_payload = response.json()
        report = response_payload.get("report", response_payload)
        requested_vlm_mode = str((forward_json or {}).get("vlm_mode", "")).strip().lower()
        requested_vlm_model = str((forward_json or {}).get("vlm_model", "")).strip()
        source_payload = str((forward_json or {}).get("image_b64", "")).strip()
        if source_payload:
            report = await _apply_bridge_vlm_if_requested(
                report=report,
                source_image_payload=source_payload,
                location_payload=forward_json or {},
                requested_mode=requested_vlm_mode,
                requested_model=requested_vlm_model,
            )
            response_payload["report"] = report
        persisted_finding: dict[str, Any] | None = None
        persisted_to_supabase = False

        if persist_db and _supabase_configured() and init_supabase is not None and create_mission_record and persist_image_analysis and finalize_mission_record:
            supabase = init_supabase()
            if supabase is not None:
                mission_id = ""
                started_at = time.time()
                try:
                    mission_id = create_mission_record(supabase, mission_name, status="processing")
                    # Drastically shorten path for Windows compatibility
                    session_dir = PROCESSED_HISTORY_DIR / f"p_{time.strftime('%m%d_%H%M%S')}"
                    session_dir.mkdir(parents=True, exist_ok=True)
                    source_payload = str((forward_json or {}).get("image_b64", "")).strip()
                    if not source_payload:
                        raise RuntimeError("Photo payload missing image_b64 for persistence.")

                    original_file = _decode_image_to_file(source_payload, session_dir, prefix="source")
                    annotated_payload = str(report.get("annotated_image_b64", "")).strip()
                    storage_file = original_file
                    local_image_url = _processed_url(original_file)
                    if annotated_payload:
                        annotated_file = _decode_image_to_file(annotated_payload, session_dir, prefix="annotated")
                        storage_file = annotated_file
                        local_image_url = _processed_url(annotated_file)

                    timestamp_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    persistence_info = persist_image_analysis(
                        supabase,
                        mission_id=mission_id,
                        image_path=storage_file,
                        report=report,
                        timestamp_utc=timestamp_utc,
                        processing_seconds=time.time() - started_at,
                        image_name=_bridge_image_name((forward_json or {}).get("image_name"), storage_file.name),
                    )
                    finalize_mission_record(
                        supabase,
                        mission_id,
                        status="completed",
                        description=f"Processed standalone photo with {len(report.get('boxes', []))} detections.",
                    )
                    persisted_to_supabase = True
                    persisted_finding = {
                        **_finding_from_analysis(
                            report=report,
                            mission_name=mission_name,
                            mission_id=mission_id,
                            image_id=str(persistence_info.get("image_id") or ""),
                            image_name=_bridge_image_name((forward_json or {}).get("image_name"), storage_file.name),
                            image_url=str(persistence_info.get("public_url") or local_image_url),
                            timestamp_utc=timestamp_utc,
                            location_payload=forward_json or {},
                            source="supabase",
                            persisted_to_supabase=True,
                        ),
                        "local_image_url": local_image_url,
                    }
                    _upsert_history_record(persisted_finding)
                except Exception as exc:
                    print(f"Supabase Persistence Block Error: {exc}")
                    import traceback
                    traceback.print_exc()
                    if mission_id:
                        finalize_mission_record(
                            supabase,
                            mission_id,
                            status="failed",
                            description="Photo analysis persistence failed.",
                        )
                    raise

        response_payload["persisted_to_supabase"] = persisted_to_supabase
        if persisted_finding:
            response_payload["persisted_finding"] = persisted_finding
        return response_payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze-video")
async def analyze_video(
    request: Request,
    video: UploadFile = File(...),
    mission_name: str = Form("SkyLink Video Mission"),
    vlm_mode: str = Form(""),
    vlm_model: str = Form(""),
    detector_conf: str = Form(""),
    detector_iou: str = Form(""),
    detector_wbf_iou: str = Form(""),
    detector_wbf_skip: str = Form(""),
    detector_final_threshold: str = Form(""),
    detector_min_support: str = Form(""),
    speed_mps: float = Form(5.0),
    altitude_m: float = Form(10.0),
    fov: float = Form(82.6),
    overlap_fraction: float = Form(0.10),
    dedup_distance: int = Form(4),
    max_frames: int | None = Form(None),
    persist_db: str = Form("true"),
) -> dict[str, Any]:
    if not _video_pipeline_available():
        raise HTTPException(
            status_code=503,
            detail=f"Video analysis pipeline is unavailable: {VIDEO_PIPELINE_IMPORT_ERROR or 'missing dependencies'}",
        )
    if not str(video.content_type or "").lower().startswith("video/"):
        raise HTTPException(status_code=400, detail="Uploaded file is not recognized as a video.")

    configured_url, configured_key, _, _ = _resolved_model_target()
    if not configured_url:
        runtime = _runtime_config(request)
        raise HTTPException(
            status_code=503,
            detail=(
                "Model API is not ready yet. "
                f"Managed model status: {runtime['MODEL_SERVER_STATUS']}. "
                f"{runtime['MODEL_SERVER_ERROR'] or 'Startup is still in progress.'}"
            ),
        )

    session_id = f"v_{time.strftime('%m%d_%H%M')}"
    session_dir = PROCESSED_HISTORY_DIR / session_id
    frames_dir = session_dir / "frames"
    session_dir.mkdir(parents=True, exist_ok=True)

    original_name = video.filename or "upload.mp4"
    saved_video_path = session_dir / f"{_safe_stem(original_name, 'video')}{Path(original_name).suffix or '.mp4'}"
    await _save_upload_file(video, saved_video_path)

    request_overrides = {}
    if vlm_mode.strip():
        request_overrides["vlm_mode"] = vlm_mode.strip().lower()
    if vlm_model.strip():
        request_overrides["vlm_model"] = vlm_model.strip()
    if detector_conf.strip():
        request_overrides["detector_conf"] = detector_conf.strip()
    if detector_iou.strip():
        request_overrides["detector_iou"] = detector_iou.strip()
    if detector_wbf_iou.strip():
        request_overrides["detector_wbf_iou"] = detector_wbf_iou.strip()
    if detector_wbf_skip.strip():
        request_overrides["detector_wbf_skip"] = detector_wbf_skip.strip()
    if detector_final_threshold.strip():
        request_overrides["detector_final_threshold"] = detector_final_threshold.strip()
    if detector_min_support.strip():
        request_overrides["detector_min_support"] = detector_min_support.strip()

    supabase = init_supabase() if (_coerce_bool(persist_db, True) and _supabase_configured()) else None
    try:
        result = analyze_video_session(
            video_path=saved_video_path,
            mission_name=mission_name,
            speed_mps=speed_mps,
            altitude_m=altitude_m,
            fov=fov,
            overlap_fraction=overlap_fraction,
            max_frames=max_frames,
            dedup_hamming_threshold=(None if dedup_distance < 0 else dedup_distance),
            api_url=configured_url,
            api_key=configured_key,
            supabase=supabase,
            request_overrides=request_overrides or None,
            output_dir=frames_dir,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Video analysis failed: {exc}") from exc

    result["video_path"] = str(saved_video_path)
    payload = _materialize_video_result(session_dir, result)
    payload["persisted_to_supabase"] = bool(supabase)
    return payload


app.mount("/h", StaticFiles(directory=PROCESSED_HISTORY_DIR), name="processed_history")
app.mount("/history_images", StaticFiles(directory=HISTORY_IMAGES_DIR), name="history_images")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT)
