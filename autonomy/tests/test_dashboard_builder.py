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

from autonomy.drone_system.dashboard_builder import build_dashboard_data, render_dashboard_html, write_dashboard


class DashboardBuilderTests(unittest.TestCase):
    def _sample_manifest(self) -> dict:
        return {
            "bundle_name": "latest_live_px4_replay_bundle",
            "summary": {
                "dock_proof_status": "consumed_from_live_telemetry_projection",
            },
            "artifacts": {
                "mission_validation": {
                    "mission": {
                        "mission_id": "dashboard-test",
                        "waypoint_count": 2,
                        "cruise_speed_mps": 5.0,
                        "waypoints_local": [
                            {"index": 0, "north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                            {"index": 1, "north_m": 10.0, "east_m": 10.0, "altitude_m": 10.0},
                        ],
                    },
                    "geofence": {"radius_m": 100.0},
                },
                "execution_validation": {
                    "mission_id": "dashboard-test",
                    "after_rtl_snapshot": {"mode": "return_to_launch"},
                },
                "dock_approach_validation": {
                    "proof_status": "consumed_from_live_telemetry_projection",
                    "dock_target": {"north_m": 0.0, "east_m": 0.0, "down_m": 0.0},
                    "mission_entry_observations": [],
                    "departure_observations": [],
                    "rtl_approach_window": {"observations": []},
                    "live_stream": {
                        "records": [
                            {
                                "index": 0,
                                "snapshot": {"mode": "mission", "in_air": True, "battery_percent": 90.0},
                                "vehicle_local_pose": {"north_m": 0.0, "east_m": 0.0, "down_m": -4.0, "yaw_deg": 0.0},
                                "attitude_euler": {"roll_deg": 1.0, "pitch_deg": -1.0, "yaw_deg": 0.0},
                                "altitude_agl_m": 4.0,
                                "horizontal_distance_to_dock_m": 0.0,
                            }
                        ]
                    },
                },
                "landing_target_consumption": {"proof_status": "consumed", "receiver_observation": {"count": 10}},
                "precision_profile": {"profile": []},
                "precision_landing_manifest": {"results": [], "steps": {}},
                "weather_scenario_manifest": {"results": []},
                "live_weather_validation": {"observations": [], "dock_weather_observations": []},
                "media_bindings": [
                    {"id": "media_0", "label": "Gazebo Flight", "kind": "video", "web_path": "/artifacts/media/latest/gazebo.mp4"}
                ],
            },
        }

    def test_build_dashboard_data_wraps_latest_replay_and_baseline(self) -> None:
        payload = build_dashboard_data(self._sample_manifest())

        self.assertIn("baseline", payload)
        self.assertIn("latest_replay", payload)
        self.assertEqual(payload["latest_replay"]["dock"]["proof_status"], "consumed_from_live_telemetry_projection")
        self.assertIn("visualization", payload["baseline"])
        self.assertEqual(payload["baseline"]["visualization"]["fpv"]["proxy_url"], "/api/fpv/stream")

    def test_render_dashboard_html_contains_leaflet_three_and_live_api_hooks(self) -> None:
        html = render_dashboard_html(build_dashboard_data(self._sample_manifest()))

        self.assertIn("leaflet@1.9.4", html)
        self.assertIn("three@0.164.1", html)
        self.assertIn("Line2", html)
        self.assertIn("server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile", html)
        self.assertIn("/api/telemetry/live", html)
        self.assertIn("/api/fpv/stream", html)
        self.assertIn("Launch Live Simulator", html)
        self.assertIn("Cinematic Mode", html)
        self.assertIn("fpv-feed", html)
        self.assertIn("fpv-media", html)
        self.assertIn("status-copy", html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto", html)
        self.assertIn("overflow-wrap: anywhere", html)
        self.assertIn("action-strip", html)

    def test_write_dashboard_writes_index_and_data(self) -> None:
        manifest = self._sample_manifest()
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output_dir = Path(tmp_dir) / "dashboard"
            write_dashboard(replay_bundle_manifest_path=manifest_path, output_dir=output_dir)

            self.assertTrue((output_dir / "index.html").exists())
            self.assertTrue((output_dir / "dashboard_data.json").exists())


if __name__ == "__main__":
    unittest.main()
