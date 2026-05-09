"""FastAPI service exposing camera record / retrieve endpoints over HTTP.

Endpoints
---------
POST   /start              Start a new recording.
POST   /stop               Stop the active recording.
GET    /file/{recording_id}    Stream the recorded MP4 to the caller.
DELETE /file/{recording_id}    Delete a recording from disk + registry.
GET    /health             Liveness + recording-state + free-disk probe.

Storage
-------
Recordings are written under ``/tmp/quickrecord/{recording_id}.mp4``.
``/tmp`` is wiped on Pi reboot, which matches the throw-away nature of
this tool. The in-memory recording registry is also reset on service
restart, so files left on disk after a restart become orphans —
``DELETE /file/{id}`` won't find them in the registry. Clean up
manually if that bothers you, or just reboot.

Security
--------
This service has no authentication. ``__main__.py`` binds it to
``0.0.0.0`` so the laptop can reach it over the LAN — only run the
service on a trusted network (a dev hotspot, not an open network).
"""

from __future__ import annotations

import datetime as _dt
import logging
import pathlib
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .recorder import CameraRecorder

LOGGER = logging.getLogger(__name__)

STORAGE_DIR = pathlib.Path("/tmp/quickrecord")
DEFAULT_RESOLUTION: tuple[int, int] = (1920, 1080)
DEFAULT_BITRATE_BPS = 10_000_000
MIN_FREE_DISK_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup pre-flight (ffmpeg presence + storage dir).

    ``FfmpegOutput`` shells out to the system ``ffmpeg`` binary to mux
    H264 into MP4. Without ffmpeg the recordings come back as 0-byte
    or unplayable files, so we fail fast at startup rather than at
    first ``/start``. No teardown is needed — recordings persist on
    disk by design.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError(
            "ffmpeg binary not found or not runnable; install with "
            "`sudo apt install -y ffmpeg` and restart the service"
        ) from exc

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    LOGGER.info("quickrecord service ready, storage=%s", STORAGE_DIR)
    yield


app = FastAPI(title="quickrecord", version="0.1.0", lifespan=_lifespan)

# This service must run with `--workers 1` (the default in __main__.py).
# The state below is in-process memory; multi-worker uvicorn would give
# each worker its own _recordings dict, so the recording_id from one
# worker's /start would be invisible to another worker's /stop.
_recorder = CameraRecorder()
_recordings: dict[str, dict[str, Any]] = {}
_active_id: Optional[str] = None


class StartRequest(BaseModel):
    """Optional knobs for ``POST /start``. Both fields default if absent."""

    resolution: Optional[tuple[int, int]] = None
    bitrate_bps: Optional[int] = None


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


@app.post("/start")
def start_recording(req: StartRequest) -> dict[str, Any]:
    """Start a new recording and return its assigned id."""
    global _active_id

    if _recorder.is_recording():
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already recording",
                "current_recording_id": _active_id,
            },
        )

    free_bytes = shutil.disk_usage(STORAGE_DIR).free
    if free_bytes < MIN_FREE_DISK_BYTES:
        raise HTTPException(
            status_code=507,
            detail={
                "error": "insufficient disk space",
                "free_bytes": free_bytes,
                "min_required_bytes": MIN_FREE_DISK_BYTES,
            },
        )

    resolution = (
        tuple(req.resolution) if req.resolution else DEFAULT_RESOLUTION
    )
    bitrate = (
        req.bitrate_bps if req.bitrate_bps is not None else DEFAULT_BITRATE_BPS
    )

    recording_id = str(uuid.uuid4())
    output_path = STORAGE_DIR / f"{recording_id}.mp4"
    started_at = _utc_now_iso()

    try:
        _recorder.start(output_path, resolution, bitrate)
    except RuntimeError as exc:
        if str(exc) == "already recording":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "already recording",
                    "current_recording_id": _active_id,
                },
            )
        raise
    except Exception as exc:
        # 503, not 500: the service is healthy but the camera resource
        # isn't available right now — most likely another consumer
        # (autonomy/companion/video_logger.py or similar) holds it.
        LOGGER.exception("camera start failed")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "camera unavailable; another process likely holds it",
                "details": repr(exc),
            },
        )

    _recordings[recording_id] = {
        "started_at": started_at,
        "stopped_at": None,
        "path": str(output_path),
        "size_bytes": None,
    }
    _active_id = recording_id
    return {"recording_id": recording_id, "started_at": started_at}


@app.post("/stop")
def stop_recording() -> dict[str, Any]:
    """Stop the active recording and return final metadata."""
    global _active_id

    if not _recorder.is_recording():
        raise HTTPException(
            status_code=409,
            detail={"error": "not recording"},
        )

    rid = _active_id

    try:
        _recorder.stop()
    except RuntimeError as exc:
        _active_id = None
        if str(exc) == "not recording":
            raise HTTPException(status_code=409, detail={"error": "not recording"})
        raise HTTPException(
            status_code=500,
            detail={"error": "stop failed", "details": repr(exc)},
        )
    except Exception as exc:
        _active_id = None
        raise HTTPException(
            status_code=500,
            detail={"error": "stop failed", "details": repr(exc)},
        )

    _active_id = None
    stopped_at = _utc_now_iso()

    rec = _recordings.get(rid) if rid is not None else None
    if rec is None:
        raise HTTPException(
            status_code=500,
            detail={"error": "recording state lost"},
        )

    path = pathlib.Path(rec["path"])
    size_bytes = path.stat().st_size if path.exists() else 0
    started_at = _dt.datetime.fromisoformat(rec["started_at"])
    duration_s = (
        _dt.datetime.fromisoformat(stopped_at) - started_at
    ).total_seconds()

    rec["stopped_at"] = stopped_at
    rec["size_bytes"] = size_bytes

    return {
        "recording_id": rid,
        "stopped_at": stopped_at,
        "size_bytes": size_bytes,
        "duration_s": duration_s,
    }


@app.get("/file/{recording_id}")
def get_file(recording_id: str) -> FileResponse:
    """Stream the recorded MP4 back to the caller.

    The file is NOT deleted on download — re-fetching the same id
    returns the same bytes. Use ``DELETE /file/{recording_id}`` for
    explicit cleanup.
    """
    rec = _recordings.get(recording_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown recording_id"},
        )
    path = pathlib.Path(rec["path"])
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "file gone from disk"},
        )
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=f"{recording_id}.mp4",
    )


@app.delete("/file/{recording_id}")
def delete_file(recording_id: str) -> dict[str, Any]:
    """Delete the recording's file and remove it from the registry."""
    rec = _recordings.get(recording_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown recording_id"},
        )
    path = pathlib.Path(rec["path"])
    if path.exists():
        path.unlink()
    _recordings.pop(recording_id, None)
    return {"recording_id": recording_id, "deleted": True}


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe with recording state and free-disk metric."""
    free_bytes = (
        shutil.disk_usage(STORAGE_DIR).free if STORAGE_DIR.exists() else 0
    )
    return {
        "status": "ok",
        "recording": _recorder.is_recording(),
        "current_recording_id": _active_id,
        "free_disk_bytes": free_bytes,
    }
