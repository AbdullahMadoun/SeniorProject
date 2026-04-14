import unittest
import time

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hal.base import HardwareDevice, HealthStatus
from hal.manager import HardwareManager
from hal.health import HealthMonitor
from hal.watchdog import WatchdogTimer
from hal.drivers.mock_driver import (
    MockGPSDevice,
    MockRangefinderDevice,
    MockADCDevice,
    MockCameraDevice,
    MockMAVLinkDevice,
    MockGPIODevice,
)


class FullSystemDevice(HardwareDevice):
    def __init__(self, device_id: str, device_type: str, boot_delay: float = 0.01):
        super().__init__(device_id, device_type)
        self._boot_delay = boot_delay
        self._connected = False

    def boot(self) -> bool:
        time.sleep(self._boot_delay)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message=f"{self._device_id} booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message=f"{self._device_id} shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected


class TestFullBootSequence(unittest.TestCase):
    def setUp(self):
        self.manager = HardwareManager()
        self.monitor = HealthMonitor(check_interval=1.0)
        self.watchdog = WatchdogTimer(timeout=10.0, tick_interval=1.0)

    def tearDown(self):
        self.monitor.stop()
        self.watchdog.stop()

    def test_boot_all_devices_in_sequence(self):
        devices = [
            FullSystemDevice("gps", "gps"),
            FullSystemDevice("rangefinder_1", "rangefinder"),
            FullSystemDevice("rangefinder_2", "rangefinder"),
            FullSystemDevice("adc", "adc"),
            FullSystemDevice("camera", "camera"),
            FullSystemDevice("mavlink", "mavlink"),
            FullSystemDevice("gpio_1", "gpio"),
            FullSystemDevice("gpio_2", "gpio"),
        ]

        for device in devices:
            self.manager.register(device)
            self.watchdog.register(device.device_id, timeout=30.0)

        self.watchdog.start()
        report = self.manager.boot_all()

        self.assertEqual(report.total_devices, 8)
        self.assertEqual(report.successful, 8)
        self.assertEqual(report.failed, 0)
        self.assertEqual(self.manager.get_global_health(), HealthStatus.HEALTHY)

    def test_boot_with_mock_drivers(self):
        devices = [
            MockGPSDevice("mock_gps", 0x42),
            MockRangefinderDevice("mock_rf", 0x10),
            MockADCDevice("mock_adc", 0x48),
            MockCameraDevice("mock_camera", 0),
            MockMAVLinkDevice("mock_mavlink"),
            MockGPIODevice("mock_gpio", 17),
        ]

        for device in devices:
            self.manager.register(device)

        report = self.manager.boot_all()

        self.assertEqual(report.total_devices, 6)
        self.assertEqual(report.successful, 6)

        for device in devices:
            self.assertTrue(device.is_connected())

    def test_boot_with_health_monitoring(self):
        devices = [
            FullSystemDevice("monitored_1", "test"),
            FullSystemDevice("monitored_2", "test"),
        ]

        for device in devices:
            self.manager.register(device)

        self.monitor.set_manager(self.manager)
        self.monitor.start()

        self.manager.boot_all()

        time.sleep(0.5)
        self.monitor.stop()

        events = self.monitor.get_recent_events()
        self.assertIsInstance(events, list)

    def test_boot_shutdown_cycle(self):
        devices = [
            FullSystemDevice("cycle_1", "test"),
            FullSystemDevice("cycle_2", "test"),
        ]

        for device in devices:
            self.manager.register(device)

        report1 = self.manager.boot_all()
        self.assertEqual(report1.successful, 2)

        results = self.manager.shutdown_all()
        for success in results.values():
            self.assertTrue(success)

        for device in devices:
            self.assertFalse(device.is_connected())

    def test_emergency_stop_during_boot(self):
        devices = [
            FullSystemDevice("emergency_1", "test", boot_delay=1.0),
            FullSystemDevice("emergency_2", "test", boot_delay=1.0),
        ]

        for device in devices:
            self.manager.register(device)

        self.manager.boot_all()
        self.manager.emergency_stop_all()

        for device in devices:
            self.assertFalse(device.is_connected())

    def test_boot_report_accuracy(self):
        device1 = FullSystemDevice("report_1", "test")
        device2 = FullSystemDevice("report_2", "test")

        self.manager.register(device1)
        self.manager.register(device2)

        report = self.manager.boot_all()

        self.assertEqual(report.total_devices, 2)
        self.assertIn("report_1", report.device_results)
        self.assertIn("report_2", report.device_results)
        self.assertTrue(report.device_results["report_1"])
        self.assertTrue(report.device_results["report_2"])
        self.assertGreater(report.boot_time, 0)


class TestBootPerformance(unittest.TestCase):
    def test_parallel_boot_performance(self):
        manager = HardwareManager()
        num_devices = 10

        for i in range(num_devices):
            device = FullSystemDevice(f"perf_{i}", "test", boot_delay=0.01)
            manager.register(device)

        start = time.time()
        report = manager.boot_all()
        elapsed = time.time() - start

        self.assertEqual(report.successful, num_devices)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
