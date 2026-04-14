from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import threading
import time
import logging

from .base import HardwareDevice, HardwareStatus, HealthStatus


logger = logging.getLogger(__name__)


@dataclass
class BootReport:
    total_devices: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    device_results: Dict[str, bool] = field(default_factory=dict)
    device_messages: Dict[str, str] = field(default_factory=dict)
    boot_time: float = 0.0


class HardwareManager:
    def __init__(self):
        self._devices: Dict[str, HardwareDevice] = {}
        self._lock = threading.RLock()
        self._status_callbacks: List[Callable[[HardwareStatus], None]] = []
        self._global_health = HealthStatus.UNKNOWN
        self._boot_in_progress = False

    def register(self, device: HardwareDevice) -> None:
        with self._lock:
            if device.device_id in self._devices:
                logger.warning(f"Device {device.device_id} already registered, replacing")
            device.register_callback(self._on_device_status_change)
            self._devices[device.device_id] = device
            logger.info(f"Registered device: {device.device_id} ({device.device_type})")

    def unregister(self, device_id: str) -> Optional[HardwareDevice]:
        with self._lock:
            device = self._devices.pop(device_id, None)
            if device:
                device.unregister_callback(self._on_device_status_change)
                logger.info(f"Unregistered device: {device_id}")
            return device

    def get_device(self, device_id: str) -> Optional[HardwareDevice]:
        with self._lock:
            return self._devices.get(device_id)

    def get_all_devices(self) -> List[HardwareDevice]:
        with self._lock:
            return list(self._devices.values())

    def get_device_status(self, device_id: str) -> Optional[HardwareStatus]:
        device = self.get_device(device_id)
        return device.status if device else None

    def get_all_statuses(self) -> List[HardwareStatus]:
        with self._lock:
            return [device.status for device in self._devices.values()]

    def register_status_callback(self, callback: Callable[[HardwareStatus], None]) -> None:
        self._status_callbacks.append(callback)

    def unregister_status_callback(self, callback: Callable[[HardwareStatus], None]) -> None:
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    def _on_device_status_change(self, status: HardwareStatus) -> None:
        for callback in self._status_callbacks:
            callback(status)
        self._update_global_health()

    def _update_global_health(self) -> None:
        with self._lock:
            if not self._devices:
                self._global_health = HealthStatus.UNKNOWN
                return

            statuses = [d.status.health for d in self._devices.values()]
            if all(s == HealthStatus.HEALTHY for s in statuses):
                self._global_health = HealthStatus.HEALTHY
            elif any(s == HealthStatus.FAILED for s in statuses):
                self._global_health = HealthStatus.FAILED
            elif any(s == HealthStatus.DEGRADED for s in statuses):
                self._global_health = HealthStatus.DEGRADED
            elif any(s == HealthStatus.OFFLINE for s in statuses):
                self._global_health = HealthStatus.OFFLINE
            else:
                self._global_health = HealthStatus.UNKNOWN

    def get_global_health(self) -> HealthStatus:
        with self._lock:
            return self._global_health

    def boot_all(self, timeout: float = 30.0) -> BootReport:
        if self._boot_in_progress:
            logger.warning("Boot already in progress")
            return BootReport()

        self._boot_in_progress = True
        report = BootReport(total_devices=len(self._devices))
        start_time = time.time()

        try:
            with self._lock:
                devices = list(self._devices.values())

            for device in devices:
                device_id = device.device_id
                try:
                    logger.info(f"Booting device: {device_id}")
                    success = device.boot()
                    elapsed = time.time() - start_time

                    if success:
                        report.successful += 1
                        report.device_results[device_id] = True
                        report.device_messages[device_id] = "Boot successful"
                    else:
                        report.failed += 1
                        report.device_results[device_id] = False
                        report.device_messages[device_id] = "Boot returned False"

                except Exception as e:
                    report.failed += 1
                    report.device_results[device_id] = False
                    report.device_messages[device_id] = f"Boot exception: {str(e)}"
                    logger.exception(f"Error booting device {device_id}")

                if time.time() - start_time > timeout:
                    report.skipped += len(devices) - list(self._devices.values()).index(device) - 1
                    logger.warning(f"Boot timeout reached at {timeout}s")
                    break

            report.boot_time = time.time() - start_time

        finally:
            self._boot_in_progress = False

        logger.info(
            f"Boot complete: {report.successful}/{report.total_devices} successful "
            f"in {report.boot_time:.2f}s"
        )
        return report

    def shutdown_all(self) -> Dict[str, bool]:
        results = {}
        with self._lock:
            devices = list(self._devices.values())

        for device in devices:
            try:
                results[device.device_id] = device.shutdown()
            except Exception as e:
                logger.exception(f"Error shutting down device {device.device_id}")
                results[device.device_id] = False

        return results

    def emergency_stop_all(self) -> None:
        logger.warning("EMERGENCY STOP - shutting down all devices")
        with self._lock:
            devices = list(self._devices.values())

        for device in devices:
            try:
                device.shutdown()
            except Exception:
                pass

        logger.warning("Emergency stop complete")

    def get_devices_by_type(self, device_type: str) -> List[HardwareDevice]:
        with self._lock:
            return [d for d in self._devices.values() if d.device_type == device_type]

    def get_devices_by_health(self, health: HealthStatus) -> List[HardwareDevice]:
        with self._lock:
            return [d for d in self._devices.values() if d.status.health == health]
