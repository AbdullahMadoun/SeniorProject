from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Any
import threading
import time
import logging

from .base import HardwareDevice, HardwareStatus, HealthStatus


logger = logging.getLogger(__name__)


class HealthEventType(Enum):
    HEALTH_CHANGED = "health_changed"
    DEVICE_FAILED = "device_failed"
    DEVICE_RECOVERED = "device_recovered"
    DEVICE_OFFLINE = "device_offline"
    CHECK_FAILED = "check_failed"


@dataclass
class HealthEvent:
    event_id: str
    event_type: HealthEventType
    device_id: str
    timestamp: float
    old_health: Optional[HealthStatus] = None
    new_health: Optional[HealthStatus] = None
    message: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "old_health": self.old_health.value if self.old_health else None,
            "new_health": self.new_health.value if self.new_health else None,
            "message": self.message,
            "metadata": self.metadata,
        }


HealthCallback = Callable[[HealthEvent], None]


class HealthMonitor:
    def __init__(
        self,
        check_interval: float = 5.0,
        offline_threshold: float = 30.0,
        degraded_threshold: int = 3,
    ):
        self._check_interval = check_interval
        self._offline_threshold = offline_threshold
        self._degraded_threshold = degraded_threshold
        self._manager = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._callbacks: List[HealthCallback] = []
        self._device_health_history: Dict[str, List[HealthStatus]] = {}
        self._event_id_counter = 0
        self._recent_events: List[HealthEvent] = []
        self._max_recent_events = 100

    def set_manager(self, manager) -> None:
        self._manager = manager

    def start(self) -> None:
        with self._lock:
            if self._running:
                logger.warning("HealthMonitor already running")
                return
            self._running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            logger.info("HealthMonitor started")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("HealthMonitor stopped")

    def register_callback(self, callback: HealthCallback) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: HealthCallback) -> None:
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _emit_event(self, event: HealthEvent) -> None:
        with self._lock:
            self._recent_events.append(event)
            if len(self._recent_events) > self._max_recent_events:
                self._recent_events.pop(0)

        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.exception(f"Error in health callback: {e}")

    def _generate_event_id(self) -> str:
        self._event_id_counter += 1
        return f"evt_{self._event_id_counter}_{int(time.time() * 1000)}"

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_devices()
            except Exception as e:
                logger.exception(f"Error in health check: {e}")
            time.sleep(self._check_interval)

    def _check_devices(self) -> None:
        if not self._manager:
            return

        devices = self._manager.get_all_devices()
        current_time = time.time()

        for device in devices:
            status = device.status
            self._track_health_history(device.device_id, status.health)
            self._check_offline(device, status, current_time)

    def _track_health_history(self, device_id: str, health: HealthStatus) -> None:
        with self._lock:
            if device_id not in self._device_health_history:
                self._device_health_history[device_id] = []
            history = self._device_health_history[device_id]
            history.append(health)
            if len(history) > self._degraded_threshold:
                history.pop(0)

    def _check_offline(
        self, device: HardwareDevice, status: HardwareStatus, current_time: float
    ) -> None:
        time_since_seen = current_time - status.last_seen
        if time_since_seen > self._offline_threshold and status.health != HealthStatus.OFFLINE:
            old_health = status.health
            event = HealthEvent(
                event_id=self._generate_event_id(),
                event_type=HealthEventType.DEVICE_OFFLINE,
                device_id=device.device_id,
                timestamp=current_time,
                old_health=old_health,
                new_health=HealthStatus.OFFLINE,
                message=f"Device offline (no update for {time_since_seen:.1f}s)",
            )
            self._emit_event(event)
            device._update_status(HealthStatus.OFFLINE, message=event.message)

    def get_device_health_history(self, device_id: str) -> List[HealthStatus]:
        with self._lock:
            return list(self._device_health_history.get(device_id, []))

    def get_recent_events(self, limit: int = 50) -> List[HealthEvent]:
        with self._lock:
            return list(self._recent_events[-limit:])

    def get_events_by_device(self, device_id: str, limit: int = 50) -> List[HealthEvent]:
        with self._lock:
            return [e for e in self._recent_events if e.device_id == device_id][-limit:]

    def get_events_by_type(
        self, event_type: HealthEventType, limit: int = 50
    ) -> List[HealthEvent]:
        with self._lock:
            return [e for e in self._recent_events if e.event_type == event_type][-limit:]

    def force_check(self) -> None:
        self._check_devices()
