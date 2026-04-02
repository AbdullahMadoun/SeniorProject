from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.request
import unittest
from unittest.mock import patch


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.video_logger import VideoLoggerConfig, VideoLoggerService


class VideoLoggerTests(unittest.TestCase):
    def test_video_logger_runs_with_mock_camera_and_mock_mavlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            config = VideoLoggerConfig(
                output_dir=output_dir,
                max_frames=4,
                frame_interval_s=0.01,
                use_mock_mavlink=True,
                use_mock_camera=True,
            )
            result = VideoLoggerService(config).run()

            csv_path = output_dir / "telemetry_log.csv"
            summary_path = output_dir / "summary.json"
            self.assertTrue(csv_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(result["processed_frames"], 4)
            self.assertGreater(result["telemetry_updates"], 0)
            with csv_path.open("r", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["telemetry_source"], "mock_mavlink")

    def test_video_logger_can_publish_mjpeg_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            config = VideoLoggerConfig(
                output_dir=output_dir,
                max_frames=24,
                frame_interval_s=0.02,
                use_mock_mavlink=True,
                use_mock_camera=True,
                stream_enabled=True,
                stream_port=0,
            )
            service = VideoLoggerService(config)
            result_holder: dict[str, object] = {}

            def _runner() -> None:
                result_holder["summary"] = service.run()

            thread = threading.Thread(target=_runner, daemon=True)
            thread.start()
            deadline = time.time() + 5.0
            stream_url = None
            while time.time() < deadline:
                stream_url = service.current_stream_url()
                if stream_url:
                    break
                time.sleep(0.05)
            self.assertTrue(stream_url)

            with urllib.request.urlopen(stream_url, timeout=5.0) as response:
                content_type = response.headers.get("Content-Type", "")
                first_chunk = response.read(128)

            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())
            self.assertIn("multipart/x-mixed-replace", content_type)
            self.assertIn(b"--frame", first_chunk)
            summary = result_holder["summary"]
            self.assertTrue(summary["stream"]["enabled"])
            self.assertTrue(summary["stream"]["url"])

    def test_video_logger_applies_configured_cpu_affinity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            config = VideoLoggerConfig(
                output_dir=output_dir,
                max_frames=2,
                frame_interval_s=0.01,
                use_mock_mavlink=True,
                use_mock_camera=True,
                cpu_core=1,
            )
            with patch("autonomy.companion.video_logger.enforce_cpu_affinity") as enforce_mock:
                VideoLoggerService(config).run()

            enforce_mock.assert_called_once_with(1, label="video_logger")


if __name__ == "__main__":
    unittest.main()
