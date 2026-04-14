import unittest
import time
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hal.base import HardwareDevice, HealthStatus, HardwareStatus
from hal.manager import HardwareManager
from hal.health import HealthMonitor, HealthEvent, HealthEventType
from hal.watchdog import WatchdogTimer


class FailingDevice(HardwareDevice):
    def __init__(self, device_id: str, fail_boot: bool = False, fail_count: int = 0):
        super().__init__(device_id, "failing")
        self._fail_boot = fail_boot
        self._fail_count = fail_count
        self._connected = False
        self._boot_attempts = 0

    def boot(self) -> bool:
        self._boot_attempts += 1
        if self._fail_boot and (self._fail_count == 0 or self._boot_attempts <= self._fail_count):
            self._update_status(HealthStatus.FAILED, message="Boot failed")
            return False
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected


class IntermittentDevice(HardwareDevice):
    def __init__(self, device_id: str, failure_rate: float = 0.5):
        super().__init__(device_id, "intermittent")
        self._failure_rate = failure_rate
        self._connected = False
        self._call_count = 0

    def boot(self) -> bool:
        import random
        self._call_count += 1
        if random.random() < self._failure_rate:
            self._update_status(HealthStatus.DEGRADED, message="Intermittent failure")
            return False
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected


class TestFailureInjection(unittest.TestCase):
    def test_boot_failure_tracking(self):
        manager = HardwareManager()
        device = FailingDevice("failing_1", fail_boot=True)
        manager.register(device)
        report = manager.boot_all()
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.successful, 0)

    def test_multiple_boot_failures(self):
        manager = HardwareManager()
        device1 = FailingDevice("failing_1", fail_boot=True)
        device2 = FailingDevice("failing_2", fail_boot=True)
        manager.register(device1)
        manager.register(device2)
        report = manager.boot_all()
        self.assertEqual(report.failed, 2)
        self.assertEqual(report.successful, 0)

    def test_partial_boot_success(self):
        manager = HardwareManager()
        device1 = FailingDevice("working_1", fail_boot=False)
        device2 = FailingDevice("failing_1", fail_boot=True)
        manager.register(device1)
        manager.register(device2)
        report = manager.boot_all()
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.successful, 1)

    def test_emergency_stop_on_failure(self):
        manager = HardwareManager()
        device1 = FailingDevice("working_1")
        device2 = FailingDevice("failing_1")
        manager.register(device1)
        manager.register(device2)
        manager.boot_all()
        manager.emergency_stop_all()
        self.assertFalse(device1.is_connected())
        self.assertFalse(device2.is_connected())

    def test_health_monitor_failure_detection(self):
        monitor = HealthMonitor(check_interval=0.1)
        manager = HardwareManager()
        device = FailingDevice("monitored_device", fail_boot=True)
        manager.register(device)
        monitor.set_manager(manager)

        def failure_callback(event):
            pass

        monitor.register_callback(failure_callback)
        monitor.start()
        time.sleep(0.3)
        monitor.stop()

    def test_watchdog_timeout_detection(self):
        watchdog = WatchdogTimer(timeout=0.2, tick_interval=0.1)
        callback = MagicMock()
        watchdog.register("watched_device", timeout=0.2, callback=callback)
        watchdog.start()
        time.sleep(0.5)
        watchdog.stop()
        self.assertTrue(callback.called)

    def test_status_callback_on_failure(self):
        manager = HardwareManager()
        callback = MagicMock()
        manager.register_status_callback(callback)
        device = FailingDevice("callback_test", fail_boot=True)
        manager.register(device)
        manager.boot_all()
        self.assertGreater(callback.call_count, 0)


class TestRecoveryScenarios(unittest.TestCase):
    def test_retry_boot_after_failure(self):
        device = FailingDevice("retry_device", fail_boot=True, fail_count=1)
        self.assertFalse(device.boot())
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())


class TestSystemResilience(unittest.TestCase):
    def test_manager_handles_empty(self):
        manager = HardwareManager()
        report = manager.boot_all()
        self.assertEqual(report.total_devices, 0)

    def test_manager_allows_duplicate_register(self):
        manager = HardwareManager()
        device1 = FailingDevice("dup_device")
        device2 = FailingDevice("dup_device")
        manager.register(device1)
        manager.register(device2)
        self.assertEqual(len(manager.get_all_devices()), 1)

    def test_unregister_nonexistent(self):
        manager = HardwareManager()
        result = manager.unregister("nonexistent")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
