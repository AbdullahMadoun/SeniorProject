from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.calibrate_camera import calibrate_camera


class CameraCalibrationTests(unittest.TestCase):
    def test_template_only_mode_writes_placeholder_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "camera_calibration.json"
            result = calibrate_camera(
                image_glob=str(Path(tmp) / "*.png"),
                output_path=output_path,
                template_only=True,
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(result["status"], "template")
            self.assertEqual(result["camera_matrix"][0][0], 615.0)


if __name__ == "__main__":
    unittest.main()
