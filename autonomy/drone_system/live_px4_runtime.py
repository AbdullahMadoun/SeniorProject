from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
import subprocess
import time

from .landing_target_projection import (
    DockTarget,
    build_projected_landing_target_frame,
    frame_to_dict,
    sample_from_projected_frame,
)
from .landing_target_stream import LandingTargetPublisher, sample_to_dict
from .models import VehicleLocalPose
from .vehicle_interface import MavsdkVehicleGateway


SITL_LOG_DIR_NAME = "sitl_logs"


def detect_wsl_bridge_ip() -> str | None:
    result = subprocess.run(
        ["wsl", "bash", "-lc", "hostname -I | awk '{print $1}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    bridge_ip = result.stdout.strip()
    if result.returncode != 0 or not bridge_ip:
        return None
    return bridge_ip


def snapshot_to_dict(snapshot) -> dict[str, object]:
    return {
        "connected": snapshot.connected,
        "armed": snapshot.armed,
        "in_air": snapshot.in_air,
        "mode": snapshot.mode.value,
        "battery_percent": snapshot.battery_percent,
        "position": {
            "lat": snapshot.position.lat if snapshot.position else None,
            "lon": snapshot.position.lon if snapshot.position else None,
            "alt_m": snapshot.position.alt_m if snapshot.position else None,
        },
        "mission_progress": {
            "current": snapshot.mission_progress.current,
            "total": snapshot.mission_progress.total,
        },
    }


def local_pose_to_dict(local_pose: VehicleLocalPose | None) -> dict[str, object]:
    if local_pose is None:
        return {}
    return {
        "north_m": local_pose.north_m,
        "east_m": local_pose.east_m,
        "down_m": local_pose.down_m,
        "yaw_deg": local_pose.yaw_deg,
        "roll_deg": local_pose.roll_deg,
        "pitch_deg": local_pose.pitch_deg,
    }


def attitude_to_dict(local_pose: VehicleLocalPose | None) -> dict[str, object]:
    if local_pose is None:
        return {}
    return {
        "roll_deg": local_pose.roll_deg,
        "pitch_deg": local_pose.pitch_deg,
        "yaw_deg": local_pose.yaw_deg,
    }


async def capture_live_telemetry(
    gateway: MavsdkVehicleGateway,
    *,
    elapsed_s: float | None = None,
) -> dict[str, object]:
    snapshot = await gateway.get_snapshot()
    local_pose = await gateway.get_local_pose()
    gps_info = await gateway.get_gps_info()
    payload = {
        "elapsed_s": round(elapsed_s, 3) if elapsed_s is not None else None,
        "snapshot": snapshot_to_dict(snapshot),
        "gps_info": gps_info,
        "local_pose": local_pose_to_dict(local_pose),
        "attitude_euler": attitude_to_dict(local_pose),
        "battery": {
            "percent": snapshot.battery_percent,
        },
    }
    return payload


def horizontal_distance_m(local_pose: VehicleLocalPose, dock_target: DockTarget) -> float:
    return math.hypot(
        local_pose.north_m - dock_target.north_m,
        local_pose.east_m - dock_target.east_m,
    )


def resolve_log_path(repo_root: Path, env_name: str, pattern: str) -> Path | None:
    raw = os.environ.get(env_name)
    if raw:
        candidate = Path(raw)
        if candidate.exists():
            return candidate
    sitl_log_dir = repo_root / "artifacts" / SITL_LOG_DIR_NAME
    matches = sorted(
        sitl_log_dir.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


async def wait_for_mission_entry(
    gateway: MavsdkVehicleGateway,
    *,
    timeout_s: float,
) -> tuple[object, list[dict[str, object]]]:
    observations: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = await gateway.get_snapshot()
        local_pose = await gateway.get_local_pose()
        observations.append(
            {
                "t_s": round(time.monotonic(), 3),
                "snapshot": snapshot_to_dict(snapshot),
                "local_pose": local_pose_to_dict(local_pose),
                "attitude_euler": attitude_to_dict(local_pose),
            }
        )
        if snapshot.in_air and snapshot.mode.value == "mission":
            return snapshot, observations
        await asyncio.sleep(1.0)
    raise RuntimeError("PX4 SITL did not enter mission mode before timeout.")


async def wait_for_departure(
    gateway: MavsdkVehicleGateway,
    dock_target: DockTarget,
    *,
    min_radius_m: float,
    timeout_s: float,
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        local_pose = await gateway.get_local_pose()
        snapshot = await gateway.get_snapshot()
        if local_pose is None:
            await asyncio.sleep(1.0)
            continue
        distance_m = horizontal_distance_m(local_pose, dock_target)
        observations.append(
            {
                "t_s": round(time.monotonic(), 3),
                "local_pose": local_pose_to_dict(local_pose),
                "attitude_euler": attitude_to_dict(local_pose),
                "horizontal_distance_to_dock_m": distance_m,
                "snapshot": snapshot_to_dict(snapshot),
            }
        )
        if distance_m >= min_radius_m:
            return observations
        await asyncio.sleep(1.0)
    raise RuntimeError("Vehicle did not depart the dock area before timeout.")


async def wait_for_mission_completion(
    gateway: MavsdkVehicleGateway,
    *,
    timeout_s: float,
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = await gateway.get_snapshot()
        local_pose = await gateway.get_local_pose()
        observations.append(
            {
                "t_s": round(time.monotonic(), 3),
                "snapshot": snapshot_to_dict(snapshot),
                "local_pose": local_pose_to_dict(local_pose),
                "attitude_euler": attitude_to_dict(local_pose),
            }
        )
        mission_progress = snapshot.mission_progress
        if mission_progress.total > 0 and mission_progress.current >= mission_progress.total:
            return observations
        await asyncio.sleep(1.0)
    raise RuntimeError("Vehicle did not complete the uploaded mission before timeout.")


async def wait_for_rtl_approach_window(
    gateway: MavsdkVehicleGateway,
    dock_target: DockTarget,
    *,
    activation_radius_m: float,
    timeout_s: float,
) -> tuple[VehicleLocalPose, list[dict[str, object]]]:
    observations: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        local_pose = await gateway.get_local_pose()
        snapshot = await gateway.get_snapshot()
        if local_pose is None:
            await asyncio.sleep(0.5)
            continue
        distance_m = horizontal_distance_m(local_pose, dock_target)
        altitude_agl_m = max(0.0, dock_target.down_m - local_pose.down_m)
        observations.append(
            {
                "t_s": round(time.monotonic(), 3),
                "local_pose": local_pose_to_dict(local_pose),
                "attitude_euler": attitude_to_dict(local_pose),
                "horizontal_distance_to_dock_m": distance_m,
                "altitude_agl_m": altitude_agl_m,
                "snapshot": snapshot_to_dict(snapshot),
            }
        )
        if (
            snapshot.mode.value == "return_to_launch"
            and snapshot.in_air
            and distance_m <= activation_radius_m
            and altitude_agl_m >= 1.0
        ):
            return local_pose, observations
        await asyncio.sleep(0.5)
    raise RuntimeError("Vehicle did not reach the dock approach window before timeout.")


async def stream_live_projected_targets(
    gateway: MavsdkVehicleGateway,
    publisher: LandingTargetPublisher,
    dock_target: DockTarget,
    *,
    rate_hz: float,
    duration_s: float,
    require_touchdown: bool = True,
    touchdown_altitude_m: float = 0.2,
) -> list[dict[str, object]]:
    interval_s = 1.0 / rate_hz
    iterations = max(1, int(duration_s * rate_hz))
    records: list[dict[str, object]] = []
    ground_record_streak = 0
    touchdown_confirmed = False
    for index in range(iterations):
        loop_start = time.monotonic()
        local_pose = await gateway.get_local_pose()
        snapshot = await gateway.get_snapshot()
        if local_pose is None:
            raise RuntimeError("Live PX4 local pose was unavailable during dock-approach streaming.")
        frame = build_projected_landing_target_frame(local_pose, dock_target)
        sample = sample_from_projected_frame(frame)
        publisher.send_sample(sample)
        altitude_agl_m = max(0.0, dock_target.down_m - local_pose.down_m)
        records.append(
            {
                "index": index,
                "snapshot": snapshot_to_dict(snapshot),
                "vehicle_local_pose": local_pose_to_dict(local_pose),
                "attitude_euler": attitude_to_dict(local_pose),
                "horizontal_distance_to_dock_m": horizontal_distance_m(local_pose, dock_target),
                "altitude_agl_m": altitude_agl_m,
                "projected_frame": frame_to_dict(frame),
                "sample": sample_to_dict(sample),
            }
        )
        if not snapshot.in_air and altitude_agl_m <= touchdown_altitude_m:
            ground_record_streak += 1
        else:
            ground_record_streak = 0
        if ground_record_streak >= 3:
            touchdown_confirmed = True
            break
        remaining_s = interval_s - (time.monotonic() - loop_start)
        if remaining_s > 0.0:
            await asyncio.sleep(remaining_s)
    if require_touchdown and not touchdown_confirmed:
        last_record = records[-1] if records else {}
        raise RuntimeError(
            "Vehicle did not reach confirmed touchdown during landing-target streaming "
            f"within {duration_s:.1f}s. Last record: {last_record}"
        )
    return records
