from typing import Optional
import os
import logging

from ..base import GPIODevice, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


def _mock_env_float(key: str, default: float) -> float:
    try:
        val = os.environ.get(key, "")
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


class GPIODriver(GPIODevice):
    def __init__(
        self,
        device_id: str,
        gpio_pin: int,
        direction: str = "in",
        use_mock: Optional[bool] = None,
    ):
        super().__init__(device_id, gpio_pin, direction)
        self._use_mock = use_mock if use_mock is not None else _mock_env_flag("SKYLINK_USE_MOCK_GPIO")
        self._gpio = None
        self._connected = False

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Mock GPIO initialized")
                return True

            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            if self._direction == "in":
                GPIO.setup(self._gpio_pin, GPIO.IN)
            else:
                GPIO.setup(self._gpio_pin, GPIO.OUT)
            self._gpio = GPIO
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="GPIO initialized")
            return True

        except ImportError:
            logger.warning("RPi.GPIO not available, using mock")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock GPIO initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot GPIO device: {e}")
            self._update_status(HealthStatus.FAILED, message=f"GPIO init failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            if self._gpio and not self._use_mock:
                self._gpio.cleanup(self._gpio_pin)
            self._connected = False
            self._update_status(HealthStatus.OFFLINE, message="GPIO shutdown")
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown GPIO: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def read(self) -> Optional[int]:
        if not self._connected:
            return None
        try:
            if self._use_mock:
                import random
                return random.randint(0, 1)

            return self._gpio.input(self._gpio_pin)

        except Exception as e:
            logger.error(f"GPIO read error: {e}")
            self._update_status(HealthStatus.DEGRADED, message=f"GPIO read failed: {e}")
            return None

    def write(self, value: int) -> bool:
        if not self._connected:
            return False
        try:
            if self._use_mock:
                return True

            if self._direction != "out":
                logger.warning("Cannot write to input GPIO")
                return False

            self._gpio.output(self._gpio_pin, value)
            return True

        except Exception as e:
            logger.error(f"GPIO write error: {e}")
            self._update_status(HealthStatus.DEGRADED, message=f"GPIO write failed: {e}")
            return False
