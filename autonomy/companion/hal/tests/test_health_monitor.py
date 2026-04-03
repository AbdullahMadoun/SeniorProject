import unittest
import time
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hal.base import HardwareDevice, HardwareStatus, HealthStatus
from hal.health import HealthMonitor, HealthEvent, HealthEventType


class MockDevice(HardwareDevice):
    def __init__(self, device_id: str, device_type: str = "mock", boot_success: bool = True):
        super().__init__(device_id, device_type)
        self._boot_success = boot_success
        self._connected = False

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Booted")
        return self._boot_success

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected


class MockManager:
    def __init__(self):
        self._devices = {}

    def register(self, device: HardwareDevice):
        self._devices[device.device_id] = device

    def get_all_devices(self):
        return list(self._devices.values())


class TestHealthMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = HealthMonitor(check_interval=0.1, offline_threshold=1.0)
        self.manager = MockManager()

    def tearDown(self):
        self.monitor.stop()

    def test_start_stop(self):
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        self.assertTrue(True)
        self.monitor.stop()

    def test_register_callback(self):
        callback = MagicMock()
        self.monitor.register_callback(callback)
        self.monitor.unregister_callback(callback)

    def test_emit_event(self):
        event = HealthEvent(
            event_id="test_evt",
            event_type=HealthEventType.HEALTH_CHANGED,
            device_id="test_device",
            timestamp=time.time(),
            old_health=HealthStatus.HEALTHY,
            new_health=HealthStatus.DEGRADED,
        )
        self.monitor._emit_event(event)
        recent = self.monitor.get_recent_events(limit=10)
        self.assertEqual(len(recent), 1)

    def test_check_devices(self):
        device = MockDevice("test_device")
        self.manager.register(device)
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        time.sleep(0.2)
        self.monitor.stop()

    def test_offline_detection(self):
        device = MockDevice("offline_test")
        device._status.last_seen = time.time() - 10
        self.manager.register(device)
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        time.sleep(0.3)
        self.monitor.stop()

    def test_get_device_health_history(self):
        device = MockDevice("history_test")
        self.manager.register(device)
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        time.sleep(0.2)
        self.monitor.stop()
        history = self.monitor.get_device_health_history("history_test")
        self.assertIsInstance(history, list)

    def test_get_events_by_device(self):
        device = MockDevice("event_test")
        self.manager.register(device)
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        time.sleep(0.2)
        self.monitor.stop()
        events = self.monitor.get_events_by_device("event_test")
        self.assertIsInstance(events, list)

    def test_get_events_by_type(self):
        events = self.monitor.get_events_by_type(HealthEventType.DEVICE_FAILED)
        self.assertIsInstance(events, list)

    def test_force_check(self):
        device = MockDevice("force_test")
        self.manager.register(device)
        self.monitor.set_manager(self.manager)
        self.monitor.start()
        self.monitor.force_check()
        self.monitor.stop()


class TestHealthEvent(unittest.TestCase):
    def test_event_to_dict(self):
        event = HealthEvent(
            event_id="test_123",
            event_type=HealthEventType.HEALTH_CHANGED,
            device_id="device_1",
            timestamp=1234567890.0,
            old_health=HealthStatus.HEALTHY,
            new_health=HealthStatus.DEGRADED,
            message="Test message",
            metadata={"key": "value"},
        )
        d = event.to_dict()
        self.assertEqual(d["event_id"], "test_123")
        self.assertEqual(d["event_type"], "health_changed")
        self.assertEqual(d["device_id"], "device_1")
        self.assertEqual(d["old_health"], "healthy")
        self.assertEqual(d["new_health"], "degraded")
        self.assertEqual(d["message"], "Test message")
        self.assertEqual(d["metadata"], {"key": "value"})

    def test_event_default_metadata(self):
        event = HealthEvent(
            event_id="test_456",
            event_type=HealthEventType.DEVICE_FAILED,
            device_id="device_2",
            timestamp=1234567890.0,
        )
        self.assertEqual(event.metadata, {})


if __name__ == "__main__":
    unittest.main()
