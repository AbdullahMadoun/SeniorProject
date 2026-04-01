from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .config import SystemBaseline
from .interactive_mission import InteractiveMissionSpec


@dataclass(frozen=True)
class Px4SimOverridePlan:
    float_params: dict[str, float]
    int_params: dict[str, int]
    wind_speed_mps: float
    wind_direction_deg: float
    gust_multiplier: float
    wind_vector_enu_mps: tuple[float, float, float]


def build_px4_sim_override_plan(
    spec: InteractiveMissionSpec,
    baseline: SystemBaseline,
) -> Px4SimOverridePlan:
    rtl_threshold_norm = max(0.05, min(0.5, spec.battery.rtl_battery_threshold_percent / 100.0))
    emergency_threshold_norm = max(0.05, min(rtl_threshold_norm - 0.02, rtl_threshold_norm))
    warning_threshold_norm = min(0.99, max(rtl_threshold_norm + 0.05, rtl_threshold_norm))
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
            "COM_LOW_BAT_ACT": 3,
        },
        wind_speed_mps=spec.environment.wind_speed_mps,
        wind_direction_deg=spec.environment.wind_direction_deg,
        gust_multiplier=spec.environment.gust_multiplier,
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
