from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion import mock_rpi


class MockRpiTests(unittest.TestCase):
    def test_gpio_and_board_fallbacks_activate_on_windows(self) -> None:
        with patch.dict(os.environ, {"SKYLINK_FORCE_MOCK_GPIO": "1"}, clear=False):
            gpio, gpio_is_mock = mock_rpi.load_gpio_module()
            board, board_is_mock = mock_rpi.load_board_module()
            busio, busio_is_mock = mock_rpi.load_busio_module()
            ads, analog_in, ads_is_mock = mock_rpi.load_ads_backend()

        self.assertTrue(gpio_is_mock)
        self.assertTrue(board_is_mock)
        self.assertTrue(busio_is_mock)
        self.assertTrue(ads_is_mock)
        self.assertEqual(board.SCL, "MOCK_SCL")
        ads_device = ads.ADS1115(busio.I2C(board.SCL, board.SDA))
        self.assertAlmostEqual(analog_in(ads_device, ads.P1).voltage, 16.8, places=3)

    def test_mock_cv2_camera_generates_frames(self) -> None:
        with patch.dict(os.environ, {"SKYLINK_FORCE_MOCK_CAMERA": "1"}, clear=False):
            cv2_module, is_mock = mock_rpi.load_cv2_module()

        self.assertTrue(is_mock)
        capture = cv2_module.VideoCapture(0)
        ok, frame = capture.read()
        self.assertTrue(ok)
        self.assertEqual(frame.shape, (480, 640, 3))
        capture.release()


if __name__ == "__main__":
    unittest.main()

