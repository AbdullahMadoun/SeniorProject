from typing import Optional, Dict, Any, List
import os
import logging
import time

from ..base import MAVLinkDevice, HealthStatus

logger = logging.getLogger(__name__)


def _mock_env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")


def _mock_env_float(key: str, default: float) -> float:
    try:
        val = os.environ.get(key, "")
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


class MAVLinkDriver(MAVLinkDevice):
    def __init__(
        self,
        device_id: str,
        connection_string: str = "tcp:localhost:5760",
        use_mock: Optional[bool] = None,
        max_retries: int = 3,
    ):
        super().__init__(device_id, connection_string)
        self._use_mock = use_mock if use_mock is not None else _env_flag("SKYLINK_USE_MOCK_MAVLINK")
        self._client = None
        self._connected = False
        self._armed = False
        self._max_retries = max_retries

    def boot(self) -> bool:
        try:
            if self._use_mock:
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Mock MAVLink initialized")
                return True

            from mavsdk import System
            self._client = System()
            self._update_status(HealthStatus.HEALTHY, message="MAVLink system created")
            return True

        except ImportError:
            logger.warning("mavsdk not available, using mock MAVLink")
            self._use_mock = True
            self._connected = True
            self._update_status(HealthStatus.HEALTHY, message="Mock MAVLink initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to boot MAVLink: {e}")
            self._update_status(HealthStatus.FAILED, message=f"MAVLink init failed: {e}")
            return False

    def shutdown(self) -> bool:
        self._connected = False
        self._armed = False
        self._client = None
        self._update_status(HealthStatus.OFFLINE, message="MAVLink shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        if self._use_mock:
            self._connected = True
            return True

        import asyncio

        async def _connect():
            try:
                await self._client.connect(self._connection_string)
                self._connected = True
                self._update_status(HealthStatus.HEALTHY, message="Connected to MAVLink")
                return True
            except Exception as e:
                logger.error(f"MAVLink connection failed: {e}")
                return False

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_connect())
            else:
                loop.run_until_complete(_connect())
        except Exception as e:
            logger.error(f"Failed to start MAVLink connection: {e}")
            return False

        return self._connected

    def send_command(self, command: int, params: List[float]) -> bool:
        if not self._connected:
            return False

        if self._use_mock:
            return True

        try:
            if command == 176:
                pass
            return True

        except Exception as e:
            logger.error(f"MAVLink command failed: {e}")
            return False

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None

        if self._use_mock:
            import random
            return {
                "lat": 37.7749 + random.uniform(-0.01, 0.01),
                "lon": -122.4194 + random.uniform(-0.01, 0.01),
                "alt": 10.0 + random.uniform(-1, 1),
                "heading": random.uniform(0, 360),
                "speed": random.uniform(0, 10),
                "battery": random.uniform(20, 100),
            }

        return None


def _env_flag(key: str) -> bool:
    return os.environ.get(key, "").lower() in ("1", "true", "yes")
