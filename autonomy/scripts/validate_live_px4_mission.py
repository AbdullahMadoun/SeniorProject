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
from autonomy.drone_system.geometry import (
    generate_lawnmower_pattern,
    latlon_to_local_m,
    local_m_to_latlon,
    validate_mission_area,
)
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import Waypoint
from autonomy.drone_system.vehicle_interface import MavsdkVehicleGateway


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_mission_validation.json"
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


def _waypoints_local_to_list(waypoints: tuple[Waypoint, ...], home: Waypoint) -> list[dict[str, float]]:
    payload: list[dict[str, float]] = []
    for index, waypoint in enumerate(waypoints):
        north_m, east_m = latlon_to_local_m(
            waypoint.lat,
            waypoint.lon,
            home.lat,
            home.lon,
        )
        payload.append(
            {
                "index": index,
                "north_m": north_m,
                "east_m": east_m,
                "altitude_m": waypoint.alt_m,
            }
        )
    return payload


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
    await gateway.connect()

    before = await gateway.get_snapshot()
    before_local_pose = await gateway.get_local_pose()
    if before.position is None:
        raise RuntimeError("Live PX4 snapshot did not expose a position.")

    live_home = Waypoint(
        lat=before.position.lat,
        lon=before.position.lon,
        alt_m=max(before.position.alt_m, 0.0),
    )
    geofence = build_home_geofence(live_home, baseline.mission_limits.max_radius_m)
    survey_width_m = 20.0
    survey_height_m = 20.0
    survey_boundary = tuple(
        Waypoint(lat=lat, lon=lon, alt_m=0.0)
        for lat, lon in (
            local_m_to_latlon(0.0, 0.0, live_home.lat, live_home.lon),
            local_m_to_latlon(0.0, survey_width_m, live_home.lat, live_home.lon),
            local_m_to_latlon(survey_height_m, survey_width_m, live_home.lat, live_home.lon),
            local_m_to_latlon(survey_height_m, 0.0, live_home.lat, live_home.lon),
        )
    )
    waypoints = tuple(
        generate_lawnmower_pattern(
            home=live_home,
            width_m=survey_width_m,
            height_m=survey_height_m,
            row_spacing_m=10.0,
            altitude_m=10.0,
        )
    )
    area = validate_mission_area(
        survey_boundary,
        max_area_m2=baseline.mission_limits.max_area_m2,
        max_dimension_m=baseline.mission_limits.max_dimension_m,
    )
    request = MissionPlanRequest(
        mission_id="live-sitl-smoke",
        home=live_home,
        waypoints=waypoints,
        cruise_speed_mps=baseline.speed_band.nominal_mps,
        rtl_after_mission=True,
    )

    await gateway.upload_geofence(geofence)
    await gateway.upload_mission(request)
    after = await gateway.get_snapshot()
    after_local_pose = await gateway.get_local_pose()

    payload = {
        "system_address": system_address,
        "connect_timeout_s": connect_timeout_s,
        "geofence": {
            "center": {
                "lat": geofence.center.lat,
                "lon": geofence.center.lon,
                "alt_m": geofence.center.alt_m,
            },
            "radius_m": geofence.radius_m,
        },
        "mission": {
            "mission_id": request.mission_id,
            "waypoint_count": len(request.waypoints),
            "cruise_speed_mps": request.cruise_speed_mps,
            "area_m2": area.area_m2,
            "north_span_m": area.north_span_m,
            "east_span_m": area.east_span_m,
            "waypoints_local": _waypoints_local_to_list(request.waypoints, live_home),
        },
        "before_upload": _snapshot_to_dict(before),
        "before_upload_local_pose": _local_pose_to_dict(before_local_pose),
        "after_upload": _snapshot_to_dict(after),
        "after_upload_local_pose": _local_pose_to_dict(after_local_pose),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Live PX4 mission validation written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
