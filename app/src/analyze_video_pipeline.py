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
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv
from supabase import Client, create_client

from video_extractor import DroneParams, extract_frames

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw"
load_dotenv(ROOT_DIR / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
API_URL = os.getenv("API_URL", "http://localhost:17612")
API_KEY = os.getenv("API_KEY", "road-inspector-secret-key-2024")


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
    except Exception:
        pass
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{object_name}"


def analyze_video_session(
    *,
    video_path: Path,
    mission_name: str,
    speed_mps: float = 5.0,
    altitude_m: float = 10.0,
    fov: float = 82.6,
    overlap_fraction: float = 0.10,
    max_frames: Optional[int] = None,
    dedup_hamming_threshold: Optional[int] = 4,
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
        mission_resp = supabase.table("missions").insert(
            {
                "name": mission_name,
                "status": "processing",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
        if not mission_resp.data:
            raise RuntimeError("Failed to create mission in Supabase.")
        mission_id = mission_resp.data[0]["id"]

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
                process_sec = time.time() - frame_start
                public_url = ""
                image_id: Optional[str] = None

                if should_persist and mission_id:
                    public_url = upload_image_to_supabase(supabase, mission_id, frame_path)
                    img_resp = supabase.table("mission_images").insert(
                        {
                            "mission_id": mission_id,
                            "image_name": frame_path.name,
                            "processed_image_path": public_url,
                            "processing_seconds": round(process_sec, 2),
                            "timestamp_utc": ts,
                        }
                    ).execute()
                    if img_resp.data:
                        image_id = img_resp.data[0]["id"]

                boxes = list(report.get("boxes", []))
                if should_persist and image_id:
                    for box in boxes:
                        severity = str(box.get("severity", "unknown")).strip().lower()
                        if severity == "moderate":
                            severity = "medium"
                        supabase.table("damage_detections").insert(
                            {
                                "image_id": image_id,
                                "severity": severity,
                                "confidence": box.get("confidence", 0.0),
                                "damage_type": box.get("class", "damage"),
                                "bounding_box": box.get("bbox_xyxy"),
                            }
                        ).execute()

                record = {
                    "frame_path": str(frame_path),
                    "timestamp_utc": ts,
                    "processing_seconds": round(process_sec, 2),
                    "report": report,
                    "public_url": public_url,
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
            supabase.table("missions").update(
                {
                    "status": "failed",
                    "description": "Video analysis aborted unexpectedly.",
                }
            ).eq("id", mission_id).execute()
        raise

    elapsed = round(time.time() - start_time, 1)
    if should_persist and mission_id:
        supabase.table("missions").update(
            {
                "status": "completed",
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "description": f"Processed {processed_count} frames in {elapsed} seconds.",
            }
        ).eq("id", mission_id).execute()

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
    dedup_hamming_threshold: Optional[int] = 4,
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
    parser.add_argument("--dedup-distance", type=int, default=4)
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
        max_frames=args.max_frames,
    )


if __name__ == "__main__":
    main()
