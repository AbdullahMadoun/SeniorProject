"""
Tests for camera calibration enforcement.

These tests verify that:
1. Placeholder calibration is rejected in STRICT mode
2. Valid calibration loads successfully
3. Invalid intrinsics (bad focal length) are rejected
4. RMS error threshold is enforced
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


class TestCalibrationLoading:
    """Tests for camera calibration loading."""

    def test_load_camera_calibration_function_exists(self):
        """Verify load_camera_calibration function exists."""
        from autonomy.companion.aruco_detector import load_camera_calibration
        assert callable(load_camera_calibration)

    def test_valid_calibration_loads_successfully(self, valid_calibration_json):
        """Valid calibrated JSON loads without error."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        cm, dc, is_valid = load_camera_calibration(valid_calibration_json)

        assert is_valid is True
        assert cm.shape == (3, 3)
        assert dc.shape == (5, 1)
        assert cm[0, 0] == 615.0

    def test_placeholder_calibration_rejected_in_strict_mode(self, placeholder_calibration_json):
        """Placeholder calibration MUST be rejected in STRICT mode."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        with pytest.raises(ValueError, match="status.*calibrated"):
            load_camera_calibration(placeholder_calibration_json, strict=True)

    def test_placeholder_calibration_rejected_in_simulation_mode(self, placeholder_calibration_json):
        """Placeholder calibration is rejected in simulation mode too."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        with pytest.raises(ValueError, match="status.*calibrated"):
            load_camera_calibration(placeholder_calibration_json, strict=False)

    def test_invalid_focal_length_rejected(self, invalid_focal_calibration_json):
        """fx or fy <= 0 must be rejected."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        with pytest.raises(ValueError, match="focal"):
            load_camera_calibration(invalid_focal_calibration_json, strict=True)

    def test_bad_rms_rejected_in_strict_mode(self, bad_rms_calibration_json):
        """RMS error > 1.0 must be rejected in STRICT mode."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        with pytest.raises(ValueError, match="RMS error.*exceeds"):
            load_camera_calibration(bad_rms_calibration_json, strict=True)

    def test_calibration_file_not_found_raises_error(self):
        """Missing calibration file raises FileNotFoundError."""
        from autonomy.companion.aruco_detector import load_camera_calibration

        with pytest.raises(FileNotFoundError):
            load_camera_calibration(Path("/nonexistent/calibration.json"))


class TestOpenCVArucoBackend:
    """Tests for OpenCVArucoBackend calibration handling."""

    def test_requires_calibration_in_strict_mode(self):
        """OpenCVArucoBackend MUST raise if no calibration in STRICT mode."""
        from autonomy.companion.aruco_detector import OpenCVArucoBackend
        from unittest.mock import MagicMock

        cv2_mock = MagicMock()
        cv2_mock.aruco = MagicMock()
        cv2_mock.aruco.getPredefinedDictionary = MagicMock()
        cv2_mock.aruco.DICT_4X4_50 = 0

        previous = os.environ.pop("SKYLINK_CAMERA_CALIBRATION", None)
        try:
            with pytest.raises(RuntimeError, match="calibration"):
                OpenCVArucoBackend(cv2_mock, calibration_path=None, strict=True)
        finally:
            if previous is not None:
                os.environ["SKYLINK_CAMERA_CALIBRATION"] = previous


class TestCalibrateCameraRMS:
    """Tests for calibrate_camera.py RMS threshold."""

    def test_rms_fail_threshold_defined(self):
        """Verify RMS_FAIL_THRESHOLD is defined."""
        from autonomy.companion import calibrate_camera
        assert hasattr(calibrate_camera, 'RMS_FAIL_THRESHOLD')
        assert calibrate_camera.RMS_FAIL_THRESHOLD == 2.0

    def test_rms_warn_threshold_defined(self):
        """Verify RMS_WARN_THRESHOLD is defined."""
        from autonomy.companion import calibrate_camera
        assert hasattr(calibrate_camera, 'RMS_WARN_THRESHOLD')
        assert calibrate_camera.RMS_WARN_THRESHOLD == 1.0
