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
from autonomy.drone_system.weather_scenario_runner import WeatherScenarioRunner


class WeatherScenarioRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()

    def test_run_all_produces_expected_weather_scenarios(self) -> None:
        async def _run() -> None:
            runner = WeatherScenarioRunner(self.baseline)
            results = await runner.run_all()

            self.assertEqual(len(results), 4)
            result_map = {result.name: result for result in results}
            self.assertTrue(result_map["nominal_weather_ready"].passed)
            self.assertTrue(result_map["gust_abort_launch"].passed)
            self.assertEqual(result_map["gust_abort_launch"].safety_action, "abort_launch")
            self.assertTrue(result_map["inflight_wind_excursion_rtl"].passed)
            self.assertEqual(result_map["inflight_wind_excursion_rtl"].final_mode, "return_to_launch")
            self.assertTrue(result_map["nominal_dock_weather_ready"].dock_allowed)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
