import unittest
import time
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hal.watchdog import WatchdogTimer, WatchdogExpiredError


class TestWatchdogTimer(unittest.TestCase):
    def setUp(self):
        self.watchdog = WatchdogTimer(timeout=1.0, tick_interval=0.1)

    def tearDown(self):
        self.watchdog.stop()

    def test_start_stop(self):
        self.watchdog.start()
        self.watchdog.stop()

    def test_register(self):
        self.watchdog.register("test_device", timeout=5.0)
        self.assertIn("test_device", self.watchdog.get_registered_devices())

    def test_unregister(self):
        self.watchdog.register("test_device")
        self.watchdog.unregister("test_device")
        self.assertNotIn("test_device", self.watchdog.get_registered_devices())

    def test_kick_registered(self):
        self.watchdog.register("test_device", timeout=5.0)
        result = self.watchdog.kick("test_device")
        self.assertTrue(result)

    def test_kick_unregistered(self):
        result = self.watchdog.kick("nonexistent")
        self.assertFalse(result)

    def test_get_time_remaining(self):
        self.watchdog.register("test_device", timeout=5.0)
        time.sleep(0.1)
        remaining = self.watchdog.get_time_remaining("test_device")
        self.assertIsNotNone(remaining)
        self.assertLess(remaining, 5.0)
        self.assertGreater(remaining, 0)

    def test_get_time_remaining_unregistered(self):
        remaining = self.watchdog.get_time_remaining("nonexistent")
        self.assertIsNone(remaining)

    def test_expiry_callback(self):
        callback = MagicMock()
        self.watchdog.register("expiry_test", timeout=0.1, callback=callback)
        self.watchdog.start()
        time.sleep(0.5)
        self.watchdog.stop()
        self.assertTrue(callback.called)

    def test_expiry_detection(self):
        callback = MagicMock()
        self.watchdog.register("detect_test", timeout=0.2, callback=callback)
        self.watchdog.start()
        time.sleep(0.5)
        self.watchdog.stop()

    def test_set_expiry_callback(self):
        callback = MagicMock()
        self.watchdog.register("callback_test", timeout=0.2)
        self.watchdog.set_expiry_callback("callback_test", callback)
        self.watchdog.start()
        time.sleep(0.5)
        self.watchdog.stop()

    def test_get_registered_devices(self):
        self.watchdog.register("device_1")
        self.watchdog.register("device_2")
        devices = self.watchdog.get_registered_devices()
        self.assertEqual(len(devices), 2)


class TestWatchdogExpiredError(unittest.TestCase):
    def test_exception_message(self):
        try:
            raise WatchdogExpiredError("device_123")
        except WatchdogExpiredError as e:
            self.assertIn("device_123", str(e))


if __name__ == "__main__":
    unittest.main()
