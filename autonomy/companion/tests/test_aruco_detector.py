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

from autonomy.companion.aruco_detector import ArucoDetectorConfig, ArucoPrecisionLandingService


class ArucoDetectorTests(unittest.TestCase):
    def test_aruco_detector_emits_landing_target_with_mock_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            config = ArucoDetectorConfig(
                output_dir=output_dir,
                max_frames=3,
                frame_interval_s=0.01,
                use_mock_camera=True,
                use_mock_mavlink=True,
            )
            with patch.dict(os.environ, {"SKYLINK_MOCK_ARUCO_DETECTION": "1"}, clear=False):
                result = ArucoPrecisionLandingService(config).run()

            self.assertEqual(result["detection_count"], 1)
            self.assertTrue((output_dir / "landing_target_log.json").exists())
            self.assertTrue((output_dir / "aruco_preview.jpg.npy").exists())


if __name__ == "__main__":
    unittest.main()
