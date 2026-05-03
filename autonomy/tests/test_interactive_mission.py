from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.interactive_mission import (
    BatteryOverrides,
    InteractiveMissionSpec,
    LocalMissionWaypoint,
    LOW_BATTERY_ACTION_WARNING,
    WEATHER_PROFILE_MODE_FULL_TRIP,
    WeatherProfilePoint,
    default_weather_profile,
    runtime_baseline_for_spec,
    validate_interactive_mission,
    weather_reading_at,
)


class InteractiveMissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()

    def test_validate_interactive_mission_accepts_nominal_local_waypoints(self) -> None:
        spec = InteractiveMissionSpec(
            mission_id="planner-test",
            cruise_speed_mps=self.baseline.speed_band.nominal_mps,
            waypoints=(
                LocalMissionWaypoint(north_m=0.0, east_m=0.0, altitude_m=10.0),
                LocalMissionWaypoint(north_m=18.0, east_m=12.0, altitude_m=12.0),
            ),
        )

        validate_interactive_mission(spec, self.baseline)

    def test_validate_interactive_mission_rejects_radius_overflow(self) -> None:
        spec = InteractiveMissionSpec(
            mission_id="planner-test",
            cruise_speed_mps=self.baseline.speed_band.nominal_mps,
            waypoints=(
                LocalMissionWaypoint(north_m=0.0, east_m=0.0, altitude_m=10.0),
                LocalMissionWaypoint(north_m=130.0, east_m=0.0, altitude_m=12.0),
            ),
        )

        with self.assertRaises(ValueError) as context:
            validate_interactive_mission(spec, self.baseline)

        self.assertIn("Waypoint radius", str(context.exception))

    def test_weather_reading_at_steps_profile_over_time(self) -> None:
        profile = (
            WeatherProfilePoint(t_s=0.0, steady_wind_mps=3.0, gust_wind_mps=4.0),
            WeatherProfilePoint(t_s=10.0, steady_wind_mps=7.4, gust_wind_mps=8.2),
        )

        early = weather_reading_at(profile, 4.0)
        late = weather_reading_at(profile, 14.0)

        self.assertEqual(early.steady_wind_mps, 3.0)
        self.assertEqual(early.gust_wind_mps, 4.0)
        self.assertEqual(late.steady_wind_mps, 7.4)
        self.assertEqual(late.gust_wind_mps, 8.2)

    def test_default_weather_profile_holds_violation_window_during_live_mission(self) -> None:
        profile = default_weather_profile(wind_speed_mps=3.4, gust_multiplier=1.34)

        self.assertEqual([point.t_s for point in profile], [0.0, 5.0, 12.0, 36.0])
        trigger = weather_reading_at(profile, 18.0)
        recovery = weather_reading_at(profile, 40.0)

        self.assertGreater(trigger.gust_wind_mps or 0.0, self.baseline.safety.max_operating_wind_mps)
        self.assertLessEqual(recovery.gust_wind_mps or 0.0, self.baseline.safety.max_operating_wind_mps)

    def test_full_trip_weather_profile_stays_below_abort_limit(self) -> None:
        profile = default_weather_profile(
            wind_speed_mps=3.4,
            gust_multiplier=1.34,
            profile_mode=WEATHER_PROFILE_MODE_FULL_TRIP,
        )

        self.assertTrue(all((point.gust_wind_mps or 0.0) <= self.baseline.safety.max_operating_wind_mps for point in profile))

    def test_validate_interactive_mission_rejects_invalid_battery_threshold_order(self) -> None:
        spec = InteractiveMissionSpec(
            mission_id="planner-test",
            cruise_speed_mps=self.baseline.speed_band.nominal_mps,
            waypoints=(
                LocalMissionWaypoint(north_m=0.0, east_m=0.0, altitude_m=10.0),
                LocalMissionWaypoint(north_m=18.0, east_m=12.0, altitude_m=12.0),
            ),
            battery=BatteryOverrides(
                initial_battery_percent=100.0,
                warn_battery_threshold_percent=20.0,
                rtl_battery_threshold_percent=25.0,
                emergency_battery_threshold_percent=10.0,
                low_battery_action=LOW_BATTERY_ACTION_WARNING,
            ),
        )

        with self.assertRaises(ValueError) as context:
            validate_interactive_mission(spec, self.baseline)

        self.assertIn("Warn battery threshold", str(context.exception))

    def test_runtime_baseline_for_spec_uses_battery_overrides(self) -> None:
        spec = InteractiveMissionSpec(
            mission_id="planner-test",
            cruise_speed_mps=self.baseline.speed_band.nominal_mps,
            waypoints=(
                LocalMissionWaypoint(north_m=0.0, east_m=0.0, altitude_m=10.0),
                LocalMissionWaypoint(north_m=18.0, east_m=12.0, altitude_m=12.0),
            ),
        )

        runtime_baseline = runtime_baseline_for_spec(self.baseline, spec)

        self.assertEqual(runtime_baseline.safety.battery_warn_percent, spec.battery.warn_battery_threshold_percent)
        self.assertEqual(runtime_baseline.safety.battery_rtl_percent, spec.battery.rtl_battery_threshold_percent)
        self.assertEqual(runtime_baseline.safety.battery_emergency_percent, spec.battery.emergency_battery_threshold_percent)


if __name__ == "__main__":
    unittest.main()
