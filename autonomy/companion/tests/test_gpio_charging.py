from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.gpio_charging import ChargingConfig, GPIOChargingController


class GpioChargingTests(unittest.TestCase):
    def test_charging_controller_enables_charge_on_valid_mock_voltage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = GPIOChargingController(
                ChargingConfig(output_dir=Path(tmp), cycles=1, poll_interval_s=0.0)
            ).run()

        self.assertTrue(result["used_mock_gpio"])
        self.assertTrue(result["used_mock_ads"])
        self.assertTrue(result["decisions"][0]["charge_enabled"])
        self.assertEqual(result["final_pin_state"]["value"], 1)

    def test_charging_controller_blocks_out_of_range_battery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "SKYLINK_MOCK_CONTACT_VOLTAGE": "1.2",
                    "SKYLINK_MOCK_BATTERY_VOLTAGE": "20.5",
                    "SKYLINK_FORCE_MOCK_GPIO": "1",
                },
                clear=False,
            ):
                result = GPIOChargingController(
                    ChargingConfig(output_dir=Path(tmp), cycles=1, poll_interval_s=0.0)
                ).run()

        self.assertFalse(result["decisions"][0]["charge_enabled"])
        self.assertEqual(result["final_pin_state"]["value"], 0)


if __name__ == "__main__":
    unittest.main()

