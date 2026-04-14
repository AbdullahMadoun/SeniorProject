from typing import Optional, Dict, Any
import os
import logging

from ..base import CameraDevice, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


class CameraDriver(CameraDevice):
    def __init__(
        self,
        device_id: str,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
        use_mock: Optional[bool] = None,
        mock_calibration: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(device_id, camera_index)
        self._use_mock = use_mock if use_mock is not None else _mock_env_flag("SKYLINK_USE_MOCK_CAMERA")
        self._width = width
        self._height = height
        self._camera = None
        self._connected = False
        self._calibration = mock_calibration or {
            "rms_error": 0.5,
            "camera_matrix": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
            "dist_coeffs": [[0.1, -0.05, 0, 0, 0]],
        }

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Mock camera initialized")
                return True

            from picamera2 import Picamera2
            self._camera = Picamera2(self._camera_index)
            self._camera.configure(self._camera.camera_configure("preview"))
            self._camera.start()
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Camera initialized")
            return True

        except ImportError:
            logger.warning("picamera2 not available, using mock camera")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock camera initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot camera: {e}")
            self._update_status(HealthStatus.FAILED, message=f"Camera init failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            if self._camera and not self._use_mock:
                self._camera.close()
            self._connected = False
            self._update_status(HealthStatus.OFFLINE, message="Camera shutdown")
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown camera: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def capture_frame(self) -> Optional[Any]:
        if not self._connected:
            return None

        try:
            if self._use_mock:
                return {"width": self._width, "height": self._height, "data": b"mock_frame"}

            import numpy as np
            frame = self._camera.capture_array()
            return frame

        except Exception as e:
            logger.error(f"Failed to capture frame: {e}")
            self._update_status(HealthStatus.DEGRADED, message=f"Frame capture failed: {e}")
            return None

    def get_calibration(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None
        return self._calibration.copy()
