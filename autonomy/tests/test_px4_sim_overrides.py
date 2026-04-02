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
)
from autonomy.drone_system.px4_sim_overrides import build_px4_sim_override_plan


class Px4SimOverridesTests(unittest.TestCase):
    def test_build_override_plan_uses_explicit_battery_thresholds_and_modes(self) -> None:
        baseline = load_system_baseline()
        spec = InteractiveMissionSpec(
            mission_id="override-test",
            cruise_speed_mps=baseline.speed_band.nominal_mps,
            waypoints=(
                LocalMissionWaypoint(north_m=0.0, east_m=0.0, altitude_m=10.0),
                LocalMissionWaypoint(north_m=20.0, east_m=15.0, altitude_m=10.0),
            ),
            weather_profile_mode=WEATHER_PROFILE_MODE_FULL_TRIP,
            battery=BatteryOverrides(
                initial_battery_percent=96.0,
                warn_battery_threshold_percent=28.0,
                rtl_battery_threshold_percent=17.0,
                emergency_battery_threshold_percent=9.0,
                low_battery_action=LOW_BATTERY_ACTION_WARNING,
            ),
        )

        plan = build_px4_sim_override_plan(spec, baseline)

        self.assertEqual(plan.float_params["SIM_BAT_MIN_PCT"], 96.0)
        self.assertAlmostEqual(plan.float_params["BAT_LOW_THR"], 0.28)
        self.assertAlmostEqual(plan.float_params["BAT_CRIT_THR"], 0.17)
        self.assertAlmostEqual(plan.float_params["BAT_EMERGEN_THR"], 0.09)
        self.assertEqual(plan.int_params["COM_LOW_BAT_ACT"], 0)
        self.assertEqual(plan.weather_profile_mode, WEATHER_PROFILE_MODE_FULL_TRIP)
        self.assertEqual(plan.low_battery_action, LOW_BATTERY_ACTION_WARNING)


if __name__ == "__main__":
    unittest.main()
