from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .models import Waypoint


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class AreaValidationResult:
    area_m2: float
    north_span_m: float
    east_span_m: float


def latlon_to_local_m(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    north = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    east = (
        math.radians(lon - ref_lon)
        * EARTH_RADIUS_M
        * math.cos(math.radians((lat + ref_lat) / 2.0))
    )
    return north, east


def local_m_to_latlon(north_m: float, east_m: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    lat = ref_lat + math.degrees(north_m / EARTH_RADIUS_M)
    lon = ref_lon + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(ref_lat))))
    return lat, lon


def _shoelace_area(points_xy: list[tuple[float, float]]) -> float:
    area = 0.0
    for idx, (x1, y1) in enumerate(points_xy):
        x2, y2 = points_xy[(idx + 1) % len(points_xy)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) * 0.5


def validate_mission_area(
    waypoints: Iterable[Waypoint],
    max_area_m2: float,
    max_dimension_m: float,
) -> AreaValidationResult:
    points = list(waypoints)
    if len(points) < 3:
        raise ValueError("At least three waypoints are required for area validation.")

    ref_lat = sum(point.lat for point in points) / len(points)
    ref_lon = sum(point.lon for point in points) / len(points)
    local_points = [latlon_to_local_m(point.lat, point.lon, ref_lat, ref_lon) for point in points]

    north_values = [north for north, _ in local_points]
    east_values = [east for _, east in local_points]
    north_span = max(north_values) - min(north_values)
    east_span = max(east_values) - min(east_values)
    area_m2 = _shoelace_area(local_points)

    if area_m2 > max_area_m2:
        raise ValueError(f"Mission area {area_m2:.1f} m^2 exceeds {max_area_m2:.1f} m^2.")
    if north_span > max_dimension_m or east_span > max_dimension_m:
        raise ValueError(
            f"Mission dimensions {north_span:.1f}m x {east_span:.1f}m exceed {max_dimension_m:.1f}m."
        )

    return AreaValidationResult(area_m2=area_m2, north_span_m=north_span, east_span_m=east_span)


def generate_lawnmower_pattern(
    home: Waypoint,
    width_m: float,
    height_m: float,
    row_spacing_m: float,
    altitude_m: float,
) -> list[Waypoint]:
    if width_m <= 0 or height_m <= 0 or row_spacing_m <= 0:
        raise ValueError("Survey dimensions and row spacing must be positive.")

    points: list[Waypoint] = []
    direction_east = True
    north = 0.0
    while north <= height_m + 1e-6:
        start_east = 0.0 if direction_east else width_m
        end_east = width_m if direction_east else 0.0
        for east in (start_east, end_east):
            lat, lon = local_m_to_latlon(north, east, home.lat, home.lon)
            points.append(Waypoint(lat=lat, lon=lon, alt_m=altitude_m))
        north += row_spacing_m
        direction_east = not direction_east
    return points
