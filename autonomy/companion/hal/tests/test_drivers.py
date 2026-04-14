import unittest
import time

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hal.drivers.mock_driver import (
    MockI2CDevice,
    MockGPIODevice,
    MockCameraDevice,
    MockMAVLinkDevice,
    MockGPSDevice,
    MockRangefinderDevice,
    MockADCDevice,
    create_mock_driver,
)
from hal.base import HealthStatus


class TestMockDrivers(unittest.TestCase):
    def test_mock_i2c_boot_shutdown(self):
        device = MockI2CDevice("test_i2c", 0x42, bus=1)
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertEqual(device.status.health, HealthStatus.HEALTHY)
        self.assertTrue(device.shutdown())
        self.assertFalse(device.is_connected())

    def test_mock_i2c_read(self):
        device = MockI2CDevice("test_i2c", 0x42)
        device.boot()
        data = device.read_raw_data()
        self.assertIsNotNone(data)
        self.assertIsInstance(data, bytes)

    def test_mock_gpio_boot_shutdown(self):
        device = MockGPIODevice("test_gpio", 17, direction="in")
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_gpio_read_write(self):
        device = MockGPIODevice("test_gpio", 17, direction="in")
        device.boot()
        value = device.read()
        self.assertIn(value, [0, 1])

        device2 = MockGPIODevice("test_gpio_out", 18, direction="out")
        device2.boot()
        self.assertTrue(device2.write(1))

    def test_mock_camera_boot_shutdown(self):
        device = MockCameraDevice("test_camera", 0)
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_camera_capture(self):
        device = MockCameraDevice("test_camera", 0)
        device.boot()
        frame = device.capture_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame["width"], 640)
        self.assertEqual(frame["height"], 480)

    def test_mock_camera_calibration(self):
        device = MockCameraDevice("test_camera", 0)
        device.boot()
        calib = device.get_calibration()
        self.assertIsNotNone(calib)
        self.assertIn("rms_error", calib)

    def test_mock_mavlink_boot_shutdown(self):
        device = MockMAVLinkDevice("test_mavlink", "tcp:localhost:5760")
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_mavlink_connect(self):
        device = MockMAVLinkDevice("test_mavlink")
        device.boot()
        self.assertTrue(device.connect())

    def test_mock_mavlink_telemetry(self):
        device = MockMAVLinkDevice("test_mavlink")
        device.boot()
        device.connect()
        telemetry = device.get_telemetry()
        self.assertIsNotNone(telemetry)
        self.assertIn("lat", telemetry)
        self.assertIn("lon", telemetry)

    def test_mock_gps_boot_shutdown(self):
        device = MockGPSDevice("test_gps", 0x42)
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_gps_position(self):
        device = MockGPSDevice("test_gps", 0x42)
        device.boot()
        pos = device.get_position()
        self.assertIsNotNone(pos)
        self.assertIn("lat", pos)
        self.assertIn("lon", pos)

    def test_mock_gps_satellite_count(self):
        device = MockGPSDevice("test_gps", 0x42)
        device.boot()
        count = device.get_satellite_count()
        self.assertEqual(count, 12)

    def test_mock_rangefinder_boot_shutdown(self):
        device = MockRangefinderDevice("test_rf", 0x10)
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_rangefinder_distance(self):
        device = MockRangefinderDevice("test_rf", 0x10)
        device.boot()
        dist = device.get_distance()
        self.assertIsNotNone(dist)
        self.assertGreaterEqual(dist, 0.0)
        self.assertLessEqual(dist, 100.0)

    def test_mock_adc_boot_shutdown(self):
        device = MockADCDevice("test_adc", 0x48)
        self.assertTrue(device.boot())
        self.assertTrue(device.is_connected())
        self.assertTrue(device.shutdown())

    def test_mock_adc_voltage(self):
        device = MockADCDevice("test_adc", 0x48)
        device.boot()
        voltage = device.read_voltage(0)
        self.assertIsNotNone(voltage)
        self.assertGreaterEqual(voltage, 0.0)
        self.assertLessEqual(voltage, 5.0)

    def test_mock_adc_raw(self):
        device = MockADCDevice("test_adc", 0x48)
        device.boot()
        raw = device.read_raw(0)
        self.assertIsNotNone(raw)
        self.assertGreaterEqual(raw, 0)


class TestCreateMockDriver(unittest.TestCase):
    def test_create_gpio(self):
        device = create_mock_driver("gpio", "test_gpio", gpio_pin=17)
        self.assertIsInstance(device, MockGPIODevice)

    def test_create_i2c(self):
        device = create_mock_driver("i2c", "test_i2c", i2c_address=0x42)
        self.assertIsInstance(device, MockI2CDevice)

    def test_create_camera(self):
        device = create_mock_driver("camera", "test_camera")
        self.assertIsInstance(device, MockCameraDevice)

    def test_create_mavlink(self):
        device = create_mock_driver("mavlink", "test_mavlink")
        self.assertIsInstance(device, MockMAVLinkDevice)

    def test_create_gps(self):
        device = create_mock_driver("gps", "test_gps", i2c_address=0x42)
        self.assertIsInstance(device, MockGPSDevice)

    def test_create_rangefinder(self):
        device = create_mock_driver("rangefinder", "test_rf", i2c_address=0x10)
        self.assertIsInstance(device, MockRangefinderDevice)

    def test_create_adc(self):
        device = create_mock_driver("adc", "test_adc", i2c_address=0x48)
        self.assertIsInstance(device, MockADCDevice)

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            create_mock_driver("invalid", "test_device")


if __name__ == "__main__":
    unittest.main()
