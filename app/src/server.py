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
    from analyze_video_pipeline import analyze_video_session, init_supabase
    VIDEO_PIPELINE_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    analyze_video_session = None
    init_supabase = None
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
    os.getenv("SKYLINK_PROCESSED_HISTORY_DIR", ROOT_DIR / "data" / "processed" / "history")
)
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
HISTORY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

if not HISTORY_FILE.exists():
    HISTORY_FILE.write_text("[]", encoding="utf-8")

STATIC_VLM_API_URL = os.getenv("SKYLINK_VLM_API_URL", "")
STATIC_VLM_API_KEY = os.getenv("SKYLINK_VLM_API_KEY", "")
BRIDGE_PORT = int(os.getenv("SKYLINK_BRIDGE_PORT", "8001"))
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
CLOUDFLARED_BIN = os.getenv("SKYLINK_CLOUDFLARED_BIN", "cloudflared").strip() or "cloudflared"
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


def _read_history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_history(history: list[dict]) -> None:
    HISTORY_FILE.write_text(json.dumps(history[-50:]), encoding="utf-8")


def _split_data_uri(value: str) -> Tuple[str, str]:
    if not value or "," not in value:
        raise ValueError("Invalid data URI payload.")
    header, body = value.split(",", 1)
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
    relative = path.resolve().relative_to(PROCESSED_HISTORY_DIR.resolve())
    return f"/processed_history/{relative.as_posix()}"


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


@app.post("/api/history")
async def save_history(request: Request) -> Dict[str, str]:
    try:
        data = await request.json()
        image_value = str(data.get("image", "")).strip()
        if image_value.startswith("data:image"):
            file_path = _decode_image_to_file(image_value, HISTORY_IMAGES_DIR, prefix="thumb")
            data["image"] = f"/history_images/{file_path.name}"

        history = _read_history()
        history.append(data)
        _write_history(history)
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

        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read") or not hasattr(upload, "filename"):
                raise HTTPException(status_code=400, detail="Multipart analyze requests must include a file field.")

            request_url = str(form.get("api_url", "")).strip()
            request_key = str(form.get("api_key", "")).strip()
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
        return response.json()
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

    session_id = f"video_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    session_dir = PROCESSED_HISTORY_DIR / session_id
    frames_dir = session_dir / "frames"
    session_dir.mkdir(parents=True, exist_ok=True)

    original_name = video.filename or "upload.mp4"
    saved_video_path = session_dir / f"{_safe_stem(original_name, 'video')}{Path(original_name).suffix or '.mp4'}"
    await _save_upload_file(video, saved_video_path)

    request_overrides = {}
    if vlm_mode.strip():
        request_overrides["vlm_mode"] = vlm_mode.strip().lower()

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


app.mount("/history_images", StaticFiles(directory=HISTORY_IMAGES_DIR), name="history_images")
app.mount("/processed_history", StaticFiles(directory=PROCESSED_HISTORY_DIR), name="processed_history")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT)
