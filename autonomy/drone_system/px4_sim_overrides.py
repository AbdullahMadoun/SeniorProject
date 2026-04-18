from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .config import SystemBaseline
from .interactive_mission import (
    InteractiveMissionSpec,
    LOW_BATTERY_ACTION_LAND,
    LOW_BATTERY_ACTION_RETURN,
    LOW_BATTERY_ACTION_WARNING,
)


@dataclass(frozen=True)
class Px4SimOverridePlan:
    float_params: dict[str, float]
    int_params: dict[str, int]
    wind_speed_mps: float
    wind_direction_deg: float
    gust_multiplier: float
    weather_profile_mode: str
    low_battery_action: str
    wind_vector_enu_mps: tuple[float, float, float]


def low_battery_action_to_px4(action: str) -> int:
    normalized = action.strip().lower()
    if normalized == LOW_BATTERY_ACTION_WARNING:
        return 0
    if normalized == LOW_BATTERY_ACTION_LAND:
        return 2
    if normalized == LOW_BATTERY_ACTION_RETURN:
        return 3
    raise ValueError(f"Unsupported low battery action: {action}")


def build_px4_sim_override_plan(
    spec: InteractiveMissionSpec,
    baseline: SystemBaseline,
) -> Px4SimOverridePlan:
    warning_threshold_norm = max(0.12, min(0.5, spec.battery.warn_battery_threshold_percent / 100.0))
    rtl_threshold_norm = max(0.05, min(0.5, spec.battery.rtl_battery_threshold_percent / 100.0))
    emergency_threshold_norm = max(0.03, min(0.5, spec.battery.emergency_battery_threshold_percent / 100.0))
    wind_vector_enu_mps = wind_direction_to_enu(
        speed_mps=spec.environment.wind_speed_mps,
        direction_deg=spec.environment.wind_direction_deg,
    )
    return Px4SimOverridePlan(
        float_params={
            "SIM_BAT_MIN_PCT": spec.battery.initial_battery_percent,
            "BAT_LOW_THR": warning_threshold_norm,
            "BAT_CRIT_THR": rtl_threshold_norm,
            "BAT_EMERGEN_THR": emergency_threshold_norm,
        },
        int_params={
            "COM_LOW_BAT_ACT": low_battery_action_to_px4(spec.battery.low_battery_action),
        },
        wind_speed_mps=spec.environment.wind_speed_mps,
        wind_direction_deg=spec.environment.wind_direction_deg,
        gust_multiplier=spec.environment.gust_multiplier,
        weather_profile_mode=spec.weather_profile_mode,
        low_battery_action=spec.battery.low_battery_action,
        wind_vector_enu_mps=wind_vector_enu_mps,
    )


def wind_direction_to_enu(*, speed_mps: float, direction_deg: float) -> tuple[float, float, float]:
    radians = math.radians(direction_deg)
    east_mps = speed_mps * math.sin(radians)
    north_mps = speed_mps * math.cos(radians)
    return (round(east_mps, 4), round(north_mps, 4), 0.0)


def plan_to_dict(plan: Px4SimOverridePlan) -> dict[str, Any]:
    payload = asdict(plan)
    payload["wind_vector_enu_mps"] = {
        "east_mps": plan.wind_vector_enu_mps[0],
        "north_mps": plan.wind_vector_enu_mps[1],
        "up_mps": plan.wind_vector_enu_mps[2],
    }
    return payload


def write_generated_gz_world(
    *,
    template_path: Path,
    output_dir: Path,
    world_name: str,
    wind_vector_enu_mps: tuple[float, float, float],
) -> Path:
    if not template_path.exists():
        fallback_path = template_path.with_name("default.sdf")
        if fallback_path.exists():
            template_path = fallback_path
        else:
            raise RuntimeError(f"Gazebo wind template not found: {template_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{world_name}.sdf"

    tree = ElementTree.parse(template_path)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise RuntimeError("Wind template world file does not contain a <world> element.")
    world.set("name", world_name)
    wind = world.find("wind")
    if wind is None:
        wind = ElementTree.SubElement(world, "wind")
    linear_velocity = wind.find("linear_velocity")
    if linear_velocity is None:
        linear_velocity = ElementTree.SubElement(wind, "linear_velocity")
    linear_velocity.text = f"{wind_vector_enu_mps[0]} {wind_vector_enu_mps[1]} {wind_vector_enu_mps[2]}"
    tree.write(output_path, encoding="utf-8", xml_declaration=False)
    return output_path
