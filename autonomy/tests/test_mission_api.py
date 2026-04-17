from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from autonomy.scripts import mission_api


class _FakeStdout:
    def __iter__(self):
        return iter(())


class _FakeProcess:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.stdout = _FakeStdout()
        self.returncode = 0

    def wait(self) -> int:
        return self.returncode


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes], content_type: str = "multipart/x-mixed-replace; boundary=frame") -> None:
        self._chunks = list(chunks)
        self.headers = {"Content-Type": content_type}

    def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        return None

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


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
        self.assertTrue(payload["fpv"]["enabled"])
        self.assertEqual(payload["fpv"]["proxy_url"], "/api/fpv/stream")
        self.assertEqual(payload["default_battery"]["warn_battery_threshold_percent"], 25.0)
        self.assertEqual(payload["default_battery"]["emergency_battery_threshold_percent"], 18.0)
        self.assertEqual(payload["default_battery"]["low_battery_action"], "return")
        self.assertEqual(payload["default_simulation"]["weather_profile_mode"], "proof")

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

    def test_execute_revalidates_prepared_mission_before_starting_job(self) -> None:
        mission_api.PREPARED_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
        mission_api.PREPARED_SPEC_PATH.write_text(
            json.dumps(
                {
                    "mission_id": "bad-prepared",
                    "cruise_speed_mps": 5.0,
                    "waypoints": [
                        {"north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                        {"north_m": 10.0, "east_m": 10.0, "altitude_m": 999.0},
                    ],
                }
            ),
            encoding="utf-8",
        )

        try:
            with patch.object(mission_api.job_manager, "start_job") as start_job_mock:
                response = self.client.post("/api/mission/execute", json=self.valid_payload)

            self.assertEqual(response.status_code, 400)
            self.assertIn("Waypoint altitude 999.0 m exceeds 100.0 m.", response.json()["detail"])
            start_job_mock.assert_not_called()
            self.assertFalse(mission_api.PREPARED_SPEC_PATH.exists())
        finally:
            mission_api.PREPARED_SPEC_PATH.unlink(missing_ok=True)

    def test_validate_accepts_full_trip_mode_and_extended_battery_controls(self) -> None:
        response = self.client.post(
            "/api/mission/validate",
            json={
                "mission_id": "api-full-trip",
                "weather_profile_mode": "full_trip",
                "cruise_speed_mps": 5.0,
                "waypoints": [
                    {"north_m": 0.0, "east_m": 0.0, "altitude_m": 10.0},
                    {"north_m": 20.0, "east_m": 12.0, "altitude_m": 10.0},
                ],
                "battery": {
                    "initial_battery_percent": 100.0,
                    "warn_battery_threshold_percent": 24.0,
                    "rtl_battery_threshold_percent": 14.0,
                    "emergency_battery_threshold_percent": 7.0,
                    "low_battery_action": "warning",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        mission = response.json()["mission"]
        self.assertEqual(mission["weather_profile_mode"], "full_trip")
        self.assertEqual(mission["battery"]["low_battery_action"], "warning")
        self.assertLessEqual(max(point["gust_wind_mps"] for point in mission["weather_profile"]), 7.0)

    def test_runner_command_includes_execution_cpu_cores(self) -> None:
        job = mission_api.MissionExecutionJob(
            job_id="job456",
            spec_path=Path("mission_request.json"),
            created_at="2026-04-02T00:00:00Z",
            spec={},
        )
        process_holder: dict[str, _FakeProcess] = {}

        def _fake_popen(command, **kwargs):
            process = _FakeProcess(command)
            process_holder["process"] = process
            return process

        with patch.object(mission_api.subprocess, "Popen", side_effect=_fake_popen):
            mission_api.job_manager._run_job(job)

        command = process_holder["process"].command
        self.assertIn("--cpu-cores", command)
        self.assertEqual(command[command.index("--cpu-cores") + 1], mission_api.DEFAULT_EXECUTION_CPU_CORES)
        self.assertEqual(job.status, "completed")

    def test_root_redirects_to_dashboard(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/dashboard/index.html")

    def test_main_applies_cpu_affinity_before_starting_uvicorn(self) -> None:
        with patch.object(mission_api, "enforce_cpu_affinity") as enforce_mock, patch.object(mission_api.uvicorn, "run") as run_mock:
            mission_api.main(["--host", "0.0.0.0", "--port", "9000", "--cpu-core", "0"])

        enforce_mock.assert_called_once_with(0, label="mission_api")
        run_mock.assert_called_once_with(mission_api.app, host="0.0.0.0", port=9000)

    def test_fpv_stream_proxy_relays_upstream_mjpeg_bytes(self) -> None:
        target = "http://fpv.example/stream"
        probe = _FakeStreamResponse([], content_type="multipart/x-mixed-replace; boundary=frame")
        stream = _FakeStreamResponse([b"--frame\r\nContent-Type: image/jpeg\r\n\r\nabc", b""], content_type="multipart/x-mixed-replace; boundary=frame")

        with patch.object(mission_api.urllib.request, "urlopen", side_effect=[probe, stream]):
            response = self.client.get(f"/api/fpv/stream?source_url={target}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
        self.assertIn(b"--frame", response.content)

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
