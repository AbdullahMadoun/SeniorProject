from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import SystemBaseline
from .geofence import build_home_geofence
from .mission_control import MissionPlanRequest
from .models import VehicleMode, Waypoint
from .safety_engine import MissionSafetyEngine, SafetyAction
from .vehicle_interface import InMemoryVehicleGateway
from .weather_gate import MissionWeatherGate, WeatherReading


@dataclass(frozen=True)
class WeatherScenarioResult:
    name: str
    passed: bool
    launch_allowed: bool
    mission_continue_allowed: bool
    dock_allowed: bool
    safety_action: str
    final_mode: str
    effective_wind_mps: float
    reasons: tuple[str, ...]
    details: tuple[str, ...]


class WeatherScenarioRunner:
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline
        self._engine = MissionSafetyEngine(baseline)
        self._weather_gate = MissionWeatherGate(baseline)

    def default_mission(self) -> MissionPlanRequest:
        return MissionPlanRequest(
            mission_id="weather-gated-scenario-mission",
            home=self._baseline.home,
            waypoints=(
                Waypoint(lat=26.307150, lon=50.145900, alt_m=25.0),
                Waypoint(lat=26.307220, lon=50.146060, alt_m=25.0),
            ),
            cruise_speed_mps=self._baseline.speed_band.nominal_mps,
        )

    async def run_all(self) -> list[WeatherScenarioResult]:
        return [
            await self._run_nominal_weather_ready(),
            await self._run_gust_abort_launch(),
            await self._run_inflight_wind_excursion_rtl(),
            await self._run_nominal_dock_weather_ready(),
        ]

    async def _prepare_gateway(self) -> tuple[InMemoryVehicleGateway, MissionPlanRequest]:
        mission = self.default_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)
        gateway = InMemoryVehicleGateway(self._baseline)
        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        return gateway, mission

    async def _run_nominal_weather_ready(self) -> WeatherScenarioResult:
        gateway, mission = await self._prepare_gateway()
        reading = WeatherReading(steady_wind_mps=3.0, gust_wind_mps=4.5, source="scenario_nominal")
        weather_decision = self._weather_gate.assess(reading)
        safety_decision = await self._engine.assess_preflight_from_gateway(
            gateway,
            mission,
            wind_mps=weather_decision.effective_wind_mps,
        )
        snapshot = await gateway.get_snapshot()
        passed = (
            weather_decision.launch_allowed
            and weather_decision.dock_allowed
            and safety_decision.action == SafetyAction.CONTINUE
        )
        return WeatherScenarioResult(
            name="nominal_weather_ready",
            passed=passed,
            launch_allowed=weather_decision.launch_allowed,
            mission_continue_allowed=weather_decision.mission_continue_allowed,
            dock_allowed=weather_decision.dock_allowed,
            safety_action=safety_decision.action.value,
            final_mode=snapshot.mode.value,
            effective_wind_mps=weather_decision.effective_wind_mps,
            reasons=tuple(reason.value for reason in weather_decision.reasons),
            details=weather_decision.details,
        )

    async def _run_gust_abort_launch(self) -> WeatherScenarioResult:
        gateway, mission = await self._prepare_gateway()
        reading = WeatherReading(steady_wind_mps=5.5, gust_wind_mps=8.2, source="scenario_gust_front")
        weather_decision = self._weather_gate.assess(reading)
        safety_decision = await self._engine.assess_preflight_from_gateway(
            gateway,
            mission,
            wind_mps=weather_decision.effective_wind_mps,
        )
        snapshot = await gateway.get_snapshot()
        passed = (
            not weather_decision.launch_allowed
            and not weather_decision.dock_allowed
            and safety_decision.action == SafetyAction.ABORT_LAUNCH
        )
        return WeatherScenarioResult(
            name="gust_abort_launch",
            passed=passed,
            launch_allowed=weather_decision.launch_allowed,
            mission_continue_allowed=weather_decision.mission_continue_allowed,
            dock_allowed=weather_decision.dock_allowed,
            safety_action=safety_decision.action.value,
            final_mode=snapshot.mode.value,
            effective_wind_mps=weather_decision.effective_wind_mps,
            reasons=tuple(reason.value for reason in safety_decision.reasons),
            details=safety_decision.details,
        )

    async def _run_inflight_wind_excursion_rtl(self) -> WeatherScenarioResult:
        gateway, _ = await self._prepare_gateway()
        await gateway.arm()
        await gateway.start_mission()
        reading = WeatherReading(steady_wind_mps=7.6, gust_wind_mps=8.0, source="scenario_wind_excursion")
        weather_decision = self._weather_gate.assess(reading)
        safety_decision = await self._engine.enforce_inflight_policy(
            gateway,
            wind_mps=weather_decision.effective_wind_mps,
        )
        snapshot = await gateway.get_snapshot()
        passed = (
            not weather_decision.mission_continue_allowed
            and safety_decision.action == SafetyAction.RETURN_TO_LAUNCH
            and snapshot.mode == VehicleMode.RETURN_TO_LAUNCH
        )
        return WeatherScenarioResult(
            name="inflight_wind_excursion_rtl",
            passed=passed,
            launch_allowed=weather_decision.launch_allowed,
            mission_continue_allowed=weather_decision.mission_continue_allowed,
            dock_allowed=weather_decision.dock_allowed,
            safety_action=safety_decision.action.value,
            final_mode=snapshot.mode.value,
            effective_wind_mps=weather_decision.effective_wind_mps,
            reasons=tuple(reason.value for reason in safety_decision.reasons),
            details=safety_decision.details,
        )

    async def _run_nominal_dock_weather_ready(self) -> WeatherScenarioResult:
        gateway, _ = await self._prepare_gateway()
        await gateway.arm()
        await gateway.start_mission()
        await gateway.return_to_launch()
        reading = WeatherReading(steady_wind_mps=4.0, gust_wind_mps=5.0, source="scenario_nominal_rtl")
        weather_decision = self._weather_gate.assess(reading)
        snapshot = await gateway.get_snapshot()
        passed = weather_decision.dock_allowed and snapshot.mode == VehicleMode.RETURN_TO_LAUNCH
        return WeatherScenarioResult(
            name="nominal_dock_weather_ready",
            passed=passed,
            launch_allowed=weather_decision.launch_allowed,
            mission_continue_allowed=weather_decision.mission_continue_allowed,
            dock_allowed=weather_decision.dock_allowed,
            safety_action=SafetyAction.CONTINUE.value,
            final_mode=snapshot.mode.value,
            effective_wind_mps=weather_decision.effective_wind_mps,
            reasons=tuple(reason.value for reason in weather_decision.reasons),
            details=weather_decision.details,
        )


def write_weather_scenario_artifacts(output_dir: str | Path, results: list[WeatherScenarioResult]) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    manifest_path = destination / "manifest.json"
    summary_path = destination / "summary.md"

    payload = {
        "scenario_count": len(results),
        "passed_count": sum(1 for result in results if result.passed),
        "results": [asdict(result) for result in results],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Weather Gate Scenario Summary",
        "",
        f"- scenario count: `{payload['scenario_count']}`",
        f"- passed count: `{payload['passed_count']}`",
        "",
        "| Scenario | Passed | Effective Wind (m/s) | Launch | Mission Continue | Dock | Safety Action | Final Mode |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.name} | {'yes' if result.passed else 'no'} | "
            f"{result.effective_wind_mps:.1f} | "
            f"{'yes' if result.launch_allowed else 'no'} | "
            f"{'yes' if result.mission_continue_allowed else 'no'} | "
            f"{'yes' if result.dock_allowed else 'no'} | "
            f"{result.safety_action} | {result.final_mode} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def run_weather_scenarios_to_directory(baseline: SystemBaseline, output_dir: str | Path) -> Path:
    runner = WeatherScenarioRunner(baseline)
    results = asyncio.run(runner.run_all())
    return write_weather_scenario_artifacts(output_dir, results)
