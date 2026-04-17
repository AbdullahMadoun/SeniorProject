from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import cv2

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CALIBRATION_PATH = AUTONOMY_ROOT / "fixtures" / "sim_calibration.json"
os.environ.setdefault("SKYLINK_CAMERA_CALIBRATION", str(CALIBRATION_PATH))

from autonomy.companion.aruco_board_detector import ArucoBoardDetectorBackend
from autonomy.simulation.landing_pad import PadRenderConfig, render_frame


class LandingPadRendererTests(unittest.TestCase):
    def test_render_frame_returns_expected_shape(self) -> None:
        frame = render_frame(
            PadRenderConfig(
                altitude_m=4.0,
                offset_x_m=0.25,
                offset_y_m=-0.15,
                drop_prob=0.0,
                noise_enabled=False,
            )
        )

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.shape, (512, 512, 3))

    def test_rendered_board_is_detectable_nominally(self) -> None:
        frame = render_frame(
            PadRenderConfig(
                altitude_m=3.0,
                drop_prob=0.0,
                noise_enabled=False,
            )
        )
        assert frame is not None
        detector = ArucoBoardDetectorBackend(cv2, calibration_path=str(CALIBRATION_PATH))

        observations = detector.detect(frame)

        self.assertGreaterEqual(len(observations), 1)
        self.assertGreater(observations[0].z_m, 0.5)


if __name__ == "__main__":
    unittest.main()
