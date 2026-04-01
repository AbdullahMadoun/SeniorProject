from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.mission_control import MissionPlanRequest, validate_mission_request
from autonomy.drone_system.models import VehicleMode, Waypoint
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway, MavsdkVehicleGateway


class VehicleInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()
        self.request = MissionPlanRequest(
            mission_id="nominal-mission",
            home=self.baseline.home,
            waypoints=(
                Waypoint(lat=24.689050, lon=50.174000, alt_m=25.0),
                Waypoint(lat=24.689120, lon=50.174160, alt_m=25.0),
            ),
            cruise_speed_mps=5.0,
        )

    def test_validate_mission_request_accepts_nominal_mission(self) -> None:
        validate_mission_request(self.request, self.baseline)

    def test_validate_mission_request_rejects_speed_above_limit(self) -> None:
        request = MissionPlanRequest(
            mission_id="fast-mission",
            home=self.baseline.home,
            waypoints=self.request.waypoints,
            cruise_speed_mps=8.0,
        )
        with self.assertRaises(ValueError):
            validate_mission_request(request, self.baseline)

    def test_validate_mission_request_rejects_waypoint_outside_radius(self) -> None:
        request = MissionPlanRequest(
            mission_id="far-mission",
            home=self.baseline.home,
            waypoints=(
                Waypoint(lat=24.690500, lon=50.174000, alt_m=25.0),
                Waypoint(lat=24.690700, lon=50.174100, alt_m=25.0),
            ),
            cruise_speed_mps=5.0,
        )
        with self.assertRaises(ValueError):
            validate_mission_request(request, self.baseline)

    def test_in_memory_vehicle_gateway_executes_nominal_command_flow(self) -> None:
        async def _run() -> None:
            gateway = InMemoryVehicleGateway(self.baseline)
            await gateway.connect()
            await gateway.upload_mission(self.request)
            await gateway.arm()
            await gateway.start_mission()
            await gateway.advance_to_waypoint(2)
            local_pose = await gateway.get_local_pose()
            self.assertIsNotNone(local_pose)
            assert local_pose is not None
            self.assertGreater(local_pose.north_m, 0.0)
            self.assertGreater(local_pose.east_m, 0.0)
            self.assertAlmostEqual(local_pose.down_m, -25.0, places=1)
            await gateway.return_to_launch()
            await gateway.land()

            snapshot = await gateway.get_snapshot()
            self.assertTrue(snapshot.connected)
            self.assertFalse(snapshot.armed)
            self.assertFalse(snapshot.in_air)
            self.assertEqual(snapshot.mode, VehicleMode.LAND)
            self.assertEqual(snapshot.mission_progress.current, 2)
            self.assertEqual(snapshot.mission_progress.total, 2)

        asyncio.run(_run())

    def test_mavsdk_gateway_normalizes_fractional_battery_percent(self) -> None:
        self.assertEqual(MavsdkVehicleGateway._normalize_battery_percent(0.42), 42.0)

    def test_mavsdk_gateway_preserves_whole_number_battery_percent(self) -> None:
        self.assertEqual(MavsdkVehicleGateway._normalize_battery_percent(100.0), 100.0)

    def test_mavsdk_gateway_disconnect_stops_embedded_server(self) -> None:
        class FakeDrone:
            def __init__(self) -> None:
                self.stopped = False

            def _stop_mavsdk_server(self) -> None:
                self.stopped = True

        async def _run() -> None:
            gateway = MavsdkVehicleGateway(self.baseline)
            fake = FakeDrone()
            gateway._drone = fake
            await gateway.disconnect()
            self.assertTrue(fake.stopped)
            self.assertIsNone(gateway._drone)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
