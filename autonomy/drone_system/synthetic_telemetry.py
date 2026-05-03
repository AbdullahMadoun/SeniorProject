from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from pathlib import Path

from .geometry import generate_lawnmower_pattern
from .models import Waypoint

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None


def _video_metadata(video_path: str | Path) -> tuple[int, float]:
    if cv2 is None:
        raise RuntimeError("OpenCV not installed. Use explicit frame count and FPS instead.")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    cap.release()
    if frames <= 0 or fps <= 0:
        raise ValueError("Invalid video metadata.")
    return frames, fps


def interpolate_path(waypoints: list[Waypoint], total_frames: int) -> list[Waypoint]:
    if len(waypoints) < 2:
        raise ValueError("At least two waypoints are required.")

    distances: list[float] = []
    total_distance = 0.0
    for idx in range(len(waypoints) - 1):
        a = waypoints[idx]
        b = waypoints[idx + 1]
        dlat = (b.lat - a.lat) * 111_000.0
        dlon = (b.lon - a.lon) * 111_000.0 * math.cos(math.radians(a.lat))
        distance = math.sqrt((dlat * dlat) + (dlon * dlon))
        distances.append(distance)
        total_distance += distance

    if total_distance <= 0:
        return [waypoints[0] for _ in range(total_frames)]

    positions: list[Waypoint] = []
    segment_index = 0
    segment_progress = 0.0
    frame_step = total_distance / max(total_frames - 1, 1)

    for _ in range(total_frames):
        start = waypoints[segment_index]
        end = waypoints[min(segment_index + 1, len(waypoints) - 1)]
        seg_len = max(distances[min(segment_index, len(distances) - 1)], 1e-6)
        ratio = min(1.0, segment_progress / seg_len)
        positions.append(
            Waypoint(
                lat=start.lat + (end.lat - start.lat) * ratio,
                lon=start.lon + (end.lon - start.lon) * ratio,
                alt_m=start.alt_m + (end.alt_m - start.alt_m) * ratio,
            )
        )
        segment_progress += frame_step
        while segment_index < len(distances) - 1 and segment_progress >= distances[segment_index]:
            segment_progress -= distances[segment_index]
            segment_index += 1
    return positions


def generate_synthetic_telemetry_csv(
    output_csv: str | Path,
    home: Waypoint,
    width_m: float,
    height_m: float,
    row_spacing_m: float,
    altitude_m: float,
    frames: int,
    fps: float,
) -> Path:
    survey_path = generate_lawnmower_pattern(home, width_m, height_m, row_spacing_m, altitude_m)
    positions = interpolate_path(survey_path, frames)
    start_time = datetime(2026, 1, 15, 9, 0, 0)

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["frame", "timestamp", "lat", "lon", "alt"])
        writer.writeheader()
        for idx, waypoint in enumerate(positions):
            writer.writerow(
                {
                    "frame": idx,
                    "timestamp": (start_time + timedelta(seconds=idx / fps)).isoformat(),
                    "lat": f"{waypoint.lat:.7f}",
                    "lon": f"{waypoint.lon:.7f}",
                    "alt": f"{waypoint.alt_m:.3f}",
                }
            )
    return output_path


def resolve_frames_and_fps(video: str | Path | None, frames: int | None, fps: float | None) -> tuple[int, float]:
    if video:
        return _video_metadata(video)
    if frames is None or fps is None:
        raise ValueError("Provide either a video path or both frames and fps.")
    return frames, fps
