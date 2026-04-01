from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from autonomy.scripts import mission_api


class MissionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(mission_api.app)
        self.valid_payload = {
            "mission_id": "api-test",
            "cruise_speed_mps": 5.0,
            "waypoints": [
                {"north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                {"north_m": 18.0, "east_m": 12.0, "altitude_m": 10.0},
            ],
        }

    def test_constraints_endpoint_exposes_baseline_limits(self) -> None:
        response = self.client.get("/api/constraints")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mission_limits"]["max_radius_m"], 100.0)
        self.assertEqual(payload["mission_limits"]["max_altitude_m"], 100.0)
        self.assertEqual(payload["connection"]["target"], "udpin://0.0.0.0:14540")
        self.assertEqual(payload["safety"]["max_operating_wind_mps"], 7.0)

    def test_validate_returns_400_with_exact_reason_for_altitude_violation(self) -> None:
        response = self.client.post(
            "/api/mission/validate",
            json={
                "waypoints": [
                    {"north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                    {"north_m": 5.0, "east_m": 5.0, "altitude_m": 140.0},
                ]
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Waypoint altitude 140.0 m exceeds 100.0 m.", response.json()["detail"])

    def test_validate_uses_environment_overrides_when_weather_profile_is_omitted(self) -> None:
        response = self.client.post(
            "/api/mission/validate",
            json={
                "mission_id": "api-weather",
                "cruise_speed_mps": 5.0,
                "waypoints": [
                    {"north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                    {"north_m": 12.0, "east_m": 18.0, "altitude_m": 10.0},
                ],
                "environment": {
                    "wind_speed_mps": 3.4,
                    "wind_direction_deg": 55.0,
                    "gust_multiplier": 1.34,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        mission = response.json()["mission"]
        self.assertEqual(mission["weather_profile"][0]["steady_wind_mps"], 3.4)
        self.assertEqual(mission["weather_profile"][2]["gust_wind_mps"], 10.5)

    def test_execute_returns_job_id_when_runner_is_started(self) -> None:
        fake_job = SimpleNamespace(
            job_id="job123",
            status="running",
            redirect_url="../dashboard/index.html",
            spec={},
        )
        with patch.object(mission_api.job_manager, "start_job", return_value=fake_job):
            response = self.client.post("/api/mission/execute", json=self.valid_payload)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_id"], "job123")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["bridge_status"], "Bridge Active")

    def test_root_redirects_to_dashboard(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/dashboard/index.html")

    def test_live_telemetry_endpoint_streams_job_frames(self) -> None:
        fake_job = mission_api.MissionExecutionJob(
            job_id="job123",
            spec_path=Path("mission.json"),
            created_at="2026-04-01T00:00:00Z",
            spec={},
            status="completed",
        )
        fake_job.append_telemetry(
            {
                "elapsed_s": 1.0,
                "snapshot": {"mode": "mission", "battery_percent": 95.0},
                "local_pose": {"north_m": 1.0, "east_m": 2.0, "down_m": -5.0},
            }
        )
        with patch.object(mission_api.job_manager, "get_job", return_value=fake_job):
            with self.client.stream("GET", "/api/telemetry/live?job_id=job123") as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: telemetry", body)
        self.assertIn("\"north_m\": 1.0", body)

    def test_extract_telemetry_payload_accepts_runner_prefixed_lines(self) -> None:
        payload = mission_api._extract_telemetry_payload(
            '[VALIDATOR] __TELEMETRY__{"elapsed_s":1.2,"snapshot":{"mode":"mission"}}'
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["elapsed_s"], 1.2)
        self.assertEqual(payload["snapshot"]["mode"], "mission")

    def test_job_buffers_roll_forward_without_losing_sequence(self) -> None:
        job = mission_api.MissionExecutionJob(
            job_id="job123",
            spec_path=Path("mission.json"),
            created_at="2026-04-01T00:00:00Z",
            spec={},
            max_event_buffer=3,
            max_telemetry_buffer=2,
        )

        for index in range(5):
            job.append_event("log", {"message": f"log-{index}"})
        for index in range(4):
            job.append_telemetry({"elapsed_s": float(index)})

        events, _ = job.events_since(0)
        telemetry, _ = job.telemetry_since(0)

        self.assertEqual(job.snapshot()["event_count"], 5)
        self.assertEqual(job.snapshot()["telemetry_event_count"], 4)
        self.assertEqual([event["seq"] for event in events], [2, 3, 4])
        self.assertEqual([frame["seq"] for frame in telemetry], [2, 3])


if __name__ == "__main__":
    unittest.main()
