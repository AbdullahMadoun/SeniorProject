from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = STATIC_DIR / "history.json"
HISTORY_IMAGES_DIR = STATIC_DIR / "history_images"
PROCESSED_HISTORY_DIR = ROOT_DIR / "data" / "processed" / "history"
HISTORY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

if not HISTORY_FILE.exists():
    HISTORY_FILE.write_text("[]", encoding="utf-8")

VLM_API_URL = os.getenv("SKYLINK_VLM_API_URL", "")
VLM_API_KEY = os.getenv("SKYLINK_VLM_API_KEY", "")

app = FastAPI(title="SkyLink Bridge")
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


@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


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
            data["image"] = f"history_images/{file_path.name}"

        history = _read_history()
        history.append(data)
        _write_history(history)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze(request: Request) -> Any:
    try:
        payload = await request.json()
        forward_url = str(payload.pop("api_url", VLM_API_URL)).strip() or VLM_API_URL
        forward_key = VLM_API_KEY
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                forward_url,
                json=payload,
                headers={"X-API-Key": forward_key, "Content-Type": "application/json"} if forward_key else {"Content-Type": "application/json"},
            )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc



app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    port = int(os.getenv("SKYLINK_BRIDGE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
