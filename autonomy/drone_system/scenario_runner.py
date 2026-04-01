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


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    action: str
    reasons: tuple[str, ...]
    final_mode: str
    details: tuple[str, ...]


class SafetyScenarioRunner:
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline
        self._engine = MissionSafetyEngine(baseline)

    def default_mission(self) -> MissionPlanRequest:
        return MissionPlanRequest(
            mission_id="baseline-scenario-mission",
            home=self._baseline.home,
            waypoints=(
                Waypoint(lat=24.689050, lon=50.174000, alt_m=25.0),
                Waypoint(lat=24.689120, lon=50.174160, alt_m=25.0),
            ),
            cruise_speed_mps=self._baseline.speed_band.nominal_mps,
        )

    async def run_all(self) -> list[ScenarioResult]:
        return [
            await self._run_nominal_ready_scenario(),
            await self._run_high_wind_abort_scenario(),
            await self._run_low_battery_rtl_scenario(),
        ]

    async def _prepare_gateway(self) -> tuple[InMemoryVehicleGateway, MissionPlanRequest]:
        mission = self.default_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)
        gateway = InMemoryVehicleGateway(self._baseline)
        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        return gateway, mission

    async def _run_nominal_ready_scenario(self) -> ScenarioResult:
        gateway, mission = await self._prepare_gateway()
        decision = await self._engine.assess_preflight_from_gateway(
            gateway,
            mission,
            wind_mps=self._baseline.safety.max_operating_wind_mps - 1.0,
        )
        snapshot = await gateway.get_snapshot()
        passed = decision.action in {SafetyAction.CONTINUE, SafetyAction.WARN}
        return ScenarioResult(
            name="nominal_preflight_ready",
            passed=passed,
            action=decision.action.value,
            reasons=tuple(reason.value for reason in decision.reasons),
            final_mode=snapshot.mode.value,
            details=decision.details,
        )

    async def _run_high_wind_abort_scenario(self) -> ScenarioResult:
        gateway, mission = await self._prepare_gateway()
        decision = await self._engine.assess_preflight_from_gateway(
            gateway,
            mission,
            wind_mps=self._baseline.safety.max_operating_wind_mps + 1.0,
        )
        snapshot = await gateway.get_snapshot()
        passed = decision.action == SafetyAction.ABORT_LAUNCH
        return ScenarioResult(
            name="high_wind_abort_launch",
            passed=passed,
            action=decision.action.value,
            reasons=tuple(reason.value for reason in decision.reasons),
            final_mode=snapshot.mode.value,
            details=decision.details,
        )

    async def _run_low_battery_rtl_scenario(self) -> ScenarioResult:
        gateway, _ = await self._prepare_gateway()
        await gateway.arm()
        await gateway.start_mission()
        gateway.snapshot = gateway.snapshot.__class__(
            connected=True,
            armed=True,
            in_air=True,
            mode=VehicleMode.MISSION,
            battery_percent=self._baseline.safety.battery_rtl_percent - 1.0,
            position=gateway.snapshot.position,
            mission_progress=gateway.snapshot.mission_progress,
        )
        decision = await self._engine.enforce_inflight_policy(
            gateway,
            wind_mps=self._baseline.safety.max_operating_wind_mps - 1.0,
        )
        snapshot = await gateway.get_snapshot()
        passed = decision.action == SafetyAction.RETURN_TO_LAUNCH and snapshot.mode == VehicleMode.RETURN_TO_LAUNCH
        return ScenarioResult(
            name="low_battery_rtl",
            passed=passed,
            action=decision.action.value,
            reasons=tuple(reason.value for reason in decision.reasons),
            final_mode=snapshot.mode.value,
            details=decision.details,
        )


def write_scenario_artifacts(output_dir: str | Path, results: list[ScenarioResult]) -> Path:
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
        "# Safety Scenario Summary",
        "",
        f"- scenario count: `{payload['scenario_count']}`",
        f"- passed count: `{payload['passed_count']}`",
        "",
        "| Scenario | Passed | Action | Final Mode | Reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        reasons = ", ".join(result.reasons) if result.reasons else "-"
        lines.append(
            f"| {result.name} | {'yes' if result.passed else 'no'} | "
            f"{result.action} | {result.final_mode} | {reasons} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def run_scenarios_to_directory(baseline: SystemBaseline, output_dir: str | Path) -> Path:
    runner = SafetyScenarioRunner(baseline)
    results = asyncio.run(runner.run_all())
    return write_scenario_artifacts(output_dir, results)
