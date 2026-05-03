from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = AUTONOMY_ROOT / "config" / "system.toml"


class BaselineConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with CONFIG_PATH.open("rb") as handle:
            cls.config = tomllib.load(handle)

    def test_report_driven_limits_are_frozen(self) -> None:
        mission = self.config["mission"]
        vehicle = self.config["vehicle"]
        safety = self.config["safety"]
        weather = self.config["weather"]

        self.assertEqual(mission["max_operating_radius_m"], 100.0)
        self.assertEqual(mission["target_endurance_min"], 20.0)
        self.assertEqual(mission["validated_endurance_min"], 21.0)
        self.assertEqual(mission["processing_latency_max_min"], 5.0)
        self.assertEqual(mission["geotag_error_max_m"], 20.0)

        self.assertEqual(vehicle["cruise_speed_min_mps"], 3.0)
        self.assertEqual(vehicle["cruise_speed_max_mps"], 7.0)
        self.assertEqual(safety["battery_rtl_percent"], 20.0)
        self.assertEqual(weather["max_operating_wind_mps"], 7.0)

    def test_resolved_contradictions_are_encoded(self) -> None:
        docking = self.config["docking"]
        vision = self.config["vision"]
        hardware = self.config["hardware"]

        self.assertEqual(docking["charge_power_w"], 50.0)
        self.assertEqual(docking["landing_accuracy_target_m"], 0.4)
        self.assertEqual(docking["dock_center_north_m"], 0.0)
        self.assertEqual(docking["dock_center_east_m"], 0.0)
        self.assertEqual(docking["dock_center_down_m"], 0.0)
        self.assertEqual(docking["approach_activation_radius_m"], 12.0)
        self.assertEqual(docking["landing_target_stream_rate_hz"], 5.0)
        self.assertEqual(docking["precision_landing_strategy"], "camera_marker_plus_rangefinder")

        self.assertEqual(vision["capture_resolution_min"], "1920x1080")
        self.assertEqual(vision["preferred_physical_camera_resolution"], "3840x2160")
        self.assertFalse(vision["irlock_enabled"])

        self.assertEqual(hardware["gps_model"], "M9N")
        self.assertEqual(hardware["rangefinder_primary"], "TFmini-S")
        self.assertEqual(hardware["rangefinder_secondary"], "MTF-01P")


if __name__ == "__main__":
    unittest.main()
