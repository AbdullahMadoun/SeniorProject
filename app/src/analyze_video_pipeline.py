"""
SkyLink — Video Analysis Pipeline
=================================
Orchestrates the workflow:
1. Video to frames (via video_extractor)
2. Frames to model backend (/analyze)
3. Optional persistence to Supabase (missions, mission_images, damage_detections)
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv
from supabase import Client, create_client

from video_extractor import DroneParams, extract_frames

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "h"
load_dotenv(ROOT_DIR / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
API_URL = os.getenv("API_URL", "http://localhost:17612")
API_KEY = os.getenv("API_KEY", "road-inspector-secret-key-2024")
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


def init_supabase() -> Optional[Client]:
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


def encode_image(path: Path) -> str:
    with path.open("rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def _normalize_analyze_url(api_url: str) -> str:
    trimmed = str(api_url or "").strip().rstrip("/")
    if not trimmed:
        trimmed = API_URL.rstrip("/")
    if trimmed.endswith("/analyze"):
        return trimmed
    return f"{trimmed}/analyze"


def _build_auth_headers(api_key: str, auth_scheme: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SkyLink-Drone/SkyLink",  # Required for OpenRouter
        "X-Title": "SkyLink Autonomous Inspection",                  # Required for OpenRouter
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


def _bridge_prompt_from_boxes(
    boxes: list[dict[str, Any]],
    *,
    width: int | None,
    height: int | None,
    lat: float | None,
    lon: float | None,
) -> str:
    lines: list[str] = []
    for index, box in enumerate(boxes):
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
        box_id = str(box.get("id") or f"D{index}")
        lines.append(
            f"- ID: {box_id}, Type: {label}, Ensemble Confidence: {confidence:.1f}%, "
            f"Support: {support} model(s), Dimensions: {w_px}x{h_px} pixels "
            f"(Area: {area}), Coords: [x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}]"
        )

    gps_str = f"GPS location (lat, lon): {lat}, {lon}." if lat is not None and lon is not None else "GPS location: Not provided."
    box_str = "\n".join(lines) if lines else "No defects detected by the ensemble detector."
    return (
        BRIDGE_VLM_USER_PROMPT_TEMPLATE
        + f"\n\n{gps_str}\nImage resolution: {int(width or 0)} x {int(height or 0)} pixels.\n\n"
        + "### DETECTED BOUNDING BOXES (From YOLO ensemble):\n"
        + box_str
    )


def _apply_bridge_vlm_if_requested(
    *,
    report: dict[str, Any],
    frame_b64: str,
    request_overrides: Optional[dict[str, Any]],
) -> dict[str, Any]:
    requested_mode = str((request_overrides or {}).get("vlm_mode", "")).strip().lower()
    if requested_mode != "api":
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "not_requested"
        return report

    resolved_mode = str(report.get("detector_debug", {}).get("resolved_vlm_mode", "")).strip().lower()
    if resolved_mode == "api":
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "remote_api"
        return report
    if not _bridge_vlm_available():
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "bridge_api_unconfigured"
        return report

    boxes = list(report.get("boxes", []))
    if not boxes:
        report.setdefault("detector_debug", {})["bridge_vlm_status"] = "skipped_no_boxes"
        return report

    location = (request_overrides or {}).get("location") or {"lat": 26.305, "lon": 50.146}
    lat = location.get("lat") if isinstance(location, dict) else None
    lon = location.get("lon") if isinstance(location, dict) else None
    model_name = str((request_overrides or {}).get("vlm_model", "")).strip() or BRIDGE_VLM_MODEL
    user_prompt = _bridge_prompt_from_boxes(
        boxes,
        width=report.get("image_width") or report.get("width"),
        height=report.get("image_height") or report.get("height"),
        lat=lat,
        lon=lon,
    )

    if BRIDGE_VLM_API_TYPE == "openai" or "openrouter.ai" in BRIDGE_VLM_API_URL:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": BRIDGE_VLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"} if "qwen" not in model_name.lower() else None,
        }
    else:
        payload = {
            "image_b64": frame_b64,
            "system_prompt": BRIDGE_VLM_SYSTEM_PROMPT,
            "prompt": user_prompt,
            "detections": boxes,
            "location": location if isinstance(location, dict) else None,
            "response_format": "report_markdown_and_severities",
        }

    response = requests.post(
        BRIDGE_VLM_API_URL,
        json=payload,
        headers=_build_auth_headers(BRIDGE_VLM_API_KEY, BRIDGE_VLM_API_AUTH_SCHEME),
        timeout=BRIDGE_VLM_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        if "report_markdown" in data or "severities" in data:
            api_result = data
        elif isinstance(data.get("report"), dict) and ("report_markdown" in data["report"] or "severities" in data["report"]):
            api_result = data["report"]
        else:
            text = data.get("text") or data.get("output_text") or data.get("content")
            api_result = _extract_json_from_text(text) if isinstance(text, str) else None
    else:
        api_result = None

    if not isinstance(api_result, dict):
        raise RuntimeError(f"Bridge VLM API returned unsupported payload shape: {json.dumps(data)[:500]}")

    severities = {
        str(key): str(value).strip().lower()
        for key, value in dict(api_result.get("severities", {})).items()
        if str(key).strip()
    }
    for box in boxes:
        box_id = str(box.get("id", "")).strip()
        if box_id and box_id in severities:
            box["severity"] = severities[box_id]

    report["report_markdown"] = str(api_result.get("report_markdown", report.get("report_markdown", "")))
    report.setdefault("detector_debug", {})
    report["detector_debug"]["resolved_vlm_mode"] = "api"
    report["detector_debug"]["resolved_vlm_model"] = model_name
    report["detector_debug"]["bridge_vlm_status"] = "bridge_api"
    return report


def analyze_frame_vast(
    image_b64: str,
    api_url: str = API_URL,
    api_key: str = API_KEY,
    supabase: Optional[Client] = None,
    *,
    request_overrides: Optional[dict[str, Any]] = None,
    return_full_response: bool = False,
) -> dict[str, Any]:
    """Send the base64 image to the configured analysis backend."""
    payload: dict[str, Any] = {
        "image_b64": image_b64,
        "location": {"lat": 26.305, "lon": 50.146},
    }
    if request_overrides:
        payload.update(request_overrides)

    if supabase:
        response = supabase.functions.invoke("vast-analyzer", invoke_options={"body": payload})
        if hasattr(response, "error") and response.error:
            raise RuntimeError(f"Edge Function Error: {response.error}")
        data = response.data or {}
        if return_full_response:
            return data
        if isinstance(data, dict) and "report" in data:
            return data["report"]
        return data

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"} if api_key else {"Content-Type": "application/json"}
    response = requests.post(_normalize_analyze_url(api_url), json=payload, headers=headers, timeout=300)
    response.raise_for_status()
    data = response.json()
    if return_full_response:
        return data
    if isinstance(data, dict) and "report" in data:
        return data["report"]
    return data


def upload_image_to_supabase(supabase: Client, mission_id: str, frame_path: Path) -> str:
    """Upload a frame to the public skylink_images bucket and return its public URL."""
    bucket_name = "skylink_images"
    object_name = f"{mission_id}/{frame_path.name}"
    try:
        with frame_path.open("rb") as handle:
            supabase.storage.from_(bucket_name).upload(
                path=object_name,
                file=handle,
                file_options={"content-type": "image/jpeg"},
            )
        print(f"[STORAGE] Successfully uploaded {frame_path.name} to {bucket_name}")
    except Exception as e:
        print(f"[ERROR] Supabase storage upload failed for {frame_path.name}: {e}")
        # Return local path fallback if upload fails, to at least keep local history working
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{object_name}"


def create_mission_record(supabase: Client, mission_name: str, *, status: str = "processing") -> str:
    mission_resp = supabase.table("missions").insert(
        {
            "name": mission_name,
            "status": status,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()
    if not mission_resp.data:
        raise RuntimeError("Failed to create mission in Supabase.")
    return str(mission_resp.data[0]["id"])


def finalize_mission_record(
    supabase: Client,
    mission_id: str,
    *,
    status: str,
    description: str,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "description": description,
    }
    if status == "completed":
        payload["ended_at"] = datetime.now(timezone.utc).isoformat()
    supabase.table("missions").update(payload).eq("id", mission_id).execute()


def persist_image_analysis(
    supabase: Client,
    *,
    mission_id: str,
    image_path: Path,
    report: dict[str, Any],
    timestamp_utc: str,
    processing_seconds: float,
    image_name: Optional[str] = None,
) -> dict[str, Any]:
    public_url = upload_image_to_supabase(supabase, mission_id, image_path)
    img_resp = supabase.table("mission_images").insert(
        {
            "mission_id": mission_id,
            "image_name": image_name or image_path.name,
            "processed_image_path": public_url,
            "processing_seconds": round(processing_seconds, 2),
            "timestamp_utc": timestamp_utc,
        }
    ).execute()

    image_id: Optional[str] = None
    if img_resp.data:
        image_id = str(img_resp.data[0]["id"])

    inserted_detections = 0
    boxes = list(report.get("boxes", []))
    if image_id:
        for box in boxes:
            severity_raw = str(box.get("severity", "unknown")).strip().lower()
            if severity_raw in ["moderate", "medium"]:
                severity = "medium"
            elif severity_raw in ["high", "critical", "severe"]:
                severity = "high"
            elif severity_raw in ["low", "minor", "slight"]:
                severity = "low"
            else:
                severity = "low"
            supabase.table("damage_detections").insert(
                {
                    "image_id": image_id,
                    "severity": severity,
                    "confidence": box.get("confidence", 0.0),
                    "damage_type": box.get("class", "damage"),
                    "bounding_box": box.get("bbox_xyxy"),
                }
            ).execute()
            inserted_detections += 1

    return {
        "mission_id": mission_id,
        "image_id": image_id,
        "public_url": public_url,
        "detection_count": inserted_detections,
    }


def analyze_video_session(
    *,
    video_path: Path,
    mission_name: str,
    speed_mps: float = 5.0,
    altitude_m: float = 10.0,
    fov: float = 82.6,
    overlap_fraction: float = 0.10,
    max_frames: Optional[int] = None,
    dedup_hamming_threshold: Optional[int] = 8,
    blur_threshold: Optional[float] = 80.0,
    api_url: str = API_URL,
    api_key: str = API_KEY,
    supabase: Optional[Client] = None,
    request_overrides: Optional[dict[str, Any]] = None,
    output_dir: Optional[Path] = None,
    on_frame_result: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    mission_id: Optional[str] = None
    should_persist = supabase is not None
    if should_persist:
        mission_id = create_mission_record(supabase, mission_name, status="processing")

    resolved_output_dir = output_dir or DEFAULT_RAW_DIR / str(mission_id or f"session_{int(time.time())}")
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    params = DroneParams(
        speed_mps=speed_mps,
        altitude_m=altitude_m,
        hfov_deg=fov,
        overlap_fraction=overlap_fraction,
    )
    frames = extract_frames(
        video_path=video_path,
        output_dir=resolved_output_dir,
        params=params,
        max_frames=max_frames,
        dedup_hamming_threshold=dedup_hamming_threshold,
        blur_threshold=blur_threshold,
        verbose=True,
    )

    step_m = (2.0 * params.altitude_m * math.tan(math.radians(params.hfov_deg / 2.0))) * (1.0 - params.overlap_fraction)
    interval_s = step_m / params.speed_mps
    base_time = datetime.now(timezone.utc)

    processed_count = 0
    start_time = time.time()
    frame_records: list[dict[str, Any]] = []

    try:
        for index, frame_path in enumerate(frames):
            ts = (base_time + timedelta(seconds=index * interval_s)).isoformat()
            frame_start = time.time()
            try:
                frame_b64 = encode_image(frame_path)
                full_response = analyze_frame_vast(
                    frame_b64,
                    api_url=api_url,
                    api_key=api_key,
                    supabase=supabase if request_overrides is None else None,
                    request_overrides=request_overrides,
                    return_full_response=True,
                )
                report = full_response.get("report", full_response)
                report = _apply_bridge_vlm_if_requested(
                    report=report,
                    frame_b64=frame_b64,
                    request_overrides=request_overrides,
                )
                process_sec = time.time() - frame_start
                public_url = ""
                image_id: Optional[str] = None
                persistence_info: dict[str, Any] = {}

                if should_persist and mission_id:
                    persistence_info = persist_image_analysis(
                        supabase,
                        mission_id=mission_id,
                        image_path=frame_path,
                        report=report,
                        timestamp_utc=ts,
                        processing_seconds=process_sec,
                        image_name=frame_path.name,
                    )
                    public_url = str(persistence_info.get("public_url") or "")
                    image_id = persistence_info.get("image_id")

                boxes = list(report.get("boxes", []))

                record = {
                    "frame_path": str(frame_path),
                    "timestamp_utc": ts,
                    "processing_seconds": round(process_sec, 2),
                    "report": report,
                    "public_url": public_url,
                    "mission_id": mission_id,
                    "image_id": image_id,
                    "persistence_info": persistence_info,
                }
                frame_records.append(record)
                processed_count += 1
                if on_frame_result:
                    on_frame_result(record)
                print(f"[{processed_count}/{len(frames)}] Analyzed {frame_path.name}: {len(boxes)} defects.")
            except Exception as exc:
                print(f"Error processing frame {frame_path.name}: {exc}")
                frame_records.append(
                    {
                        "frame_path": str(frame_path),
                        "timestamp_utc": ts,
                        "error": str(exc),
                    }
                )
    except Exception:
        if should_persist and mission_id:
            finalize_mission_record(
                supabase,
                mission_id,
                status="failed",
                description="Video analysis aborted unexpectedly.",
            )
        raise

    elapsed = round(time.time() - start_time, 1)
    if should_persist and mission_id:
        finalize_mission_record(
            supabase,
            mission_id,
            status="completed",
            description=f"Processed {processed_count} frames in {elapsed} seconds.",
        )

    return {
        "mission_id": mission_id,
        "mission_name": mission_name,
        "video_path": str(video_path),
        "output_dir": str(resolved_output_dir),
        "frame_count": len(frames),
        "processed_count": processed_count,
        "elapsed_seconds": elapsed,
        "frames": frame_records,
    }


def run_pipeline(
    video_path: Path,
    mission_name: str,
    speed_mps: float = 5.0,
    altitude_m: float = 10.0,
    fov: float = 82.6,
    overlap_fraction: float = 0.10,
    dedup_hamming_threshold: Optional[int] = 8,
    blur_threshold: Optional[float] = 80.0,
    max_frames: Optional[int] = None,
    api_url: str = API_URL,
    api_key: str = API_KEY,
    supabase: Optional[Client] = None,
) -> dict[str, Any]:
    print(f"--- Starting Pipeline for: {mission_name} ---")
    if supabase is None:
        supabase = init_supabase()
    result = analyze_video_session(
        video_path=video_path,
        mission_name=mission_name,
        speed_mps=speed_mps,
        altitude_m=altitude_m,
        fov=fov,
        overlap_fraction=overlap_fraction,
        dedup_hamming_threshold=dedup_hamming_threshold,
        blur_threshold=blur_threshold,
        max_frames=max_frames,
        api_url=api_url,
        api_key=api_key,
        supabase=supabase,
    )
    print("--- Pipeline Complete ---")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-End Extraction & Vast Analysis")
    parser.add_argument("--video", type=Path, required=True, help="Path to video file")
    parser.add_argument("--mission", type=str, default=f"Scan {int(time.time())}")
    parser.add_argument("--speed", type=float, default=5.0)
    parser.add_argument("--altitude", type=float, default=10.0)
    parser.add_argument("--fov", type=float, default=82.6)
    parser.add_argument("--overlap", type=float, default=0.10)
    parser.add_argument("--dedup-distance", type=int, default=8)
    parser.add_argument("--blur-threshold", type=float, default=80.0)
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args()

    run_pipeline(
        video_path=args.video,
        mission_name=args.mission,
        speed_mps=args.speed,
        altitude_m=args.altitude,
        fov=args.fov,
        overlap_fraction=args.overlap,
        dedup_hamming_threshold=(None if args.dedup_distance < 0 else args.dedup_distance),
        blur_threshold=(None if args.blur_threshold < 0 else args.blur_threshold),
        max_frames=args.max_frames,
    )


if __name__ == "__main__":
    main()
