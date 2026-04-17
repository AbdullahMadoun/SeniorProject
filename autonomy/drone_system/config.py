from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from .models import Waypoint


@dataclass(frozen=True)
class SpeedBand:
    min_mps: float
    nominal_mps: float
    max_mps: float


@dataclass(frozen=True)
class MissionLimits:
    max_radius_m: float
    max_altitude_m: float
    target_endurance_min: float
    validated_endurance_min: float
    max_processing_latency_min: float
    max_geotag_error_m: float
    max_area_m2: float
    max_dimension_m: float


@dataclass(frozen=True)
class SafetyThresholds:
    battery_warn_percent: float
    battery_rtl_percent: float
    battery_emergency_percent: float
    max_operating_wind_mps: float


@dataclass(frozen=True)
class DockingBaseline:
    charge_power_w: float
    landing_accuracy_target_m: float
    dock_center_north_m: float
    dock_center_east_m: float
    dock_center_down_m: float
    approach_activation_radius_m: float
    landing_target_stream_rate_hz: float
    precision_landing_strategy: str
    rtl_precision_land_mode: str


@dataclass(frozen=True)
class SystemBaseline:
    home: Waypoint
    speed_band: SpeedBand
    mission_limits: MissionLimits
    safety: SafetyThresholds
    docking: DockingBaseline


def default_system_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "system.toml"


def load_system_baseline(path: str | Path | None = None) -> SystemBaseline:
    config_path = Path(path) if path is not None else default_system_config_path()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    home = Waypoint(
        lat=float(raw["home"]["lat"]),
        lon=float(raw["home"]["lon"]),
        alt_m=float(raw["home"]["alt_m"]),
    )
    speed_band = SpeedBand(
        min_mps=float(raw["vehicle"]["cruise_speed_min_mps"]),
        nominal_mps=float(raw["vehicle"]["cruise_speed_nominal_mps"]),
        max_mps=float(raw["vehicle"]["cruise_speed_max_mps"]),
    )
    mission_limits = MissionLimits(
        max_radius_m=float(raw["mission"]["max_operating_radius_m"]),
        max_altitude_m=float(raw["mission"]["max_altitude_m"]),
        target_endurance_min=float(raw["mission"]["target_endurance_min"]),
        validated_endurance_min=float(raw["mission"]["validated_endurance_min"]),
        max_processing_latency_min=float(raw["mission"]["processing_latency_max_min"]),
        max_geotag_error_m=float(raw["mission"]["geotag_error_max_m"]),
        max_area_m2=float(raw["safety"]["max_mission_area_m2"]),
        max_dimension_m=float(raw["safety"]["max_mission_dimension_m"]),
    )
    safety = SafetyThresholds(
        battery_warn_percent=float(raw["safety"]["battery_warn_percent"]),
        battery_rtl_percent=float(raw["safety"]["battery_rtl_percent"]),
        battery_emergency_percent=float(raw["safety"]["battery_emergency_percent"]),
        max_operating_wind_mps=float(raw["weather"]["max_operating_wind_mps"]),
    )
    docking = DockingBaseline(
        charge_power_w=float(raw["docking"]["charge_power_w"]),
        landing_accuracy_target_m=float(raw["docking"]["landing_accuracy_target_m"]),
        dock_center_north_m=float(raw["docking"]["dock_center_north_m"]),
        dock_center_east_m=float(raw["docking"]["dock_center_east_m"]),
        dock_center_down_m=float(raw["docking"]["dock_center_down_m"]),
        approach_activation_radius_m=float(raw["docking"]["approach_activation_radius_m"]),
        landing_target_stream_rate_hz=float(raw["docking"]["landing_target_stream_rate_hz"]),
        precision_landing_strategy=str(raw["docking"]["precision_landing_strategy"]),
        rtl_precision_land_mode=str(raw["docking"]["rtl_precision_land_mode"]),
    )
    return SystemBaseline(
        home=home,
        speed_band=speed_band,
        mission_limits=mission_limits,
        safety=safety,
        docking=docking,
    )
