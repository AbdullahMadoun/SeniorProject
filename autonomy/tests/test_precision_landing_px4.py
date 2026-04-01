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
from autonomy.drone_system.precision_landing import PrecisionLandingTuning
from autonomy.drone_system.precision_landing_px4 import (
    apply_px4_precision_landing_profile,
    build_px4_precision_landing_profile,
)


class FakeParamPlugin:
    def __init__(self) -> None:
        self.values: dict[str, int | float] = {}

    async def set_param_int(self, name: str, value: int) -> None:
        self.values[name] = int(value)

    async def get_param_int(self, name: str) -> int:
        return int(self.values[name])

    async def set_param_float(self, name: str, value: float) -> None:
        self.values[name] = float(value)

    async def get_param_float(self, name: str) -> float:
        return float(self.values[name])


class PrecisionLandingPx4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()

    def test_build_px4_precision_landing_profile_matches_baseline(self) -> None:
        profile = build_px4_precision_landing_profile(self.baseline, PrecisionLandingTuning())
        values = {setting.name: setting.value for setting in profile}

        self.assertEqual(values["RTL_PLD_MD"], 2)
        self.assertEqual(values["LTEST_MODE"], 1)
        self.assertEqual(values["PLD_HACC_RAD"], self.baseline.docking.landing_accuracy_target_m)
        self.assertEqual(values["PLD_BTOUT"], 2.0)
        self.assertEqual(values["PLD_FAPPR_ALT"], 1.2)
        self.assertEqual(values["PLD_MAX_SRCH"], 3)

    def test_apply_px4_precision_landing_profile_reads_back_values(self) -> None:
        async def _run() -> None:
            plugin = FakeParamPlugin()
            profile = build_px4_precision_landing_profile(self.baseline)
            applied = await apply_px4_precision_landing_profile(plugin, profile)

            self.assertEqual(len(applied), len(profile))
            self.assertEqual(plugin.values["RTL_PLD_MD"], 2)
            self.assertAlmostEqual(float(plugin.values["PLD_HACC_RAD"]), 0.4, places=6)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
