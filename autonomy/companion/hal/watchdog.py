from typing import Callable, Dict, Optional
import threading
import time
import logging

from .base import HealthStatus


logger = logging.getLogger(__name__)


class WatchdogExpiredError(Exception):
    pass


class WatchdogTimer:
    def __init__(self, timeout: float = 10.0, tick_interval: float = 1.0):
        self._timeout = timeout
        self._tick_interval = tick_interval
        self._registered: Dict[str, float] = {}
        self._callbacks: Dict[str, Callable[[str], None]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._expiry_callbacks: Dict[str, Callable[[str], None]] = {}

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._tick_loop, daemon=True)
            self._thread.start()
            logger.info("WatchdogTimer started")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("WatchdogTimer stopped")

    def register(
        self, device_id: str, timeout: Optional[float] = None, callback: Optional[Callable[[str], None]] = None
    ) -> None:
        with self._lock:
            self._registered[device_id] = time.time()
            if timeout is not None:
                self._registered[f"{device_id}_timeout"] = timeout
            if callback:
                self._expiry_callbacks[device_id] = callback
            logger.debug(f"Registered watchdog for {device_id}")

    def unregister(self, device_id: str) -> None:
        with self._lock:
            self._registered.pop(device_id, None)
            self._registered.pop(f"{device_id}_timeout", None)
            self._expiry_callbacks.pop(device_id, None)
            logger.debug(f"Unregistered watchdog for {device_id}")

    def kick(self, device_id: str) -> bool:
        with self._lock:
            if device_id not in self._registered:
                logger.warning(f"Cannot kick unregistered watchdog: {device_id}")
                return False
            self._registered[device_id] = time.time()
            return True

    def get_time_remaining(self, device_id: str) -> Optional[float]:
        with self._lock:
            if device_id not in self._registered:
                return None
            last_kick = self._registered[device_id]
            timeout = self._registered.get(f"{device_id}_timeout", self._timeout)
            elapsed = time.time() - last_kick
            remaining = timeout - elapsed
            return max(0.0, remaining)

    def _tick_loop(self) -> None:
        while self._running:
            try:
                self._check_expiry()
            except Exception as e:
                logger.exception(f"Error in watchdog tick: {e}")
            time.sleep(self._tick_interval)

    def _check_expiry(self) -> None:
        current_time = time.time()
        expired = []

        with self._lock:
            for device_id in list(self._registered.keys()):
                if device_id.startswith("_") or device_id.endswith("_timeout"):
                    continue

                timeout = self._registered.get(f"{device_id}_timeout", self._timeout)
                last_kick = self._registered.get(device_id, 0)
                elapsed = current_time - last_kick

                if elapsed >= timeout:
                    expired.append(device_id)

        for device_id in expired:
            self._handle_expiry(device_id)

    def _handle_expiry(self, device_id: str) -> None:
        logger.warning(f"Watchdog expired for device: {device_id}")

        callback = None
        with self._lock:
            callback = self._expiry_callbacks.get(device_id)

        if callback:
            try:
                callback(device_id)
            except Exception as e:
                logger.exception(f"Error in watchdog expiry callback for {device_id}")

    def set_expiry_callback(self, device_id: str, callback: Callable[[str], None]) -> None:
        with self._lock:
            self._expiry_callbacks[device_id] = callback

    def get_registered_devices(self) -> list:
        with self._lock:
            return [k for k in self._registered.keys() if not k.endswith("_timeout")]
