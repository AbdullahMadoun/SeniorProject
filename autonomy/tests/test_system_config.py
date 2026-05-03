from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline


class SystemConfigTests(unittest.TestCase):
    def test_load_system_baseline(self) -> None:
        baseline = load_system_baseline()
        self.assertEqual(baseline.home.lat, 26.307114)
        self.assertEqual(baseline.mission_limits.max_radius_m, 100.0)
        self.assertEqual(baseline.speed_band.max_mps, 7.0)
        self.assertEqual(baseline.safety.battery_rtl_percent, 20.0)
        self.assertEqual(baseline.docking.landing_accuracy_target_m, 0.4)
        self.assertEqual(baseline.docking.dock_center_north_m, 0.0)
        self.assertEqual(baseline.docking.approach_activation_radius_m, 12.0)
        self.assertEqual(baseline.docking.landing_target_stream_rate_hz, 5.0)


if __name__ == "__main__":
    unittest.main()
