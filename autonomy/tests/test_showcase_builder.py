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

from autonomy.drone_system.showcase_builder import build_showcase_data, render_showcase_html, write_showcase


class ShowcaseBuilderTests(unittest.TestCase):
    def _sample_bundle_manifest(self) -> dict:
        return {
            "bundle_name": "latest_live_px4_replay_bundle",
            "summary": {
                "dock_proof_status": "consumed_from_live_telemetry_projection",
                "dock_receiver_count": 8,
                "dock_final_horizontal_distance_m": 0.385,
                "weather_scenario_passed_count": 4,
                "weather_scenario_total_count": 4,
                "precision_profile_rtl_pld_md": 2,
            },
            "artifacts": {
                "mission_validation": {
                    "mission": {
                        "mission_id": "live-sitl-smoke",
                        "waypoint_count": 6,
                        "cruise_speed_mps": 5.0,
                        "area_m2": 400.0,
                        "north_span_m": 20.0,
                        "east_span_m": 20.0,
                    },
                    "geofence": {"radius_m": 100.0},
                    "before_upload": {
                        "mode": "hold",
                        "armed": False,
                        "in_air": False,
                        "battery_percent": 100.0,
                        "position": {"alt_m": 0.0},
                        "mission_progress": {"current": 0, "total": 0},
                    },
                    "after_upload": {
                        "mode": "hold",
                        "armed": False,
                        "in_air": False,
                        "battery_percent": 100.0,
                        "position": {"alt_m": 0.0},
                        "mission_progress": {"current": 0, "total": 0},
                    },
                },
                "execution_validation": {
                    "mission_id": "live-execution-smoke",
                    "initial_snapshot": {
                        "mode": "hold",
                        "armed": False,
                        "in_air": False,
                        "battery_percent": 100.0,
                        "position": {"alt_m": 0.0},
                        "mission_progress": {"current": 0, "total": 0},
                    },
                    "mission_phase_snapshots": [
                        {
                            "snapshot": {
                                "mode": "mission",
                                "armed": True,
                                "in_air": True,
                                "battery_percent": 98.0,
                                "position": {"alt_m": 0.0},
                                "mission_progress": {"current": 1, "total": 6},
                            }
                        }
                    ],
                    "after_rtl_snapshot": {
                        "mode": "return_to_launch",
                        "armed": True,
                        "in_air": True,
                        "battery_percent": 82.0,
                        "position": {"alt_m": 6.5},
                        "mission_progress": {"current": 0, "total": 0},
                    },
                },
                "precision_profile": {
                    "profile": [
                        {"name": "RTL_PLD_MD", "applied_value": 2, "rationale": "Required precision landing."}
                    ]
                },
                "landing_target_consumption": {
                    "proof_status": "consumed",
                    "bridge_host_to_px4_count": 54,
                    "receiver_observation": {"count": 50, "first_match": {"x": 1.25, "y": -0.75, "z": 0.0}},
                },
                "dock_approach_validation": {
                    "proof_status": "consumed_from_live_telemetry_projection",
                    "mission_entry_observations": [
                        {
                            "t_s": 10.0,
                            "snapshot": {"mode": "mission", "in_air": True, "battery_percent": 98.0},
                            "local_pose": {"north_m": 0.0, "east_m": 0.0, "down_m": -3.5, "yaw_deg": 96.9},
                            "attitude_euler": {"roll_deg": 1.0, "pitch_deg": -0.8, "yaw_deg": 96.9},
                        }
                    ],
                    "departure_observations": [
                        {
                            "t_s": 11.0,
                            "snapshot": {"mode": "mission", "in_air": True, "battery_percent": 92.0},
                            "local_pose": {"north_m": 0.5, "east_m": 2.0, "down_m": -8.0, "yaw_deg": 88.0},
                            "horizontal_distance_to_dock_m": 2.06,
                            "attitude_euler": {"roll_deg": 4.0, "pitch_deg": -3.0, "yaw_deg": 88.0},
                        },
                        {
                            "t_s": 12.0,
                            "snapshot": {"mode": "mission", "in_air": True, "battery_percent": 82.0},
                            "local_pose": {"north_m": 9.0, "east_m": 19.0, "down_m": -10.0, "yaw_deg": -16.0},
                            "horizontal_distance_to_dock_m": 21.0,
                            "attitude_euler": {"roll_deg": 6.0, "pitch_deg": -4.0, "yaw_deg": -16.0},
                        },
                    ],
                    "rtl_approach_window": {
                        "activation_radius_m": 12.0,
                        "observations": [
                            {
                                "t_s": 13.0,
                                "snapshot": {"mode": "return_to_launch", "in_air": True, "battery_percent": 62.0},
                                "local_pose": {"north_m": 10.1, "east_m": 1.7, "down_m": -10.0, "yaw_deg": -91.1},
                                "horizontal_distance_to_dock_m": 10.27,
                                "altitude_agl_m": 10.0,
                                "attitude_euler": {"roll_deg": 2.0, "pitch_deg": -2.0, "yaw_deg": -91.1},
                            }
                        ],
                    },
                    "live_stream": {
                        "last_record": {
                            "horizontal_distance_to_dock_m": 0.385,
                            "snapshot": {"in_air": False, "mode": "mission", "armed": False, "battery_percent": 100.0, "position": {"alt_m": -0.05}, "mission_progress": {"current": 0, "total": 0}},
                        },
                        "first_record": {
                            "snapshot": {"in_air": True, "mode": "return_to_launch", "armed": True, "battery_percent": 52.0, "position": {"alt_m": 23.1}, "mission_progress": {"current": 0, "total": 0}},
                        },
                        "records": [
                            {
                                "index": 0,
                                "snapshot": {"mode": "return_to_launch", "in_air": True, "battery_percent": 52.0},
                                "altitude_agl_m": 23.1,
                                "horizontal_distance_to_dock_m": 10.6,
                                "vehicle_local_pose": {"north_m": 10.5, "east_m": 1.3, "down_m": -23.1, "yaw_deg": -91.3},
                                "attitude_euler": {"roll_deg": 2.5, "pitch_deg": -1.2, "yaw_deg": -91.3},
                            },
                            {
                                "index": 1,
                                "snapshot": {"mode": "mission", "in_air": False, "battery_percent": 100.0},
                                "altitude_agl_m": 0.0,
                                "horizontal_distance_to_dock_m": 0.385,
                                "vehicle_local_pose": {"north_m": 0.38, "east_m": 0.06, "down_m": 0.06, "yaw_deg": 97.8},
                                "attitude_euler": {"roll_deg": 0.0, "pitch_deg": 0.0, "yaw_deg": 97.8},
                            },
                        ],
                    },
                },
                "precision_landing_manifest": {
                    "results": [
                        {"name": "nominal_precision_touchdown", "passed": True, "final_phase": "touchdown", "touchdown_error_m": 0.2, "details": ["touchdown_within_target"]},
                    ],
                    "steps": {
                        "nominal_precision_touchdown": [
                            {"t_s": 0.0, "phase": "align", "altitude_m": 8.0, "horizontal_error_m": 1.8},
                            {"t_s": 1.0, "phase": "descend", "altitude_m": 6.0, "horizontal_error_m": 0.8},
                        ]
                    },
                },
                "weather_scenario_manifest": {
                    "results": [
                        {"name": "nominal_weather_ready", "passed": True, "effective_wind_mps": 4.5, "launch_allowed": True, "mission_continue_allowed": True, "dock_allowed": True, "safety_action": "continue", "final_mode": "hold"},
                        {"name": "gust_abort_launch", "passed": True, "effective_wind_mps": 8.2, "launch_allowed": False, "mission_continue_allowed": False, "dock_allowed": False, "safety_action": "abort_launch", "final_mode": "hold"},
                    ]
                },
            },
        }

    def test_build_showcase_data_extracts_lifecycle_and_full_flight_telemetry(self) -> None:
        showcase_data = build_showcase_data(self._sample_bundle_manifest())

        self.assertEqual(showcase_data["mission"]["waypoint_count"], 6)
        self.assertEqual(len(showcase_data["mission"]["lifecycle"]), 7)
        self.assertEqual(showcase_data["dock"]["records"][0]["index"], 0)
        self.assertEqual(len(showcase_data["flight_telemetry"]), 6)
        self.assertEqual(showcase_data["flight_telemetry"][0]["source"], "mission_entry")
        self.assertEqual(showcase_data["flight_telemetry"][-1]["source"], "dock_stream")
        self.assertIn("roll_deg", showcase_data["flight_telemetry"][0])
        self.assertEqual(len(showcase_data["mission"]["waypoints"]), 6)
        self.assertEqual(showcase_data["weather"]["results"][1]["safety_action"], "abort_launch")

    def test_render_showcase_html_contains_key_sections(self) -> None:
        html = render_showcase_html(build_showcase_data(self._sample_bundle_manifest()))

        self.assertIn("three@0.164.1", html)
        self.assertIn("OrbitControls", html)
        self.assertIn("Mission Lifecycle", html)
        self.assertIn("Weather Gate Evidence", html)
        self.assertIn("Precision Landing Parameters", html)
        self.assertIn("Top-down", html)
        self.assertIn("\"flight_telemetry\"", html)

    def test_write_showcase_writes_index_and_data(self) -> None:
        manifest = self._sample_bundle_manifest()
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output_dir = Path(tmp_dir) / "showcase"
            write_showcase(replay_bundle_manifest_path=manifest_path, output_dir=output_dir)

            self.assertTrue((output_dir / "index.html").exists())
            self.assertTrue((output_dir / "showcase_data.json").exists())


if __name__ == "__main__":
    unittest.main()
