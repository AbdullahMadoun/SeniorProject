from __future__ import annotations

from dataclasses import dataclass

from .models import Waypoint


@dataclass(frozen=True)
class GeofenceCircle:
    center: Waypoint
    radius_m: float


def build_home_geofence(home: Waypoint, radius_m: float) -> GeofenceCircle:
    if radius_m <= 0:
        raise ValueError("Geofence radius must be positive.")
    return GeofenceCircle(center=home, radius_m=radius_m)
