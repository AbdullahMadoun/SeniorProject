from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.scripts.export_landing_demo_data import (
    PROOF_SOURCE_SYNTHETIC_REPLAY,
    build_command_entry,
    build_demo_proof,
    simulate_landing_trajectory,
)


class ExportLandingDemoDataTests(unittest.TestCase):
    def test_build_demo_proof_captures_hardware_ready_path(self) -> None:
        proof = build_demo_proof(
            source="live_px4_sitl",
            live_pixhawk=True,
            vehicle_link="udp://:14540",
            command_rate_hz=10.0,
            modes_seen=["return_to_launch", "hold", "offboard"],
            parameter_count=8,
        )

        self.assertTrue(proof["live_pixhawk"])
        self.assertEqual(proof["vehicle_link"], "udp://:14540")
        self.assertEqual(proof["hardware_link"], "/dev/ttyAMA0 @ 57600 baud")
        self.assertIn("PrecisionLandingController", str(proof["hardware_note"]))
        self.assertEqual(proof["precision_parameter_count"], 8)

    def test_build_command_entry_rounds_numeric_fields(self) -> None:
        command = build_command_entry(
            1.23456,
            phase="DESCEND",
            command_type="velocity_ned",
            source="precision_landing_controller",
            forward_velocity_mps=0.1234567,
            right_velocity_mps=-0.7654321,
            down_velocity_mps=0.4,
            north_velocity_mps=0.5000004,
            east_velocity_mps=-0.2500004,
            yaw_deg=14.123456,
        )

        self.assertEqual(command["t"], 1.235)
        self.assertEqual(command["forward_velocity_mps"], 0.123457)
        self.assertEqual(command["right_velocity_mps"], -0.765432)
        self.assertEqual(command["north_velocity_mps"], 0.5)
        self.assertEqual(command["yaw_deg"], 14.123456)

    def test_simulate_landing_trajectory_includes_proof_events_and_commands(self) -> None:
        payload = simulate_landing_trajectory()

        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["proof"]["trajectory_source"], PROOF_SOURCE_SYNTHETIC_REPLAY)
        self.assertFalse(payload["proof"]["live_pixhawk"])
        self.assertGreater(len(payload["frames"]), 50)
        self.assertGreater(len(payload["events"]), 2)
        self.assertGreater(len(payload["commands"]), 50)


if __name__ == "__main__":
    unittest.main()
