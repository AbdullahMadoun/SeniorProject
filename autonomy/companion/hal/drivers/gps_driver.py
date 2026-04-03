from typing import Optional, Dict, Any
import os
import logging
import time

from ..base import GPSDevice, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


class GPSDriver(GPSDevice):
    def __init__(
        self,
        device_id: str,
        i2c_address: int = 0x42,
        bus: int = 1,
        use_mock: Optional[bool] = None,
    ):
        super().__init__(device_id, i2c_address, bus)
        self._use_mock = use_mock if use_mock is not None else _mock_env_flag("SKYLINK_USE_MOCK_GPS")
        self._connected = False

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Mock GPS initialized")
                return True

            import busio
            import board
            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="GPS I2C initialized")
            return True

        except ImportError:
            logger.warning("I2C not available, using mock GPS")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock GPS initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot GPS: {e}")
            self._update_status(HealthStatus.FAILED, message=f"GPS init failed: {e}")
            return False

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="GPS shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None

        if self._use_mock:
            return b"\x00\x01\x02\x03\x04\x05\x06\x07"

        try:
            result = bytearray(8)
            self._i2c.try_lock()
            try:
                self._i2c.readfrom_into(self._i2c_address, result)
            finally:
                self._i2c.unlock()
            return bytes(result)
        except Exception as e:
            logger.error(f"GPS read error: {e}")
            return None

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        return self.get_position()

    def get_position(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None

        if self._use_mock:
            return {
                "lat": 37.7749,
                "lon": -122.4194,
                "alt": 10.0,
                "fix": 3,
                "satellites": 12,
            }

        return None

    def get_satellite_count(self) -> int:
        if not self._connected:
            return 0
        if self._use_mock:
            return 12
        return 0
