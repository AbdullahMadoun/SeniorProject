from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import MissionProgress, VehicleMode, VehicleSnapshot, Waypoint
from autonomy.drone_system.safety_engine import MissionSafetyEngine, SafetyAction, SafetyReason
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway


class SafetyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()
        self.engine = MissionSafetyEngine(self.baseline)
        self.request = MissionPlanRequest(
            mission_id="safety-mission",
            home=self.baseline.home,
            waypoints=(
                Waypoint(lat=24.689050, lon=50.174000, alt_m=25.0),
                Waypoint(lat=24.689120, lon=50.174160, alt_m=25.0),
            ),
            cruise_speed_mps=5.0,
        )
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=False,
            in_air=False,
            mode=VehicleMode.HOLD,
            battery_percent=100.0,
            position=self.baseline.home,
            mission_progress=MissionProgress(),
        )

    def test_preflight_rejects_high_wind(self) -> None:
        decision = self.engine.assess_preflight(self.snapshot, self.request, wind_mps=8.0)
        self.assertEqual(decision.action, SafetyAction.ABORT_LAUNCH)
        self.assertIn(SafetyReason.WIND_LIMIT_EXCEEDED, decision.reasons)

    def test_preflight_warns_on_low_battery(self) -> None:
        snapshot = replace(self.snapshot, battery_percent=25.0)
        decision = self.engine.assess_preflight(snapshot, self.request, wind_mps=3.0)
        self.assertEqual(decision.action, SafetyAction.WARN)
        self.assertEqual(decision.reasons, (SafetyReason.BATTERY_WARN_THRESHOLD,))

    def test_inflight_returns_to_launch_at_rtl_threshold(self) -> None:
        snapshot = replace(self.snapshot, battery_percent=20.0, armed=True, in_air=True, mode=VehicleMode.MISSION)
        decision = self.engine.assess_inflight(snapshot, wind_mps=3.0)
        self.assertEqual(decision.action, SafetyAction.RETURN_TO_LAUNCH)
        self.assertEqual(decision.reasons, (SafetyReason.BATTERY_RTL_THRESHOLD,))

    def test_inflight_lands_immediately_at_emergency_threshold(self) -> None:
        snapshot = replace(self.snapshot, battery_percent=10.0, armed=True, in_air=True, mode=VehicleMode.MISSION)
        decision = self.engine.assess_inflight(snapshot, wind_mps=3.0)
        self.assertEqual(decision.action, SafetyAction.LAND_NOW)
        self.assertEqual(decision.reasons, (SafetyReason.BATTERY_EMERGENCY_THRESHOLD,))

    def test_enforce_inflight_policy_updates_gateway_mode(self) -> None:
        async def _run() -> None:
            gateway = InMemoryVehicleGateway(self.baseline)
            await gateway.connect()
            await gateway.upload_mission(self.request)
            await gateway.arm()
            await gateway.start_mission()
            gateway.snapshot = replace(
                gateway.snapshot,
                battery_percent=19.0,
                mode=VehicleMode.MISSION,
                in_air=True,
                armed=True,
            )

            decision = await self.engine.enforce_inflight_policy(gateway, wind_mps=3.0)
            snapshot = await gateway.get_snapshot()

            self.assertEqual(decision.action, SafetyAction.RETURN_TO_LAUNCH)
            self.assertEqual(snapshot.mode, VehicleMode.RETURN_TO_LAUNCH)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
