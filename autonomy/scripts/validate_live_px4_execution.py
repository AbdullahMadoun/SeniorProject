from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.geometry import generate_lawnmower_pattern
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import Waypoint
from autonomy.drone_system.vehicle_interface import MavsdkVehicleGateway


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_execution_validation.json"
DEFAULT_SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
DEFAULT_CONNECT_TIMEOUT_S = 15.0


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


def _local_pose_to_dict(local_pose) -> dict[str, object]:
    return {
        "north_m": local_pose.north_m if local_pose else None,
        "east_m": local_pose.east_m if local_pose else None,
        "down_m": local_pose.down_m if local_pose else None,
        "yaw_deg": local_pose.yaw_deg if local_pose else None,
    }


async def main() -> None:
    baseline = load_system_baseline()
    system_address = os.environ.get("MAVSDK_SYSTEM_ADDRESS", DEFAULT_SYSTEM_ADDRESS)
    connect_timeout_s = float(
        os.environ.get("MAVSDK_CONNECT_TIMEOUT_S", str(DEFAULT_CONNECT_TIMEOUT_S))
    )
    gateway = MavsdkVehicleGateway(
        baseline,
        system_address=system_address,
        connect_timeout_s=connect_timeout_s,
    )
    print("stage=connect", flush=True)
    await gateway.connect()

    print("stage=initial_snapshot", flush=True)
    initial = await gateway.get_snapshot()
    initial_local_pose = await gateway.get_local_pose()
    if initial.position is None:
        raise RuntimeError("Live PX4 snapshot did not expose a position.")

    live_home = Waypoint(
        lat=initial.position.lat,
        lon=initial.position.lon,
        alt_m=max(initial.position.alt_m, 0.0),
    )
    mission = MissionPlanRequest(
        mission_id="live-execution-smoke",
        home=live_home,
        waypoints=tuple(generate_lawnmower_pattern(live_home, 20.0, 20.0, 10.0, 10.0)),
        cruise_speed_mps=baseline.speed_band.nominal_mps,
    )

    print("stage=upload_geofence", flush=True)
    await gateway.upload_geofence(build_home_geofence(live_home, baseline.mission_limits.max_radius_m))
    print("stage=upload_mission", flush=True)
    await gateway.upload_mission(mission)
    print("stage=arm", flush=True)
    await gateway.arm()
    print("stage=start_mission", flush=True)
    await gateway.start_mission()

    mission_snapshots: list[dict[str, object]] = []
    for tick in range(12):
        print(f"stage=mission_snapshot tick={tick}", flush=True)
        snapshot = await gateway.get_snapshot()
        local_pose = await gateway.get_local_pose()
        mission_snapshots.append(
            {
                "tick": tick,
                "snapshot": _snapshot_to_dict(snapshot),
                "local_pose": _local_pose_to_dict(local_pose),
            }
        )
        if snapshot.in_air and snapshot.mode.value == "mission":
            break
        await asyncio.sleep(2)

    print("stage=rtl", flush=True)
    await gateway.return_to_launch()
    await asyncio.sleep(3)
    print("stage=after_rtl_snapshot", flush=True)
    after_rtl = await gateway.get_snapshot()
    after_rtl_local_pose = await gateway.get_local_pose()

    payload = {
        "system_address": system_address,
        "connect_timeout_s": connect_timeout_s,
        "mission_id": mission.mission_id,
        "waypoint_count": len(mission.waypoints),
        "initial_snapshot": _snapshot_to_dict(initial),
        "initial_local_pose": _local_pose_to_dict(initial_local_pose),
        "mission_phase_snapshots": mission_snapshots,
        "after_rtl_snapshot": _snapshot_to_dict(after_rtl),
        "after_rtl_local_pose": _local_pose_to_dict(after_rtl_local_pose),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("stage=artifact_written", flush=True)
    print(f"Live PX4 execution validation written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
