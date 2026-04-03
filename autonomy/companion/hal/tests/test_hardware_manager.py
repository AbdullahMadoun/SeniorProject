import unittest
import time
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hal.base import HardwareDevice, HardwareStatus, HealthStatus, I2CSensor
from hal.manager import HardwareManager, BootReport


class MockDevice(HardwareDevice):
    def __init__(self, device_id: str, device_type: str = "mock", boot_success: bool = True):
        super().__init__(device_id, device_type)
        self._boot_success = boot_success
        self._connected = False

    def boot(self) -> bool:
        time.sleep(0.01)
        if not self._boot_success:
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


class TestHardwareManager(unittest.TestCase):
    def setUp(self):
        self.manager = HardwareManager()

    def test_register_and_get_device(self):
        device = MockDevice("test_device_1")
        self.manager.register(device)
        retrieved = self.manager.get_device("test_device_1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.device_id, "test_device_1")

    def test_register_duplicate(self):
        device1 = MockDevice("test_device")
        device2 = MockDevice("test_device")
        self.manager.register(device1)
        self.manager.register(device2)
        retrieved = self.manager.get_device("test_device")
        self.assertEqual(retrieved, device2)

    def test_unregister(self):
        device = MockDevice("test_device")
        self.manager.register(device)
        removed = self.manager.unregister("test_device")
        self.assertIsNotNone(removed)
        self.assertIsNone(self.manager.get_device("test_device"))

    def test_get_all_devices(self):
        device1 = MockDevice("device_1")
        device2 = MockDevice("device_2")
        self.manager.register(device1)
        self.manager.register(device2)
        devices = self.manager.get_all_devices()
        self.assertEqual(len(devices), 2)

    def test_boot_all_success(self):
        device1 = MockDevice("device_1", boot_success=True)
        device2 = MockDevice("device_2", boot_success=True)
        self.manager.register(device1)
        self.manager.register(device2)
        report = self.manager.boot_all()
        self.assertEqual(report.total_devices, 2)
        self.assertEqual(report.successful, 2)
        self.assertEqual(report.failed, 0)

    def test_boot_all_partial_failure(self):
        device1 = MockDevice("device_1", boot_success=True)
        device2 = MockDevice("device_2", boot_success=False)
        self.manager.register(device1)
        self.manager.register(device2)
        report = self.manager.boot_all()
        self.assertEqual(report.total_devices, 2)
        self.assertEqual(report.successful, 1)
        self.assertEqual(report.failed, 1)

    def test_boot_all_timeout(self):
        device1 = MockDevice("device_1", boot_success=True)
        device2 = MockDevice("device_2", boot_success=True)
        self.manager.register(device1)
        self.manager.register(device2)
        report = self.manager.boot_all(timeout=0.001)
        self.assertLessEqual(report.boot_time, 0.1)

    def test_shutdown_all(self):
        device1 = MockDevice("device_1")
        device2 = MockDevice("device_2")
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.boot_all()
        results = self.manager.shutdown_all()
        self.assertTrue(results["device_1"])
        self.assertTrue(results["device_2"])

    def test_emergency_stop_all(self):
        device1 = MockDevice("device_1")
        device2 = MockDevice("device_2")
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.boot_all()
        self.manager.emergency_stop_all()
        self.assertFalse(device1.is_connected())
        self.assertFalse(device2.is_connected())

    def test_global_health_unknown_when_empty(self):
        self.assertEqual(self.manager.get_global_health(), HealthStatus.UNKNOWN)

    def test_global_health_healthy(self):
        device1 = MockDevice("device_1")
        device2 = MockDevice("device_2")
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.boot_all()
        self.assertEqual(self.manager.get_global_health(), HealthStatus.HEALTHY)

    def test_global_health_failed(self):
        device1 = MockDevice("device_1")
        device2 = MockDevice("device_2", boot_success=False)
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.boot_all()
        self.assertEqual(self.manager.get_global_health(), HealthStatus.FAILED)

    def test_status_callback(self):
        callback = MagicMock()
        self.manager.register_status_callback(callback)
        device = MockDevice("test_device")
        self.manager.register(device)
        self.manager.boot_all()
        self.assertGreater(callback.call_count, 0)

    def test_get_devices_by_type(self):
        device1 = MockDevice("device_1", "gpio")
        device2 = MockDevice("device_2", "i2c")
        device3 = MockDevice("device_3", "gpio")
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.register(device3)
        gpio_devices = self.manager.get_devices_by_type("gpio")
        self.assertEqual(len(gpio_devices), 2)

    def test_get_devices_by_health(self):
        device1 = MockDevice("device_1", boot_success=True)
        device2 = MockDevice("device_2", boot_success=False)
        self.manager.register(device1)
        self.manager.register(device2)
        self.manager.boot_all()
        healthy = self.manager.get_devices_by_health(HealthStatus.HEALTHY)
        failed = self.manager.get_devices_by_health(HealthStatus.FAILED)
        self.assertEqual(len(healthy), 1)
        self.assertEqual(len(failed), 1)


class TestBootReport(unittest.TestCase):
    def test_boot_report_defaults(self):
        report = BootReport()
        self.assertEqual(report.total_devices, 0)
        self.assertEqual(report.successful, 0)
        self.assertEqual(report.failed, 0)
        self.assertEqual(report.skipped, 0)
        self.assertEqual(len(report.device_results), 0)


if __name__ == "__main__":
    unittest.main()
