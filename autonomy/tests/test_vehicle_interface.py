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
                Waypoint(lat=26.307150, lon=50.145900, alt_m=25.0),
                Waypoint(lat=26.307220, lon=50.146060, alt_m=25.0),
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
                Waypoint(lat=26.308500, lon=50.145900, alt_m=25.0),
                Waypoint(lat=26.308700, lon=50.146100, alt_m=25.0),
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

    def test_mavsdk_gateway_returns_empty_snapshot_when_telemetry_is_unavailable(self) -> None:
        class FakeTelemetry:
            def position(self):
                return self._never_stream()

            def battery(self):
                return self._never_stream()

            def armed(self):
                return self._never_stream()

            def in_air(self):
                return self._never_stream()

            def flight_mode(self):
                return self._never_stream()

            def position_velocity_ned(self):
                return self._never_stream()

            def attitude_euler(self):
                return self._never_stream()

            def gps_info(self):
                return self._never_stream()

            async def _never_stream(self):
                await asyncio.sleep(60.0)
                if False:
                    yield None

        class FakeMission:
            def mission_progress(self):
                return self._never_stream()

            async def _never_stream(self):
                await asyncio.sleep(60.0)
                if False:
                    yield None

        class FakeDrone:
            telemetry = FakeTelemetry()
            mission = FakeMission()

        async def _run() -> None:
            gateway = MavsdkVehicleGateway(self.baseline)
            gateway._drone = FakeDrone()
            snapshot = await gateway.get_snapshot()
            local_pose = await gateway.get_local_pose()
            gps_info = await gateway.get_gps_info()
            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.mode, VehicleMode.DISCONNECTED)
            self.assertIsNone(local_pose)
            self.assertEqual(gps_info, {})
            with self.assertRaises(RuntimeError):
                await gateway.wait_for_live_position(timeout_s=0.2, poll_interval_s=0.05)

        asyncio.run(_run())

    def test_read_once_or_default_honors_timeout(self) -> None:
        async def _never_stream():
            await asyncio.sleep(60.0)
            if False:
                yield None

        async def _run() -> None:
            from autonomy.drone_system.vehicle_interface import TelemetryStreamClosed

            gateway = MavsdkVehicleGateway(self.baseline)
            with self.assertRaises(TelemetryStreamClosed):
                await gateway._read_once_or_default(_never_stream(), timeout_s=0.05)

        asyncio.run(_run())

    def test_mavsdk_gateway_degrades_safely_on_unexpected_telemetry_error(self) -> None:
        async def _run() -> None:
            gateway = MavsdkVehicleGateway(self.baseline)

            class FakeTelemetry:
                def position(self):
                    return self._broken_stream()

                def battery(self):
                    return self._broken_stream()

                def armed(self):
                    return self._broken_stream()

                def in_air(self):
                    return self._broken_stream()

                def flight_mode(self):
                    return self._broken_stream()

                def position_velocity_ned(self):
                    return self._broken_stream()

                def attitude_euler(self):
                    return self._broken_stream()

                def gps_info(self):
                    return self._broken_stream()

                async def _broken_stream(self):
                    raise RuntimeError("Simulated telemetry fault")
                    if False:
                        yield None

            class FakeMission:
                def mission_progress(self):
                    return self._broken_stream()

                async def _broken_stream(self):
                    raise RuntimeError("Simulated telemetry fault")
                    if False:
                        yield None

            class FakeDrone:
                telemetry = FakeTelemetry()
                mission = FakeMission()

            gateway._drone = FakeDrone()
            gateway._start_telemetry_monitors()
            await asyncio.sleep(0.05)

            snapshot = await gateway.get_snapshot()
            local_pose = await gateway.get_local_pose()
            gps_info = await gateway.get_gps_info()

            self.assertFalse(snapshot.connected)
            self.assertEqual(snapshot.mode, VehicleMode.DISCONNECTED)
            self.assertIsNone(local_pose)
            self.assertEqual(gps_info, {})
            await gateway.disconnect()

        asyncio.run(_run())

    def test_mavsdk_gateway_uses_background_telemetry_cache(self) -> None:
        class Position:
            latitude_deg = 26.30710
            longitude_deg = 50.14590
            relative_altitude_m = 11.5
            absolute_altitude_m = 17.2

        class Battery:
            remaining_percent = 0.62

        class PositionNed:
            north_m = 4.0
            east_m = -2.0
            down_m = -11.5

        class VelocityNed:
            north_m_s = 0.0
            east_m_s = 0.0
            down_m_s = 0.0

        class PositionVelocityNed:
            position = PositionNed()
            velocity = VelocityNed()

        class AttitudeEuler:
            yaw_deg = 15.0
            roll_deg = -1.0
            pitch_deg = 2.0

        class GpsInfo:
            num_satellites = 13
            fix_type = "FIX_3D"

        class MissionProgressItem:
            current = 1
            total = 3

        class FakeTelemetry:
            def __init__(self, stop_event: asyncio.Event) -> None:
                self._stop_event = stop_event

            async def _stream(self, item):
                yield item
                await self._stop_event.wait()

            def position(self):
                return self._stream(Position())

            def battery(self):
                return self._stream(Battery())

            def armed(self):
                return self._stream(True)

            def in_air(self):
                return self._stream(True)

            def flight_mode(self):
                return self._stream("MISSION")

            def position_velocity_ned(self):
                return self._stream(PositionVelocityNed())

            def attitude_euler(self):
                return self._stream(AttitudeEuler())

            def gps_info(self):
                return self._stream(GpsInfo())

        class FakeMission:
            def __init__(self, stop_event: asyncio.Event) -> None:
                self._stop_event = stop_event

            async def _stream(self, item):
                yield item
                await self._stop_event.wait()

            def mission_progress(self):
                return self._stream(MissionProgressItem())

        class FakeDrone:
            def __init__(self, stop_event: asyncio.Event) -> None:
                self.telemetry = FakeTelemetry(stop_event)
                self.mission = FakeMission(stop_event)

        async def _run() -> None:
            stop_event = asyncio.Event()
            gateway = MavsdkVehicleGateway(self.baseline)
            gateway._drone = FakeDrone(stop_event)
            gateway._start_telemetry_monitors()
            await asyncio.sleep(0.05)

            snapshot = await gateway.get_snapshot()
            local_pose = await gateway.get_local_pose()
            gps_info = await gateway.get_gps_info()

            self.assertTrue(snapshot.connected)
            self.assertTrue(snapshot.armed)
            self.assertTrue(snapshot.in_air)
            self.assertEqual(snapshot.mode, VehicleMode.MISSION)
            self.assertAlmostEqual(snapshot.battery_percent or 0.0, 62.0)
            self.assertIsNotNone(snapshot.position)
            self.assertEqual(snapshot.mission_progress.current, 1)
            self.assertEqual(snapshot.mission_progress.total, 3)
            self.assertIsNotNone(local_pose)
            assert local_pose is not None
            self.assertAlmostEqual(local_pose.north_m, 4.0)
            self.assertAlmostEqual(local_pose.east_m, -2.0)
            self.assertAlmostEqual(local_pose.down_m, -11.5)
            self.assertEqual(gps_info["num_satellites"], 13)
            self.assertEqual(gps_info["fix_type"], "fix_3d")

            stop_event.set()
            await gateway.disconnect()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
