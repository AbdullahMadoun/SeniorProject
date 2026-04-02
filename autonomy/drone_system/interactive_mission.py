from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

from .config import SystemBaseline
from .geometry import local_m_to_latlon, validate_mission_area
from .mission_control import MissionPlanRequest, validate_mission_request
from .models import Waypoint
from .weather_gate import WeatherReading


@dataclass(frozen=True)
class LocalMissionWaypoint:
    north_m: float
    east_m: float
    altitude_m: float


@dataclass(frozen=True)
class WeatherProfilePoint:
    t_s: float
    steady_wind_mps: float
    gust_wind_mps: float | None = None


@dataclass(frozen=True)
class EnvironmentOverrides:
    wind_speed_mps: float
    wind_direction_deg: float
    gust_multiplier: float


WEATHER_PROFILE_MODE_PROOF = "proof"
WEATHER_PROFILE_MODE_FULL_TRIP = "full_trip"
SUPPORTED_WEATHER_PROFILE_MODES = {
    WEATHER_PROFILE_MODE_PROOF,
    WEATHER_PROFILE_MODE_FULL_TRIP,
}

LOW_BATTERY_ACTION_WARNING = "warning"
LOW_BATTERY_ACTION_LAND = "land"
LOW_BATTERY_ACTION_RETURN = "return"
SUPPORTED_LOW_BATTERY_ACTIONS = {
    LOW_BATTERY_ACTION_WARNING,
    LOW_BATTERY_ACTION_LAND,
    LOW_BATTERY_ACTION_RETURN,
}


@dataclass(frozen=True)
class BatteryOverrides:
    initial_battery_percent: float
    warn_battery_threshold_percent: float
    rtl_battery_threshold_percent: float
    emergency_battery_threshold_percent: float
    low_battery_action: str


@dataclass(frozen=True)
class InteractiveMissionSpec:
    mission_id: str
    waypoints: tuple[LocalMissionWaypoint, ...]
    cruise_speed_mps: float
    rtl_after_mission: bool = True
    capture_images: bool = False
    weather_profile: tuple[WeatherProfilePoint, ...] = ()
    weather_profile_mode: str = WEATHER_PROFILE_MODE_PROOF
    environment: EnvironmentOverrides = EnvironmentOverrides(
        wind_speed_mps=3.2,
        wind_direction_deg=45.0,
        gust_multiplier=1.31,
    )
    battery: BatteryOverrides = BatteryOverrides(
        initial_battery_percent=100.0,
        warn_battery_threshold_percent=25.0,
        rtl_battery_threshold_percent=20.0,
        emergency_battery_threshold_percent=18.0,
        low_battery_action=LOW_BATTERY_ACTION_RETURN,
    )


def default_environment_overrides() -> EnvironmentOverrides:
    return EnvironmentOverrides(
        wind_speed_mps=3.2,
        wind_direction_deg=45.0,
        gust_multiplier=1.31,
    )


def default_battery_overrides() -> BatteryOverrides:
    return BatteryOverrides(
        initial_battery_percent=100.0,
        warn_battery_threshold_percent=25.0,
        rtl_battery_threshold_percent=20.0,
        emergency_battery_threshold_percent=18.0,
        low_battery_action=LOW_BATTERY_ACTION_RETURN,
    )


def default_weather_profile(
    *,
    wind_speed_mps: float | None = None,
    gust_multiplier: float | None = None,
    profile_mode: str = WEATHER_PROFILE_MODE_PROOF,
) -> tuple[WeatherProfilePoint, ...]:
    environment = default_environment_overrides()
    base_wind_mps = float(wind_speed_mps if wind_speed_mps is not None else environment.wind_speed_mps)
    gust_scale = float(gust_multiplier if gust_multiplier is not None else environment.gust_multiplier)

    def _gust(steady_wind_mps: float) -> float:
        return round(max(steady_wind_mps, steady_wind_mps * gust_scale), 1)

    if profile_mode == WEATHER_PROFILE_MODE_FULL_TRIP:
        safe_peak_wind_mps = min(max(base_wind_mps + 0.8, base_wind_mps), 5.8)
        safe_recovery_wind_mps = min(max(base_wind_mps + 0.4, base_wind_mps), 5.0)

        def _safe_gust(steady_wind_mps: float) -> float:
            return round(min(max(steady_wind_mps, steady_wind_mps * gust_scale), 6.6), 1)

        return (
            WeatherProfilePoint(
                t_s=0.0,
                steady_wind_mps=round(base_wind_mps, 1),
                gust_wind_mps=_safe_gust(base_wind_mps),
            ),
            WeatherProfilePoint(
                t_s=8.0,
                steady_wind_mps=round(min(base_wind_mps + 0.6, safe_peak_wind_mps), 1),
                gust_wind_mps=_safe_gust(min(base_wind_mps + 0.6, safe_peak_wind_mps)),
            ),
            WeatherProfilePoint(
                t_s=18.0,
                steady_wind_mps=round(safe_peak_wind_mps, 1),
                gust_wind_mps=_safe_gust(safe_peak_wind_mps),
            ),
            WeatherProfilePoint(
                t_s=36.0,
                steady_wind_mps=round(safe_recovery_wind_mps, 1),
                gust_wind_mps=_safe_gust(safe_recovery_wind_mps),
            ),
        )

    trigger_wind_mps = max(base_wind_mps + 3.2, 7.8)
    recovery_wind_mps = min(max(base_wind_mps + 1.0, 4.2), 5.2)
    return (
        WeatherProfilePoint(t_s=0.0, steady_wind_mps=round(base_wind_mps, 1), gust_wind_mps=_gust(base_wind_mps)),
        WeatherProfilePoint(
            t_s=5.0,
            steady_wind_mps=round(base_wind_mps + 0.8, 1),
            gust_wind_mps=_gust(base_wind_mps + 0.8),
        ),
        WeatherProfilePoint(
            t_s=12.0,
            steady_wind_mps=round(trigger_wind_mps, 1),
            gust_wind_mps=_gust(trigger_wind_mps),
        ),
        WeatherProfilePoint(
            t_s=36.0,
            steady_wind_mps=round(recovery_wind_mps, 1),
            gust_wind_mps=_gust(recovery_wind_mps),
        ),
    )


def interactive_mission_spec_to_dict(spec: InteractiveMissionSpec) -> dict[str, Any]:
    return {
        "mission_id": spec.mission_id,
        "cruise_speed_mps": spec.cruise_speed_mps,
        "rtl_after_mission": spec.rtl_after_mission,
        "capture_images": spec.capture_images,
        "weather_profile_mode": spec.weather_profile_mode,
        "waypoints": [
            {
                "north_m": waypoint.north_m,
                "east_m": waypoint.east_m,
                "altitude_m": waypoint.altitude_m,
            }
            for waypoint in spec.waypoints
        ],
        "weather_profile": [
            {
                "t_s": point.t_s,
                "steady_wind_mps": point.steady_wind_mps,
                "gust_wind_mps": point.gust_wind_mps,
            }
            for point in spec.weather_profile
        ],
        "environment": {
            "wind_speed_mps": spec.environment.wind_speed_mps,
            "wind_direction_deg": spec.environment.wind_direction_deg,
            "gust_multiplier": spec.environment.gust_multiplier,
        },
        "battery": {
            "initial_battery_percent": spec.battery.initial_battery_percent,
            "warn_battery_threshold_percent": spec.battery.warn_battery_threshold_percent,
            "rtl_battery_threshold_percent": spec.battery.rtl_battery_threshold_percent,
            "emergency_battery_threshold_percent": spec.battery.emergency_battery_threshold_percent,
            "low_battery_action": spec.battery.low_battery_action,
        },
    }


def interactive_mission_spec_from_dict(payload: dict[str, Any], baseline: SystemBaseline) -> InteractiveMissionSpec:
    raw_waypoints = payload.get("waypoints")
    if not isinstance(raw_waypoints, list):
        raise ValueError("Waypoints must be provided as a list.")
    waypoints: list[LocalMissionWaypoint] = []
    for raw_waypoint in raw_waypoints:
        if not isinstance(raw_waypoint, dict):
            raise ValueError("Each waypoint must be an object.")
        waypoints.append(
            LocalMissionWaypoint(
                north_m=float(raw_waypoint["north_m"]),
                east_m=float(raw_waypoint["east_m"]),
                altitude_m=float(raw_waypoint["altitude_m"]),
            )
        )

    raw_environment = payload.get("environment")
    if not isinstance(raw_environment, dict):
        raw_environment = {}
    default_environment = default_environment_overrides()
    environment = EnvironmentOverrides(
        wind_speed_mps=float(raw_environment.get("wind_speed_mps", default_environment.wind_speed_mps)),
        wind_direction_deg=float(raw_environment.get("wind_direction_deg", default_environment.wind_direction_deg)),
        gust_multiplier=float(raw_environment.get("gust_multiplier", default_environment.gust_multiplier)),
    )

    raw_battery = payload.get("battery")
    if not isinstance(raw_battery, dict):
        raw_battery = {}
    default_battery = default_battery_overrides()
    battery = BatteryOverrides(
        initial_battery_percent=float(
            raw_battery.get("initial_battery_percent", default_battery.initial_battery_percent)
        ),
        warn_battery_threshold_percent=float(
            raw_battery.get(
                "warn_battery_threshold_percent",
                default_battery.warn_battery_threshold_percent,
            )
        ),
        rtl_battery_threshold_percent=float(
            raw_battery.get(
                "rtl_battery_threshold_percent",
                default_battery.rtl_battery_threshold_percent,
            )
        ),
        emergency_battery_threshold_percent=float(
            raw_battery.get(
                "emergency_battery_threshold_percent",
                default_battery.emergency_battery_threshold_percent,
            )
        ),
        low_battery_action=str(
            raw_battery.get(
                "low_battery_action",
                default_battery.low_battery_action,
            )
        ).strip()
        or default_battery.low_battery_action,
    )

    raw_profile = payload.get("weather_profile")
    weather_profile: list[WeatherProfilePoint] = []
    if isinstance(raw_profile, list):
        for raw_point in raw_profile:
            if not isinstance(raw_point, dict):
                raise ValueError("Each weather profile point must be an object.")
            weather_profile.append(
                WeatherProfilePoint(
                    t_s=float(raw_point["t_s"]),
                    steady_wind_mps=float(raw_point["steady_wind_mps"]),
                    gust_wind_mps=(
                        float(raw_point["gust_wind_mps"])
                        if raw_point.get("gust_wind_mps") is not None
                        else None
                    ),
                )
            )

    cruise_speed_mps = float(payload.get("cruise_speed_mps", baseline.speed_band.nominal_mps))
    mission_id = str(payload.get("mission_id", "interactive-mission")).strip() or "interactive-mission"
    rtl_after_mission = bool(payload.get("rtl_after_mission", True))
    capture_images = bool(payload.get("capture_images", False))
    weather_profile_mode = (
        str(payload.get("weather_profile_mode", WEATHER_PROFILE_MODE_PROOF)).strip()
        or WEATHER_PROFILE_MODE_PROOF
    )
    return InteractiveMissionSpec(
        mission_id=mission_id,
        waypoints=tuple(waypoints),
        cruise_speed_mps=cruise_speed_mps,
        rtl_after_mission=rtl_after_mission,
        capture_images=capture_images,
        weather_profile_mode=weather_profile_mode,
        weather_profile=tuple(weather_profile)
        if weather_profile
        else default_weather_profile(
            wind_speed_mps=environment.wind_speed_mps,
            gust_multiplier=environment.gust_multiplier,
            profile_mode=weather_profile_mode,
        ),
        environment=environment,
        battery=battery,
    )


def build_waypoints_from_local(
    local_waypoints: tuple[LocalMissionWaypoint, ...],
    *,
    home: Waypoint,
) -> tuple[Waypoint, ...]:
    waypoints: list[Waypoint] = []
    for waypoint in local_waypoints:
        lat, lon = local_m_to_latlon(
            waypoint.north_m,
            waypoint.east_m,
            home.lat,
            home.lon,
        )
        waypoints.append(
            Waypoint(
                lat=lat,
                lon=lon,
                alt_m=waypoint.altitude_m,
            )
        )
    return tuple(waypoints)


def build_mission_request(
    spec: InteractiveMissionSpec,
    *,
    home: Waypoint,
) -> MissionPlanRequest:
    return MissionPlanRequest(
        mission_id=spec.mission_id,
        home=home,
        waypoints=build_waypoints_from_local(spec.waypoints, home=home),
        cruise_speed_mps=spec.cruise_speed_mps,
        rtl_after_mission=spec.rtl_after_mission,
        capture_images=spec.capture_images,
    )


def validate_interactive_mission(spec: InteractiveMissionSpec, baseline: SystemBaseline) -> None:
    request = build_mission_request(spec, home=baseline.home)
    validate_mission_request(request, baseline)

    if len(request.waypoints) >= 3:
        validate_mission_area(
            request.waypoints,
            max_area_m2=baseline.mission_limits.max_area_m2,
            max_dimension_m=baseline.mission_limits.max_dimension_m,
        )

    if spec.environment.wind_speed_mps < 0.0:
        raise ValueError("Wind speed must be non-negative.")
    if not 0.0 <= spec.environment.wind_direction_deg < 360.0:
        raise ValueError("Wind direction must be in [0, 360) degrees.")
    if spec.environment.gust_multiplier < 1.0:
        raise ValueError("Gust multiplier must be at least 1.0.")
    if spec.weather_profile_mode not in SUPPORTED_WEATHER_PROFILE_MODES:
        raise ValueError(
            f"Weather profile mode must be one of {sorted(SUPPORTED_WEATHER_PROFILE_MODES)}."
        )
    if not 0.0 < spec.battery.initial_battery_percent <= 100.0:
        raise ValueError("Initial battery percent must be in (0, 100].")
    if not 12.0 <= spec.battery.warn_battery_threshold_percent <= 50.0:
        raise ValueError("Warn battery threshold percent must be in [12, 50].")
    if not 5.0 <= spec.battery.rtl_battery_threshold_percent <= 50.0:
        raise ValueError("RTL battery threshold percent must be in [5, 50].")
    if not 3.0 <= spec.battery.emergency_battery_threshold_percent <= 50.0:
        raise ValueError("Emergency battery threshold percent must be in [3, 50].")
    if spec.battery.low_battery_action not in SUPPORTED_LOW_BATTERY_ACTIONS:
        raise ValueError(
            f"Low battery action must be one of {sorted(SUPPORTED_LOW_BATTERY_ACTIONS)}."
        )
    if spec.battery.initial_battery_percent <= spec.battery.warn_battery_threshold_percent:
        raise ValueError("Initial battery percent must be greater than the warn battery threshold.")
    if spec.battery.warn_battery_threshold_percent <= spec.battery.rtl_battery_threshold_percent:
        raise ValueError("Warn battery threshold must be greater than the RTL battery threshold.")
    if spec.battery.rtl_battery_threshold_percent <= spec.battery.emergency_battery_threshold_percent:
        raise ValueError("RTL battery threshold must be greater than the emergency battery threshold.")


def validate_local_waypoint(waypoint: LocalMissionWaypoint, baseline: SystemBaseline) -> None:
    radius_m = math.hypot(waypoint.north_m, waypoint.east_m)
    if waypoint.altitude_m > baseline.mission_limits.max_altitude_m:
        raise ValueError(
            f"Waypoint altitude {waypoint.altitude_m:.1f} m exceeds "
            f"{baseline.mission_limits.max_altitude_m:.1f} m."
        )
    if radius_m > baseline.mission_limits.max_radius_m:
        raise ValueError(
            f"Waypoint radius {radius_m:.1f} m exceeds "
            f"{baseline.mission_limits.max_radius_m:.1f} m."
        )


def weather_reading_at(
    profile: tuple[WeatherProfilePoint, ...],
    elapsed_s: float,
) -> WeatherReading:
    if not profile:
        default = default_weather_profile()[0]
        return WeatherReading(
            steady_wind_mps=default.steady_wind_mps,
            gust_wind_mps=default.gust_wind_mps,
            source="default_profile",
        )

    ordered = sorted(profile, key=lambda point: point.t_s)
    current = ordered[0]
    for point in ordered:
        if point.t_s <= elapsed_s:
            current = point
        else:
            break
    return WeatherReading(
        steady_wind_mps=current.steady_wind_mps,
        gust_wind_mps=current.gust_wind_mps,
        source=f"profile@{current.t_s:.1f}s",
    )


def runtime_baseline_for_spec(
    baseline: SystemBaseline,
    spec: InteractiveMissionSpec,
) -> SystemBaseline:
    return replace(
        baseline,
        safety=replace(
            baseline.safety,
            battery_warn_percent=spec.battery.warn_battery_threshold_percent,
            battery_rtl_percent=spec.battery.rtl_battery_threshold_percent,
            battery_emergency_percent=spec.battery.emergency_battery_threshold_percent,
        ),
    )
