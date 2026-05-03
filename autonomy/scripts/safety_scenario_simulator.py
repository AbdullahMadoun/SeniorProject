"""
SkyLink2 Safety Scenario Simulator
==================================
Demonstrates RTL and safety responses for battery and wind conditions.

Usage:
    python safety_scenario_simulator.py --scenario battery_rtl
    python safety_scenario_simulator.py --scenario wind_rtl
    python safety_scenario_simulator.py --scenario battery_emergency
    python safety_scenario_simulator.py --scenario high_wind_abort
    python safety_scenario_simulator.py --scenario battery_warn
    python safety_scenario_simulator.py --scenario all
    python safety_scenario_simulator.py --scenario battery_rtl --output results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import SystemBaseline, load_system_baseline
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import MissionProgress, VehicleMode, VehicleSnapshot, Waypoint
from autonomy.drone_system.safety_engine import MissionSafetyEngine, SafetyAction, SafetyReason
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class StateRecord:
    timestamp: str
    phase: str
    battery_percent: float | None
    wind_mps: float
    mode: str
    action: str | None
    reasons: tuple[str, ...]
    details: tuple[str, ...]


@dataclass
class ScenarioResult:
    scenario: str
    success: bool
    states: list[StateRecord]
    final_action: str
    final_reasons: tuple[str, ...]
    duration_s: float


class SafetyScenarioSimulator:
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline
        self._engine = MissionSafetyEngine(baseline)

    def _make_mission(self) -> MissionPlanRequest:
        home = self._baseline.home
        waypoints = (
            Waypoint(home.lat + 0.0001, home.lon + 0.0001, 20.0),
            Waypoint(home.lat + 0.0002, home.lon + 0.0001, 25.0),
            Waypoint(home.lat + 0.0002, home.lon + 0.0002, 20.0),
            Waypoint(home.lat + 0.0001, home.lon + 0.0002, 15.0),
        )
        return MissionPlanRequest(
            mission_id="SIM_MISSION_001",
            home=home,
            waypoints=waypoints,
            cruise_speed_mps=self._baseline.speed_band.nominal_mps,
            rtl_after_mission=True,
            capture_images=True,
        )

    def _stamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    async def _record(
        self,
        states: list[StateRecord],
        phase: str,
        gateway: InMemoryVehicleGateway,
        wind_mps: float,
        action: SafetyAction | None = None,
        reasons: tuple[SafetyReason, ...] = (),
        details: tuple[str, ...] = (),
    ) -> None:
        snapshot = await gateway.get_snapshot()
        states.append(StateRecord(
            timestamp=self._stamp(),
            phase=phase,
            battery_percent=snapshot.battery_percent,
            wind_mps=wind_mps,
            mode=snapshot.mode.value,
            action=action.value if action else None,
            reasons=tuple(r.value for r in reasons),
            details=details,
        ))

    async def _run_battery_rtl(self) -> ScenarioResult:
        scenario = "battery_rtl"
        logger.info("=" * 60)
        logger.info("SCENARIO: %s - Battery at 19%% triggers RTL during flight", scenario)
        logger.info("=" * 60)

        start = time.monotonic()
        states: list[StateRecord] = []
        gateway = InMemoryVehicleGateway(self._baseline)
        wind_mps = 3.0
        mission = self._make_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await self._record(states, "CONNECTED", gateway, wind_mps)
        logger.info("[CONNECTED] Gateway connected")

        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await self._record(states, "MISSION_UPLOADED", gateway, wind_mps)
        logger.info("[MISSION_UPLOADED] Mission uploaded (4 waypoints)")

        await gateway.arm()
        await self._record(states, "ARMED", gateway, wind_mps)
        logger.info("[ARMED] Vehicle armed")

        await gateway.start_mission()
        snap = await gateway.get_snapshot()
        gateway.snapshot = VehicleSnapshot(
            connected=snap.connected, armed=snap.armed, in_air=snap.in_air,
            mode=snap.mode, battery_percent=19.0, position=snap.position,
            mission_progress=snap.mission_progress,
        )
        await self._record(states, "IN_FLIGHT @ 19%%", gateway, wind_mps)
        logger.info("[IN_FLIGHT] Battery at 19%% - below RTL threshold (20%%)")

        decision = await self._engine.enforce_inflight_policy(gateway, wind_mps)
        await self._record(
            states, "RTL_TRIGGERED", gateway, wind_mps,
            action=decision.action, reasons=decision.reasons, details=decision.details,
        )
        logger.info(
            "[RTL_TRIGGERED] Action: %s | Reasons: %s | Details: %s",
            decision.action.value,
            [r.value for r in decision.reasons],
            list(decision.details),
        )

        await gateway.disconnect()
        await self._record(states, "DISCONNECTED", gateway, wind_mps)

        duration = time.monotonic() - start
        logger.info("[COMPLETE] Duration: %.2fs", duration)

        return ScenarioResult(
            scenario=scenario,
            success=decision.action == SafetyAction.RETURN_TO_LAUNCH,
            states=states,
            final_action=decision.action.value,
            final_reasons=tuple(r.value for r in decision.reasons),
            duration_s=duration,
        )

    async def _run_wind_rtl(self) -> ScenarioResult:
        scenario = "wind_rtl"
        logger.info("=" * 60)
        logger.info("SCENARIO: %s - Wind at 8.5 m/s triggers RTL during flight", scenario)
        logger.info("=" * 60)

        start = time.monotonic()
        states: list[StateRecord] = []
        gateway = InMemoryVehicleGateway(self._baseline)
        wind_mps = 8.5
        mission = self._make_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await self._record(states, "CONNECTED", gateway, wind_mps)
        logger.info("[CONNECTED] Gateway connected")

        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await self._record(states, "MISSION_UPLOADED", gateway, wind_mps)
        logger.info("[MISSION_UPLOADED] Mission uploaded")

        await gateway.arm()
        await self._record(states, "ARMED", gateway, wind_mps)
        logger.info("[ARMED] Vehicle armed")

        await gateway.start_mission()
        await self._record(states, "IN_FLIGHT @ 8.5 m/s WIND", gateway, wind_mps)
        logger.info("[IN_FLIGHT] Wind at 8.5 m/s - exceeds limit (7.0 m/s)")

        decision = await self._engine.enforce_inflight_policy(gateway, wind_mps)
        await self._record(
            states, "RTL_TRIGGERED", gateway, wind_mps,
            action=decision.action, reasons=decision.reasons, details=decision.details,
        )
        logger.info(
            "[RTL_TRIGGERED] Action: %s | Reasons: %s | Details: %s",
            decision.action.value,
            [r.value for r in decision.reasons],
            list(decision.details),
        )

        await gateway.disconnect()
        await self._record(states, "DISCONNECTED", gateway, wind_mps)

        duration = time.monotonic() - start
        logger.info("[COMPLETE] Duration: %.2fs", duration)

        return ScenarioResult(
            scenario=scenario,
            success=decision.action == SafetyAction.RETURN_TO_LAUNCH,
            states=states,
            final_action=decision.action.value,
            final_reasons=tuple(r.value for r in decision.reasons),
            duration_s=duration,
        )

    async def _run_battery_emergency(self) -> ScenarioResult:
        scenario = "battery_emergency"
        logger.info("=" * 60)
        logger.info("SCENARIO: %s - Battery at 8%% triggers immediate LAND_NOW", scenario)
        logger.info("=" * 60)

        start = time.monotonic()
        states: list[StateRecord] = []
        gateway = InMemoryVehicleGateway(self._baseline)
        wind_mps = 3.0
        mission = self._make_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await self._record(states, "CONNECTED", gateway, wind_mps)
        logger.info("[CONNECTED] Gateway connected")

        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await self._record(states, "MISSION_UPLOADED", gateway, wind_mps)
        logger.info("[MISSION_UPLOADED] Mission uploaded")

        await gateway.arm()
        await self._record(states, "ARMED", gateway, wind_mps)
        logger.info("[ARMED] Vehicle armed")

        await gateway.start_mission()
        snap = await gateway.get_snapshot()
        gateway.snapshot = VehicleSnapshot(
            connected=snap.connected, armed=snap.armed, in_air=snap.in_air,
            mode=snap.mode, battery_percent=8.0, position=snap.position,
            mission_progress=snap.mission_progress,
        )
        await self._record(states, "IN_FLIGHT @ 8%%", gateway, wind_mps)
        logger.info("[IN_FLIGHT] Battery at 8%% - below emergency threshold (10%%)")

        decision = await self._engine.enforce_inflight_policy(gateway, wind_mps)
        await self._record(
            states, "LAND_NOW_TRIGGERED", gateway, wind_mps,
            action=decision.action, reasons=decision.reasons, details=decision.details,
        )
        logger.info(
            "[LAND_NOW_TRIGGERED] Action: %s | Reasons: %s | Details: %s",
            decision.action.value,
            [r.value for r in decision.reasons],
            list(decision.details),
        )

        await gateway.disconnect()
        await self._record(states, "DISCONNECTED", gateway, wind_mps)

        duration = time.monotonic() - start
        logger.info("[COMPLETE] Duration: %.2fs", duration)

        return ScenarioResult(
            scenario=scenario,
            success=decision.action == SafetyAction.LAND_NOW,
            states=states,
            final_action=decision.action.value,
            final_reasons=tuple(r.value for r in decision.reasons),
            duration_s=duration,
        )

    async def _run_high_wind_abort(self) -> ScenarioResult:
        scenario = "high_wind_abort"
        logger.info("=" * 60)
        logger.info("SCENARIO: %s - Wind at 9 m/s aborts preflight launch", scenario)
        logger.info("=" * 60)

        start = time.monotonic()
        states: list[StateRecord] = []
        gateway = InMemoryVehicleGateway(self._baseline)
        wind_mps = 9.0
        mission = self._make_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await self._record(states, "CONNECTED", gateway, wind_mps)
        logger.info("[CONNECTED] Gateway connected")

        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await self._record(states, "MISSION_UPLOADED", gateway, wind_mps)
        logger.info("[MISSION_UPLOADED] Mission uploaded")

        await gateway.arm()
        await self._record(states, "ARMED", gateway, wind_mps)
        logger.info("[ARMED] Vehicle armed")

        decision = await self._engine.assess_preflight_from_gateway(gateway, mission, wind_mps)
        await self._record(
            states, "PREFLIGHT_CHECK", gateway, wind_mps,
            action=decision.action, reasons=decision.reasons, details=decision.details,
        )
        logger.info(
            "[PREFLIGHT_CHECK] Action: %s | Reasons: %s | Details: %s",
            decision.action.value,
            [r.value for r in decision.reasons],
            list(decision.details),
        )

        await gateway.disarm()
        await gateway.disconnect()
        await self._record(states, "DISCONNECTED", gateway, wind_mps)

        duration = time.monotonic() - start
        logger.info("[COMPLETE] Duration: %.2fs", duration)

        return ScenarioResult(
            scenario=scenario,
            success=decision.action == SafetyAction.ABORT_LAUNCH,
            states=states,
            final_action=decision.action.value,
            final_reasons=tuple(r.value for r in decision.reasons),
            duration_s=duration,
        )

    async def _run_battery_warn(self) -> ScenarioResult:
        scenario = "battery_warn"
        logger.info("=" * 60)
        logger.info("SCENARIO: %s - Battery at 25%% triggers warning (continues mission)", scenario)
        logger.info("=" * 60)

        start = time.monotonic()
        states: list[StateRecord] = []
        gateway = InMemoryVehicleGateway(self._baseline)
        wind_mps = 3.0
        mission = self._make_mission()
        geofence = build_home_geofence(self._baseline.home, self._baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await self._record(states, "CONNECTED", gateway, wind_mps)
        logger.info("[CONNECTED] Gateway connected")

        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await self._record(states, "MISSION_UPLOADED", gateway, wind_mps)
        logger.info("[MISSION_UPLOADED] Mission uploaded")

        await gateway.arm()
        await self._record(states, "ARMED", gateway, wind_mps)
        logger.info("[ARMED] Vehicle armed")

        decision_preflight = await self._engine.assess_preflight_from_gateway(gateway, mission, wind_mps)
        await self._record(
            states, "PREFLIGHT_CHECK", gateway, wind_mps,
            action=decision_preflight.action, reasons=decision_preflight.reasons, details=decision_preflight.details,
        )
        logger.info(
            "[PREFLIGHT_CHECK] Action: %s | Reasons: %s | Details: %s",
            decision_preflight.action.value,
            [r.value for r in decision_preflight.reasons],
            list(decision_preflight.details),
        )

        await gateway.start_mission()
        snap = await gateway.get_snapshot()
        gateway.snapshot = VehicleSnapshot(
            connected=snap.connected, armed=snap.armed, in_air=snap.in_air,
            mode=snap.mode, battery_percent=25.0, position=snap.position,
            mission_progress=snap.mission_progress,
        )
        await self._record(states, "IN_FLIGHT @ 25%%", gateway, wind_mps)
        logger.info("[IN_FLIGHT] Battery at 25%% - below warn threshold (30%%)")

        decision_inflight = await self._engine.enforce_inflight_policy(gateway, wind_mps)
        await self._record(
            states, "INFLIGHT_CHECK", gateway, wind_mps,
            action=decision_inflight.action, reasons=decision_inflight.reasons, details=decision_inflight.details,
        )
        logger.info(
            "[INFLIGHT_CHECK] Action: %s | Reasons: %s | Details: %s",
            decision_inflight.action.value,
            [r.value for r in decision_inflight.reasons],
            list(decision_inflight.details),
        )

        await gateway.disconnect()
        await self._record(states, "DISCONNECTED", gateway, wind_mps)

        duration = time.monotonic() - start
        logger.info("[COMPLETE] Duration: %.2fs", duration)

        return ScenarioResult(
            scenario=scenario,
            success=decision_inflight.action == SafetyAction.WARN,
            states=states,
            final_action=decision_inflight.action.value,
            final_reasons=tuple(r.value for r in decision_inflight.reasons),
            duration_s=duration,
        )

    async def run_scenario(self, scenario: str) -> ScenarioResult:
        if scenario == "battery_rtl":
            return await self._run_battery_rtl()
        elif scenario == "wind_rtl":
            return await self._run_wind_rtl()
        elif scenario == "battery_emergency":
            return await self._run_battery_emergency()
        elif scenario == "high_wind_abort":
            return await self._run_high_wind_abort()
        elif scenario == "battery_warn":
            return await self._run_battery_warn()
        else:
            raise ValueError(f"Unknown scenario: {scenario}")

    async def run_all(self) -> list[ScenarioResult]:
        scenarios = [
            "battery_rtl",
            "wind_rtl",
            "battery_emergency",
            "high_wind_abort",
            "battery_warn",
        ]
        results: list[ScenarioResult] = []
        for s in scenarios:
            result = await self.run_scenario(s)
            results.append(result)
        return results


def _result_to_dict(result: ScenarioResult) -> dict:
    return {
        "scenario": result.scenario,
        "success": result.success,
        "duration_s": round(result.duration_s, 3),
        "final_action": result.final_action,
        "final_reasons": list(result.final_reasons),
        "states": [
            {
                "timestamp": s.timestamp,
                "phase": s.phase,
                "battery_percent": s.battery_percent,
                "wind_mps": s.wind_mps,
                "mode": s.mode,
                "action": s.action,
                "reasons": list(s.reasons),
                "details": list(s.details),
            }
            for s in result.states
        ],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="SkyLink2 Safety Scenario Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Scenarios:
  battery_rtl        Battery at 19%% triggers RTL during flight
  wind_rtl           Wind at 8.5 m/s triggers RTL during flight
  battery_emergency  Battery at 8%% triggers immediate LAND_NOW
  high_wind_abort    Wind at 9 m/s aborts preflight launch
  battery_warn       Battery at 25%% triggers warning (continues mission)
  all                Run all scenarios
        """,
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["battery_rtl", "wind_rtl", "battery_emergency", "high_wind_abort", "battery_warn", "all"],
        help="Scenario to run (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (optional)",
    )
    args = parser.parse_args()

    baseline = load_system_baseline()
    simulator = SafetyScenarioSimulator(baseline)

    logger.info("SkyLink2 Safety Scenario Simulator")
    logger.info("Battery thresholds - Warn: %.0f%% | RTL: %.0f%% | Emergency: %.0f%%",
                 baseline.safety.battery_warn_percent,
                 baseline.safety.battery_rtl_percent,
                 baseline.safety.battery_emergency_percent)
    logger.info("Max operating wind: %.1f m/s", baseline.safety.max_operating_wind_mps)
    logger.info("")

    try:
        if args.scenario == "all":
            results = await simulator.run_all()
        else:
            results = [await simulator.run_scenario(args.scenario)]
    except Exception as exc:
        logger.error("Scenario failed: %s", exc)
        raise

    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for r in results:
        status = "PASS" if r.success else "FAIL"
        logger.info("  [%s] %s - %s (%.2fs)",
                     status, r.scenario, r.final_action, r.duration_s)

    if args.output:
        output_data = [_result_to_dict(r) for r in results]
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output_data, indent=2))
        logger.info("")
        logger.info("Results written to: %s", output_path)


if __name__ == "__main__":
    asyncio.run(main())
