from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.replay_bundle import build_replay_bundle


class ReplayBundleTests(unittest.TestCase):
    def test_build_replay_bundle_writes_manifest_summary_and_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            live_px4 = repo_root / "artifacts" / "live_px4"
            precision_dir = repo_root / "artifacts" / "precision_landing" / "latest"
            weather_dir = repo_root / "artifacts" / "weather_scenarios" / "latest"
            live_px4.mkdir(parents=True, exist_ok=True)
            precision_dir.mkdir(parents=True, exist_ok=True)
            weather_dir.mkdir(parents=True, exist_ok=True)

            (live_px4 / "latest_mission_validation.json").write_text(
                json.dumps({"mission": {"waypoint_count": 6}}),
                encoding="utf-8",
            )
            (live_px4 / "latest_execution_validation.json").write_text(
                json.dumps({"after_rtl_snapshot": {"mode": "return_to_launch"}}),
                encoding="utf-8",
            )
            (live_px4 / "latest_precision_landing_profile.json").write_text(
                json.dumps({"profile": [{"name": "RTL_PLD_MD", "applied_value": 2}]}),
                encoding="utf-8",
            )
            (live_px4 / "latest_landing_target_consumption.json").write_text(
                json.dumps({"receiver_observation": {"count": 50}}),
                encoding="utf-8",
            )
            (live_px4 / "latest_dock_approach_validation.json").write_text(
                json.dumps(
                    {
                        "proof_status": "consumed_from_live_telemetry_projection",
                        "receiver_observation": {"count": 8},
                        "live_stream": {
                            "record_count": 8,
                            "last_record": {
                                "horizontal_distance_to_dock_m": 0.385,
                                "snapshot": {"in_air": False},
                            },
                            "records": [
                                {
                                    "index": 0,
                                    "snapshot": {"mode": "return_to_launch", "in_air": True},
                                    "altitude_agl_m": 23.0,
                                    "horizontal_distance_to_dock_m": 10.2,
                                    "vehicle_local_pose": {
                                        "north_m": 0.1,
                                        "east_m": 0.2,
                                        "down_m": -23.0,
                                        "yaw_deg": 96.0,
                                    },
                                    "sample": {"x_m": 0.0, "y_m": 0.0, "z_m": 0.0},
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (precision_dir / "manifest.json").write_text(
                json.dumps({"passed_count": 2, "scenario_count": 3}),
                encoding="utf-8",
            )
            (weather_dir / "manifest.json").write_text(
                json.dumps({"passed_count": 4, "scenario_count": 4}),
                encoding="utf-8",
            )

            output_dir = repo_root / "artifacts" / "replay_bundle" / "latest"
            manifest = build_replay_bundle(repo_root=repo_root, output_dir=output_dir)

            self.assertEqual(manifest["summary"]["mission_waypoint_count"], 6)
            self.assertEqual(manifest["summary"]["dock_receiver_count"], 8)
            self.assertEqual(manifest["summary"]["dock_final_horizontal_distance_m"], 0.385)
            self.assertEqual(manifest["summary"]["precision_profile_rtl_pld_md"], 2)
            self.assertEqual(manifest["summary"]["weather_scenario_passed_count"], 4)
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "summary.md").exists())
            self.assertTrue((output_dir / "dock_approach_timeline.csv").exists())


if __name__ == "__main__":
    unittest.main()
