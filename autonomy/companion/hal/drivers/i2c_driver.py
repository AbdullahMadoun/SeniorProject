from typing import Optional
import os
import logging
import time

from ..base import I2CSensor, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


def _mock_env_float(key: str, default: float) -> float:
    try:
        val = os.environ.get(key, "")
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


class I2CDriver(I2CSensor):
    def __init__(
        self,
        device_id: str,
        sensor_type: str,
        i2c_address: int,
        bus: int = 1,
        use_mock: Optional[bool] = None,
        max_retries: int = 3,
    ):
        super().__init__(device_id, sensor_type, i2c_address, bus)
        self._use_mock = use_mock if use_mock is not None else _mock_env_flag("SKYLINK_USE_MOCK_I2C")
        self._i2c = None
        self._connected = False
        self._max_retries = max_retries

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Mock I2C initialized")
                return True

            import busio
            import board
            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="I2C initialized")
            return True

        except ImportError:
            logger.warning("busio/board not available, using mock I2C")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock I2C initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot I2C device: {e}")
            self._update_status(HealthStatus.FAILED, message=f"I2C init failed: {e}")
            return False

    def shutdown(self) -> bool:
        self._connected = False
        self._i2c = None
        self._update_status(HealthStatus.OFFLINE, message="I2C shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def _retry_read(self, read_func):
        last_error = None
        for attempt in range(self._max_retries):
            try:
                return read_func()
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    time.sleep(0.01 * (attempt + 1))

        self._update_status(
            HealthStatus.DEGRADED,
            message=f"I2C read failed after {self._max_retries} retries: {last_error}",
        )
        return None

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None

        if self._use_mock:
            return b"\x00\x01\x02\x03"

        def do_read():
            if not self._i2c:
                return None
            result = bytearray(4)
            self._i2c.try_lock()
            try:
                self._i2c.readfrom_into(self._i2c_address, result)
            finally:
                self._i2c.unlock()
            return bytes(result)

        return self._retry_read(do_read)

    def get_measurement(self) -> Optional[dict]:
        raw = self.read_raw_data()
        if raw is None:
            return None
        return {"raw": raw.hex(), "timestamp": time.time()}


class I2CDeviceRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._devices = {}
        return cls._instance

    def register(self, device_id: str, device: I2CSensor) -> None:
        self._devices[device_id] = device

    def get(self, device_id: str) -> Optional[I2CSensor]:
        return self._devices.get(device_id)

    def get_all(self) -> dict:
        return dict(self._devices)
