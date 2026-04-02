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

from autonomy.companion.generate_aruco_marker import generate_aruco_marker


class ArucoMarkerGenerationTests(unittest.TestCase):
    def test_marker_generator_writes_pgm_and_metadata_in_mock_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"SKYLINK_FORCE_MOCK_CAMERA": "1"}, clear=False):
                result = generate_aruco_marker(output_dir=Path(tmp), marker_id=0, side_pixels=128)

            self.assertTrue((Path(tmp) / "aruco_id_0.pgm").exists())
            self.assertTrue((Path(tmp) / "aruco_id_0.json").exists())
            self.assertTrue(result["used_mock_cv2"])
            self.assertFalse(result["flight_ready"])


if __name__ == "__main__":
    unittest.main()

