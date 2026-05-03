from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    alt_m: float


@dataclass(frozen=True)
class VehicleLocalPose:
    north_m: float
    east_m: float
    down_m: float
    yaw_deg: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0


class VehicleMode(str, Enum):
    DISCONNECTED = "disconnected"
    HOLD = "hold"
    MISSION = "mission"
    RETURN_TO_LAUNCH = "return_to_launch"
    LAND = "land"


@dataclass(frozen=True)
class MissionProgress:
    current: int = 0
    total: int = 0


@dataclass(frozen=True)
class VehicleSnapshot:
    connected: bool
    armed: bool
    in_air: bool
    mode: VehicleMode
    battery_percent: float | None = None
    position: Waypoint | None = None
    mission_progress: MissionProgress = MissionProgress()
