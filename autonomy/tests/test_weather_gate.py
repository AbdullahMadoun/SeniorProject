from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.safety_engine import SafetyReason
from autonomy.drone_system.weather_gate import MissionWeatherGate, WeatherReading


class WeatherGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()
        self.gate = MissionWeatherGate(self.baseline)

    def test_assess_allows_nominal_steady_and_gust(self) -> None:
        decision = self.gate.assess(WeatherReading(steady_wind_mps=3.0, gust_wind_mps=5.5))

        self.assertTrue(decision.launch_allowed)
        self.assertTrue(decision.mission_continue_allowed)
        self.assertTrue(decision.dock_allowed)
        self.assertEqual(decision.effective_wind_mps, 5.5)
        self.assertEqual(decision.reasons, ())

    def test_assess_rejects_gust_over_limit(self) -> None:
        decision = self.gate.assess(WeatherReading(steady_wind_mps=5.0, gust_wind_mps=8.1))

        self.assertFalse(decision.launch_allowed)
        self.assertFalse(decision.mission_continue_allowed)
        self.assertFalse(decision.dock_allowed)
        self.assertEqual(decision.reasons, (SafetyReason.WIND_LIMIT_EXCEEDED,))


if __name__ == "__main__":
    unittest.main()
