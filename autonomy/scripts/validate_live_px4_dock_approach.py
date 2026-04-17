from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.geometry import generate_lawnmower_pattern
from autonomy.drone_system.landing_target_projection import (
    DockTarget,
    build_projected_landing_target_frame,
    frame_to_dict,
    sample_from_projected_frame,
)
from autonomy.drone_system.landing_target_proof import (
    count_bridge_direction,
    parse_receiver_observation,
)
from autonomy.drone_system.landing_target_stream import (
    LandingTargetPublisher,
    connection_string_for_endpoint,
    sample_to_dict,
)
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import VehicleLocalPose, Waypoint
from autonomy.drone_system.vehicle_interface import MavsdkVehicleGateway


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_dock_approach_validation.json"
SITL_LOG_DIR = REPO_ROOT / "artifacts" / "sitl_logs"
DEFAULT_SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_ENDPOINT = "gcs"
DEFAULT_SURVEY_WIDTH_M = 20.0
DEFAULT_SURVEY_HEIGHT_M = 20.0
DEFAULT_ROW_SPACING_M = 10.0
DEFAULT_ALTITUDE_M = 10.0
DEPARTURE_RADIUS_M = 5.0
MISSION_ENTRY_TIMEOUT_S = 30.0
DEPARTURE_TIMEOUT_S = 20.0
RTL_APPROACH_TIMEOUT_S = 40.0
STREAM_DURATION_S = 12.0


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


def use_direct_px4_transport() -> bool:
    raw = os.environ.get("LANDING_TARGET_DIRECT_PX4")
    if raw is not None and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.name != "nt"


def _snapshot_to_dict(snapshot) -> dict[str, object]:
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


def _local_pose_to_dict(local_pose: VehicleLocalPose | None) -> dict[str, object]:
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


def _attitude_to_dict(local_pose: VehicleLocalPose | None) -> dict[str, object]:
    if local_pose is None:
        return {}
    return {
        "roll_deg": local_pose.roll_deg,
        "pitch_deg": local_pose.pitch_deg,
        "yaw_deg": local_pose.yaw_deg,
    }


def _horizontal_distance_m(local_pose: VehicleLocalPose, dock_target: DockTarget) -> float:
    return math.hypot(
        local_pose.north_m - dock_target.north_m,
        local_pose.east_m - dock_target.east_m,
    )


def _resolve_log_path(env_name: str, pattern: str) -> Path | None:
    raw = os.environ.get(env_name)
    if raw:
        candidate = Path(raw)
        if candidate.exists():
            return candidate

    matches = sorted(
        SITL_LOG_DIR.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


async def _wait_for_mission_entry(
    gateway: MavsdkVehicleGateway,
    *,
    timeout_s: float,
) -> tuple[object, list[dict[str, object]]]:
    snapshots: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = await gateway.get_snapshot()
        local_pose = await gateway.get_local_pose()
        snapshots.append(
            {
                "t_s": round(time.monotonic(), 3),
                "snapshot": _snapshot_to_dict(snapshot),
                "local_pose": _local_pose_to_dict(local_pose),
                "attitude_euler": _attitude_to_dict(local_pose),
            }
        )
        if snapshot.in_air and snapshot.mode.value == "mission":
            return snapshot, snapshots
        await asyncio.sleep(1.0)
    raise RuntimeError("PX4 SITL did not enter mission mode before timeout.")


async def _wait_for_departure(
    gateway: MavsdkVehicleGateway,
    dock_target: DockTarget,
    *,
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
        horizontal_distance_m = _horizontal_distance_m(local_pose, dock_target)
        observation = {
            "t_s": round(time.monotonic(), 3),
            "local_pose": _local_pose_to_dict(local_pose),
            "attitude_euler": _attitude_to_dict(local_pose),
            "horizontal_distance_to_dock_m": horizontal_distance_m,
            "snapshot": _snapshot_to_dict(snapshot),
        }
        observations.append(observation)
        if horizontal_distance_m >= DEPARTURE_RADIUS_M:
            return observations
        await asyncio.sleep(1.0)
    raise RuntimeError("Vehicle did not depart the dock area before RTL timeout.")


async def _wait_for_rtl_approach_window(
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
        horizontal_distance_m = _horizontal_distance_m(local_pose, dock_target)
        altitude_agl_m = max(0.0, dock_target.down_m - local_pose.down_m)
        observation = {
            "t_s": round(time.monotonic(), 3),
            "local_pose": _local_pose_to_dict(local_pose),
            "attitude_euler": _attitude_to_dict(local_pose),
            "horizontal_distance_to_dock_m": horizontal_distance_m,
            "altitude_agl_m": altitude_agl_m,
            "snapshot": _snapshot_to_dict(snapshot),
        }
        observations.append(observation)
        if (
            snapshot.mode.value == "return_to_launch"
            and snapshot.in_air
            and horizontal_distance_m <= activation_radius_m
            and altitude_agl_m >= 1.0
        ):
            return local_pose, observations
        await asyncio.sleep(0.5)
    raise RuntimeError("Vehicle did not reach the dock approach window before timeout.")


async def _stream_live_projected_targets(
    gateway: MavsdkVehicleGateway,
    publisher: LandingTargetPublisher,
    dock_target: DockTarget,
    *,
    rate_hz: float,
    duration_s: float,
) -> list[dict[str, object]]:
    interval_s = 1.0 / rate_hz
    iterations = max(1, int(duration_s * rate_hz))
    records: list[dict[str, object]] = []
    ground_record_streak = 0
    for index in range(iterations):
        loop_start = time.monotonic()
        local_pose = await gateway.get_local_pose()
        snapshot = await gateway.get_snapshot()
        if local_pose is None:
            raise RuntimeError("Live PX4 local pose was unavailable during dock-approach streaming.")
        frame = build_projected_landing_target_frame(local_pose, dock_target)
        sample = sample_from_projected_frame(frame)
        publisher.send_sample(sample)
        records.append(
            {
                "index": index,
                "snapshot": _snapshot_to_dict(snapshot),
                "vehicle_local_pose": _local_pose_to_dict(local_pose),
                "attitude_euler": _attitude_to_dict(local_pose),
                "horizontal_distance_to_dock_m": _horizontal_distance_m(local_pose, dock_target),
                "altitude_agl_m": max(0.0, dock_target.down_m - local_pose.down_m),
                "projected_frame": frame_to_dict(frame),
                "sample": sample_to_dict(sample),
            }
        )
        altitude_agl_m = max(0.0, dock_target.down_m - local_pose.down_m)
        if not snapshot.in_air and altitude_agl_m <= 0.5:
            ground_record_streak += 1
        else:
            ground_record_streak = 0
        if ground_record_streak >= 3:
            break
        remaining_s = interval_s - (time.monotonic() - loop_start)
        if remaining_s > 0.0:
            await asyncio.sleep(remaining_s)
    return records


async def main() -> None:
    baseline = load_system_baseline()
    system_address = os.environ.get("MAVSDK_SYSTEM_ADDRESS", DEFAULT_SYSTEM_ADDRESS)
    connect_timeout_s = float(
        os.environ.get("MAVSDK_CONNECT_TIMEOUT_S", str(DEFAULT_CONNECT_TIMEOUT_S))
    )
    endpoint = os.environ.get("LANDING_TARGET_ENDPOINT", DEFAULT_ENDPOINT)
    direct_px4 = use_direct_px4_transport()
    bridge_ip = None if direct_px4 else (os.environ.get("WSL_BRIDGE_IP") or detect_wsl_bridge_ip())
    connection_string = os.environ.get(
        "LANDING_TARGET_CONNECTION_STRING",
        connection_string_for_endpoint(endpoint, bridge_ip=bridge_ip, direct_px4=direct_px4),
    )
    dock_target = DockTarget(
        north_m=baseline.docking.dock_center_north_m,
        east_m=baseline.docking.dock_center_east_m,
        down_m=baseline.docking.dock_center_down_m,
    )

    gateway = MavsdkVehicleGateway(
        baseline,
        system_address=system_address,
        connect_timeout_s=connect_timeout_s,
    )

    await gateway.connect()
    try:
        initial_snapshot = await gateway.get_snapshot()
        initial_local_pose = await gateway.get_local_pose()
        if initial_snapshot.position is None:
            raise RuntimeError("Live PX4 snapshot did not expose a position.")
        if initial_local_pose is None:
            raise RuntimeError("Live PX4 local position is required for dock-approach validation.")

        live_home = Waypoint(
            lat=initial_snapshot.position.lat,
            lon=initial_snapshot.position.lon,
            alt_m=max(initial_snapshot.position.alt_m, 0.0),
        )
        mission = MissionPlanRequest(
            mission_id="live-dock-approach-validation",
            home=live_home,
            waypoints=tuple(
                generate_lawnmower_pattern(
                    live_home,
                    DEFAULT_SURVEY_WIDTH_M,
                    DEFAULT_SURVEY_HEIGHT_M,
                    DEFAULT_ROW_SPACING_M,
                    DEFAULT_ALTITUDE_M,
                )
            ),
            cruise_speed_mps=baseline.speed_band.nominal_mps,
        )

        await gateway.upload_geofence(
            build_home_geofence(live_home, baseline.mission_limits.max_radius_m)
        )
        await gateway.upload_mission(mission)
        await gateway.arm()
        await gateway.start_mission()

        mission_entry_snapshot, mission_entry_observations = await _wait_for_mission_entry(
            gateway,
            timeout_s=MISSION_ENTRY_TIMEOUT_S,
        )
        departure_observations = await _wait_for_departure(
            gateway,
            dock_target,
            timeout_s=DEPARTURE_TIMEOUT_S,
        )

        await gateway.return_to_launch()
        approach_local_pose, rtl_approach_observations = await _wait_for_rtl_approach_window(
            gateway,
            dock_target,
            activation_radius_m=baseline.docking.approach_activation_radius_m,
            timeout_s=RTL_APPROACH_TIMEOUT_S,
        )

        publisher = LandingTargetPublisher(connection_string)
        live_stream_records = await _stream_live_projected_targets(
            gateway,
            publisher,
            dock_target,
            rate_hz=baseline.docking.landing_target_stream_rate_hz,
            duration_s=STREAM_DURATION_S,
        )
        after_stream_snapshot = await gateway.get_snapshot()
        after_stream_local_pose = await gateway.get_local_pose()
        await asyncio.sleep(2.0)

        sitl_log_path = _resolve_log_path("LIVE_PX4_SITL_LOG_PATH", "live_probe_*.log")
        bridge_log_path = _resolve_log_path("LIVE_PX4_BRIDGE_LOG_PATH", "live_probe_*_bridge.log")
        receiver_observation = {"count": 0, "first_match": {}}
        bridge_summary = {
            "gcs_host_to_px4_count": 0,
            "gcs_px4_to_host_count": 0,
        }
        if sitl_log_path is not None:
            sitl_log_text = sitl_log_path.read_text(encoding="utf-8", errors="replace")
            receiver_observation = parse_receiver_observation(sitl_log_text).to_dict()
        if bridge_log_path is not None:
            bridge_log_text = bridge_log_path.read_text(encoding="utf-8", errors="replace")
            bridge_summary = {
                "gcs_host_to_px4_count": count_bridge_direction(
                    bridge_log_text,
                    bridge_name="gcs",
                    direction="host->px4",
                ),
                "gcs_px4_to_host_count": count_bridge_direction(
                    bridge_log_text,
                    bridge_name="gcs",
                    direction="px4->host",
                ),
            }

        payload = {
            "system_address": system_address,
            "connect_timeout_s": connect_timeout_s,
            "mission_id": mission.mission_id,
            "waypoint_count": len(mission.waypoints),
            "dock_target": {
                "north_m": dock_target.north_m,
                "east_m": dock_target.east_m,
                "down_m": dock_target.down_m,
            },
            "landing_target_connection": {
                "endpoint": endpoint,
                "direct_px4_transport": direct_px4,
                "connection_string": connection_string,
                "stream_rate_hz": baseline.docking.landing_target_stream_rate_hz,
                "stream_duration_s": STREAM_DURATION_S,
            },
            "evidence_paths": {
                "sitl_log_path": str(sitl_log_path) if sitl_log_path is not None else None,
                "bridge_log_path": str(bridge_log_path) if bridge_log_path is not None else None,
            },
            "initial_snapshot": _snapshot_to_dict(initial_snapshot),
            "initial_local_pose": _local_pose_to_dict(initial_local_pose),
            "mission_entry_snapshot": _snapshot_to_dict(mission_entry_snapshot),
            "mission_entry_observations": mission_entry_observations,
            "departure_observations": departure_observations,
            "rtl_approach_window": {
                "activation_radius_m": baseline.docking.approach_activation_radius_m,
                "entry_local_pose": _local_pose_to_dict(approach_local_pose),
                "observations": rtl_approach_observations,
            },
            "live_stream": {
                "record_count": len(live_stream_records),
                "first_record": live_stream_records[0] if live_stream_records else {},
                "last_record": live_stream_records[-1] if live_stream_records else {},
                "records": live_stream_records,
            },
            "after_stream_snapshot": _snapshot_to_dict(after_stream_snapshot),
            "after_stream_local_pose": _local_pose_to_dict(after_stream_local_pose),
            "receiver_observation": receiver_observation,
            "bridge_summary": bridge_summary,
            "proof_status": (
                "consumed_from_live_telemetry_projection"
                if receiver_observation["count"] >= len(live_stream_records)
                else "streamed_without_full_receiver_match"
            ),
        }

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Live PX4 dock-approach validation written to: {OUTPUT_PATH}")
    finally:
        await gateway.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
