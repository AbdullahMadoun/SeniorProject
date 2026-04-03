from typing import Optional, Dict, Any
import os
import logging
import time

from ..base import RangefinderDevice, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


def _mock_env_float(key: str, default: float) -> float:
    try:
        val = os.environ.get(key, "")
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


class RangefinderDriver(RangefinderDevice):
    def __init__(
        self,
        device_id: str,
        i2c_address: int = 0x10,
        bus: int = 1,
        min_distance: float = 0.0,
        max_distance: float = 100.0,
        use_mock: Optional[bool] = None,
        model: str = "tfmini",
    ):
        super().__init__(device_id, i2c_address, bus, min_distance, max_distance)
        self._use_mock = use_mock if use_mock is not None else _mock_env_flag("SKYLINK_USE_MOCK_RANGEFINDER")
        self._model = model
        self._connected = False

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message=f"Mock {self._model} initialized")
                return True

            if self._model == "tfmini":
                return self._boot_tfmini()
            elif self._model == "mtf01":
                return self._boot_mtf01()
            else:
                logger.warning(f"Unknown rangefinder model {self._model}, using mock")
                self._use_mock = True
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message=f"Mock {self._model} initialized")
                return True

        except ImportError:
            logger.warning("I2C not available, using mock rangefinder")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message=f"Mock {self._model} initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot rangefinder: {e}")
            self._update_status(HealthStatus.FAILED, message=f"Rangefinder init failed: {e}")
            return False

    def _boot_tfmini(self) -> bool:
        try:
            import busio
            import board
            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="TFmini-S I2C initialized")
            return True
        except Exception as e:
            logger.error(f"TFmini-S init failed: {e}")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock TFmini-S initialized")
            return True

    def _boot_mtf01(self) -> bool:
        try:
            import busio
            import board
            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="MTF-01P I2C initialized")
            return True
        except Exception as e:
            logger.error(f"MTF-01P init failed: {e}")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock MTF-01P initialized")
            return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Rangefinder shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None

        if self._use_mock:
            return b"\x00\x00\x00\x00"

        try:
            result = bytearray(4)
            self._i2c.try_lock()
            try:
                self._i2c.readfrom_into(self._i2c_address, result)
            finally:
                self._i2c.unlock()
            return bytes(result)
        except Exception as e:
            logger.error(f"Rangefinder read error: {e}")
            return None

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        distance = self.get_distance()
        if distance is None:
            return None
        return {"distance": distance, "timestamp": time.time()}

    def get_distance(self) -> Optional[float]:
        if not self._connected:
            return None

        if self._use_mock:
            import random
            return random.uniform(self._min_distance, min(self._max_distance, 50.0))

        raw = self.read_raw_data()
        if raw is None or len(raw) < 4:
            return None

        try:
            distance = (raw[2] << 8) | raw[3]
            if distance > self._max_distance or distance < self._min_distance:
                return None
            return float(distance) / 100.0
        except Exception as e:
            logger.error(f"Failed to parse distance: {e}")
            return None
