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

        # Use 4x4 dictionary by default as per SkyLink standard
        self._dictionary = self._aruco.getPredefinedDictionary(self._aruco.DICT_4X4_50)
        self._parameters = self._aruco.DetectorParameters()
        
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
            # Override IDs if needed
            ids = np.arange(first_marker_id, first_marker_id + (markers_x * markers_y), dtype=np.int32)
            self._board.setIds(ids)
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

    def detect(self, frame: Any) -> list[LandingTargetObservation]:
        """Detect the board and estimate its pose relative to the camera."""
        corners, ids, _rejected = self._aruco.detectMarkers(
            frame,
            self._dictionary,
            parameters=self._parameters,
        )

        image_shape = frame.shape
        quality = _compute_detection_quality(corners, ids, _rejected, image_shape, self.primary_marker_id)
        
        if ids is None or len(ids) == 0:
            return []

        observations: list[LandingTargetObservation] = []

        try:
            # Attempt to estimate entire Board pose with Extrinsic Guess for stability
            use_extrinsic_guess = self._last_rvec is not None and self._last_tvec is not None
            rvec_in = self._last_rvec if use_extrinsic_guess else None
            tvec_in = self._last_tvec if use_extrinsic_guess else None
            
            retval, rvec, tvec = self._aruco.estimatePoseBoard(
                corners,
                ids,
                self._board,
                self._camera_matrix,
                self._dist_coeffs,
                rvec_in,
                tvec_in,
                useExtrinsicGuess=use_extrinsic_guess
            )
            
            if retval and tvec is not None:
                # Save state for next frame to prevent pose flipping
                self._last_rvec = rvec
                self._last_tvec = tvec
                
                # Transform from OpenCV Camera frame (Z-forward-out, X-right, Y-down)
                # to Drone BODY_FRD (X-forward, Y-right, Z-down)
                drone_x_m = -float(tvec[1][0])
                drone_y_m = float(tvec[0][0])
                drone_z_m = float(tvec[2][0])
                
                # Board successfully detected
                observations.append(
                    LandingTargetObservation(
                        timestamp_utc=time.time(),
                        marker_id=self.primary_marker_id,
                        quality=quality * 1.2,  # Boost quality for board detection
                        x_m=drone_x_m,
                        y_m=drone_y_m,
                        z_m=drone_z_m,
                        source="cv2.aruco.board",
                    )
                )
                return observations
            else:
                # If estimate fails, reset guess
                self._last_rvec = None
                self._last_tvec = None
        except Exception:
            # Fallback to single marker if Board throws Exception due to OpenCV versioning
            self._last_rvec = None
            self._last_tvec = None
            pass

        # Fallback: Process single markers if board estimation failed
        rvecs, tvecs, _ = self._aruco.estimatePoseSingleMarkers(
            corners,
            0.20, # Default length
            self._camera_matrix,
            self._dist_coeffs,
        )

        for index, raw_id in enumerate(ids.flatten().tolist()):
            if int(raw_id) != self.primary_marker_id:
                continue
                
            tvec = tvecs[index][0]
            
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
                    source="cv2.aruco.single",
                )
            )

        return observations
