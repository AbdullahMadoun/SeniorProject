from __future__ import annotations

from dataclasses import dataclass

from .config import SystemBaseline
from .geometry import latlon_to_local_m
from .models import Waypoint


@dataclass(frozen=True)
class MissionPlanRequest:
    mission_id: str
    home: Waypoint
    waypoints: tuple[Waypoint, ...]
    cruise_speed_mps: float
    rtl_after_mission: bool = True
    capture_images: bool = True


def _distance_from_home_m(home: Waypoint, waypoint: Waypoint) -> float:
    north, east = latlon_to_local_m(waypoint.lat, waypoint.lon, home.lat, home.lon)
    return (north * north + east * east) ** 0.5


def validate_mission_request(request: MissionPlanRequest, baseline: SystemBaseline) -> None:
    if not request.mission_id.strip():
        raise ValueError("Mission id is required.")
    if len(request.waypoints) < 2:
        raise ValueError("At least two waypoints are required.")

    if request.cruise_speed_mps < baseline.speed_band.min_mps:
        raise ValueError(
            f"Cruise speed {request.cruise_speed_mps:.1f} m/s is below "
            f"{baseline.speed_band.min_mps:.1f} m/s."
        )
    if request.cruise_speed_mps > baseline.speed_band.max_mps:
        raise ValueError(
            f"Cruise speed {request.cruise_speed_mps:.1f} m/s exceeds "
            f"{baseline.speed_band.max_mps:.1f} m/s."
        )

    for waypoint in request.waypoints:
        if waypoint.alt_m > baseline.mission_limits.max_altitude_m:
            raise ValueError(
                f"Waypoint altitude {waypoint.alt_m:.1f} m exceeds "
                f"{baseline.mission_limits.max_altitude_m:.1f} m."
            )
        radius_m = _distance_from_home_m(request.home, waypoint)
        if radius_m > baseline.mission_limits.max_radius_m:
            raise ValueError(
                f"Waypoint radius {radius_m:.1f} m exceeds "
                f"{baseline.mission_limits.max_radius_m:.1f} m."
            )
