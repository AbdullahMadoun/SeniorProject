from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()

