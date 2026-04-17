from __future__ import annotations

import os
import time
from typing import Any

import numpy as np

try:
    from .aruco_detector import LandingTargetObservation, load_camera_calibration, _compute_detection_quality, CALIBRATION_FILE_ENV
except ImportError:
    # Handle standalone testing mode if necessary
    pass

class ArucoBoardDetectorBackend:
    """Enhances the traditional ArUco detector by utilizing a Multi-Marker Board."""

    def __init__(
        self,
        cv2_module: Any,
        calibration_path: str | None = None,
        strict: bool = False,
        markers_x: int = 2,
        markers_y: int = 2,
        marker_length_m: float = 0.20,
        marker_separation_m: float = 0.05,
        first_marker_id: int = 0,
    ) -> None:
        self._cv2 = cv2_module
        self._aruco = cv2_module.aruco
        self._marker_length_m = marker_length_m

        # Use 4x4 dictionary by default as per SkyLink standard
        self._dictionary = self._aruco.getPredefinedDictionary(self._aruco.DICT_4X4_50)
        self._parameters = self._aruco.DetectorParameters()
        self._detector = (
            self._aruco.ArucoDetector(self._dictionary, self._parameters)
            if hasattr(self._aruco, "ArucoDetector")
            else None
        )
        
        # Load calibration
        if calibration_path is None:
            calibration_path = os.environ.get("SKYLINK_CAMERA_CALIBRATION")
            
        if calibration_path:
            self._camera_matrix, self._dist_coeffs, _ = load_camera_calibration(calibration_path, strict=strict)
        else:
            raise RuntimeError(
                "Camera calibration not configured. Set SKYLINK_CAMERA_CALIBRATION environment variable "
                "or pass calibration_path to ArUco Board detector."
            )

        # Create Standard GridBoard
        try:
            # OpenCV 4.7.0+ GridBoard constructor format
            self._board = self._aruco.GridBoard(
                (markers_x, markers_y),
                marker_length_m,
                marker_separation_m,
                self._dictionary,
            )
        except AttributeError:
            # Legacy OpenCV format fallback
            self._board = self._aruco.GridBoard_create(
                markers_x,
                markers_y,
                marker_length_m,
                marker_separation_m,
                self._dictionary,
                firstMarker=first_marker_id,
            )
        
        self.primary_marker_id = first_marker_id
        
        # State for pose ambiguity guard (Extrinsic Guess)
        self._last_rvec = None
        self._last_tvec = None

    def detect_marker_geometry(self, frame: Any) -> tuple[Any, Any, Any]:
        if self._detector is not None:
            return self._detector.detectMarkers(frame)
        return self._aruco.detectMarkers(
            frame,
            self._dictionary,
            parameters=self._parameters,
        )

    def detect(self, frame: Any) -> list[LandingTargetObservation]:
        """Detect the board and estimate its pose relative to the camera."""
        corners, ids, _rejected = self.detect_marker_geometry(frame)

        image_shape = frame.shape
        quality = _compute_detection_quality(corners, ids, _rejected, image_shape, self.primary_marker_id)
        
        if ids is None or len(ids) == 0:
            return []

        observations: list[LandingTargetObservation] = []

        try:
            object_points, image_points = self._board.matchImagePoints(corners, ids)
            object_points = np.asarray(object_points, dtype=np.float32).reshape((-1, 3))
            image_points = np.asarray(image_points, dtype=np.float32).reshape((-1, 2))
            use_extrinsic_guess = self._last_rvec is not None and self._last_tvec is not None
            if use_extrinsic_guess:
                retval, rvec, tvec = self._cv2.solvePnP(
                    object_points,
                    image_points,
                    self._camera_matrix,
                    self._dist_coeffs,
                    self._last_rvec,
                    self._last_tvec,
                    True,
                )
            else:
                retval, rvec, tvec = self._cv2.solvePnP(
                    object_points,
                    image_points,
                    self._camera_matrix,
                    self._dist_coeffs,
                )

            if retval and tvec is not None:
                self._last_rvec = rvec
                self._last_tvec = tvec
                flat_tvec = np.asarray(tvec, dtype=np.float32).reshape((-1,))
                drone_x_m = -float(flat_tvec[1])
                drone_y_m = float(flat_tvec[0])
                drone_z_m = float(flat_tvec[2])

                observations.append(
                    LandingTargetObservation(
                        timestamp_utc=time.time(),
                        marker_id=self.primary_marker_id,
                        quality=quality * 1.2,
                        x_m=drone_x_m,
                        y_m=drone_y_m,
                        z_m=drone_z_m,
                        source="cv2.solvepnp.board",
                    )
                )
                return observations
            self._last_rvec = None
            self._last_tvec = None
        except Exception:
            self._last_rvec = None
            self._last_tvec = None

        marker_object_points = np.array(
            [
                [-self._marker_length_m / 2.0, self._marker_length_m / 2.0, 0.0],
                [self._marker_length_m / 2.0, self._marker_length_m / 2.0, 0.0],
                [self._marker_length_m / 2.0, -self._marker_length_m / 2.0, 0.0],
                [-self._marker_length_m / 2.0, -self._marker_length_m / 2.0, 0.0],
            ],
            dtype=np.float32,
        )

        for index, raw_id in enumerate(ids.flatten().tolist()):
            if int(raw_id) != self.primary_marker_id:
                continue

            image_points = np.asarray(corners[index], dtype=np.float32).reshape((-1, 2))
            if hasattr(self._aruco, "estimatePoseSingleMarkers"):
                _rvecs, tvecs, _ = self._aruco.estimatePoseSingleMarkers(
                    [corners[index]],
                    self._marker_length_m,
                    self._camera_matrix,
                    self._dist_coeffs,
                )
                tvec = tvecs[0][0]
            else:
                retval, _rvec, tvec = self._cv2.solvePnP(
                    marker_object_points,
                    image_points,
                    self._camera_matrix,
                    self._dist_coeffs,
                )
                if not retval:
                    continue
                tvec = np.asarray(tvec, dtype=np.float32).reshape((-1,))

            drone_x_m = -float(tvec[1])
            drone_y_m = float(tvec[0])
            drone_z_m = float(tvec[2])

            observations.append(
                LandingTargetObservation(
                    timestamp_utc=time.time(),
                    marker_id=int(raw_id),
                    quality=quality,
                    x_m=drone_x_m,
                    y_m=drone_y_m,
                    z_m=drone_z_m,
                    source="cv2.solvepnp.single",
                )
            )

        return observations
