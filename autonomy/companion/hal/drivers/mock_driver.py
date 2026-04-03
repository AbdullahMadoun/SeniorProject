from typing import Optional, Dict, Any, List
import time
import random

from ..base import (
    HardwareDevice,
    I2CSensor,
    GPIODevice,
    CameraDevice,
    MAVLinkDevice,
    GPSDevice,
    RangefinderDevice,
    ADCDevice,
    HealthStatus,
)


class MockI2CDevice(I2CSensor):
    def __init__(
        self,
        device_id: str,
        i2c_address: int,
        bus: int = 1,
        mock_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(device_id, "mock_i2c", i2c_address, bus)
        self._connected = False
        self._mock_data = mock_data or {}
        self._boot_time: Optional[float] = None

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._boot_time = time.time()
        self._update_status(
            HealthStatus.HEALTHY,
            message="Mock I2C device booted",
            metadata={"boot_time": self._boot_time},
        )
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock I2C device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None
        return b"\x00\x01\x02\x03"

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None
        return {"value": random.uniform(0, 100), "timestamp": time.time()}


class MockGPIODevice(GPIODevice):
    def __init__(self, device_id: str, gpio_pin: int, direction: str = "in"):
        super().__init__(device_id, gpio_pin, direction)
        self._connected = False
        self._value = 0

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock GPIO device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock GPIO device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read(self) -> Optional[int]:
        if not self._connected:
            return None
        self._value = random.randint(0, 1)
        return self._value

    def write(self, value: int) -> bool:
        if not self._connected:
            return False
        self._value = value
        return True


class MockCameraDevice(CameraDevice):
    def __init__(
        self,
        device_id: str,
        camera_index: int = 0,
        width: int = 640,
        height: int = 480,
    ):
        super().__init__(device_id, camera_index)
        self._connected = False
        self._width = width
        self._height = height
        self._calibration = {
            "rms_error": 0.5,
            "camera_matrix": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
            "dist_coeffs": [[0.1, -0.05, 0, 0, 0]],
        }

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock camera device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock camera device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def capture_frame(self) -> Optional[Any]:
        if not self._connected:
            return None
        return {"width": self._width, "height": self._height, "data": b"fake_frame_data"}

    def get_calibration(self) -> Optional[Dict[str, Any]]:
        return self._calibration.copy() if self._connected else None


class MockMAVLinkDevice(MAVLinkDevice):
    def __init__(self, device_id: str, connection_string: str = "tcp:localhost:5760"):
        super().__init__(device_id, connection_string)
        self._connected = False
        self._armed = False

    def boot(self) -> bool:
        time.sleep(0.02)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock MAVLink device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._armed = False
        self._update_status(HealthStatus.OFFLINE, message="Mock MAVLink device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock MAVLink connected")
        return True

    def send_command(self, command: int, params: List[float]) -> bool:
        if not self._connected:
            return False
        return True

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None
        return {
            "lat": 37.7749 + random.uniform(-0.01, 0.01),
            "lon": -122.4194 + random.uniform(-0.01, 0.01),
            "alt": 10.0 + random.uniform(-1, 1),
            "heading": random.uniform(0, 360),
            "speed": random.uniform(0, 10),
            "battery": random.uniform(20, 100),
        }


class MockGPSDevice(GPSDevice):
    def __init__(self, device_id: str, i2c_address: int = 0x42, bus: int = 1):
        super().__init__(device_id, i2c_address, bus)
        self._connected = False

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock GPS device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock GPS device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None
        return b"\x00\x01\x02\x03\x04\x05\x06\x07"

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        return self.get_position()

    def get_position(self) -> Optional[Dict[str, Any]]:
        if not self._connected:
            return None
        return {
            "lat": 37.7749,
            "lon": -122.4194,
            "alt": 10.0,
            "fix": 3,
            "satellites": 12,
        }

    def get_satellite_count(self) -> int:
        if not self._connected:
            return 0
        return 12


class MockRangefinderDevice(RangefinderDevice):
    def __init__(
        self,
        device_id: str,
        i2c_address: int = 0x10,
        bus: int = 1,
        min_distance: float = 0.0,
        max_distance: float = 100.0,
    ):
        super().__init__(device_id, i2c_address, bus, min_distance, max_distance)
        self._connected = False

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock rangefinder device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock rangefinder device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None
        return b"\x00\x00\x00\x00"

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        return {"distance": self.get_distance()}

    def get_distance(self) -> Optional[float]:
        if not self._connected:
            return None
        return random.uniform(self._min_distance, min(self._max_distance, 50.0))


class MockADCDevice(ADCDevice):
    def __init__(self, device_id: str, i2c_address: int = 0x48, bus: int = 1):
        super().__init__(device_id, i2c_address, bus)
        self._connected = False

    def boot(self) -> bool:
        time.sleep(0.01)
        self._connected = True
        self._update_status(HealthStatus.HEALTHY, message="Mock ADC device booted")
        return True

    def shutdown(self) -> bool:
        self._connected = False
        self._update_status(HealthStatus.OFFLINE, message="Mock ADC device shutdown")
        return True

    def is_connected(self) -> bool:
        return self._connected

    def read_raw_data(self) -> Optional[bytes]:
        if not self._connected:
            return None
        return b"\x00\x00"

    def get_measurement(self) -> Optional[Dict[str, Any]]:
        return {
            "channel0": self.read_voltage(0),
            "channel1": self.read_voltage(1),
        }

    def read_voltage(self, channel: int) -> Optional[float]:
        if not self._connected:
            return None
        return random.uniform(0.0, 5.0)

    def read_raw(self, channel: int) -> Optional[int]:
        if not self._connected:
            return None
        return random.randint(0, 32767)


def create_mock_driver(device_type: str, device_id: str, **kwargs) -> HardwareDevice:
    mock_classes = {
        "gpio": MockGPIODevice,
        "i2c": MockI2CDevice,
        "camera": MockCameraDevice,
        "mavlink": MockMAVLinkDevice,
        "gps": MockGPSDevice,
        "rangefinder": MockRangefinderDevice,
        "adc": MockADCDevice,
    }

    mock_class = mock_classes.get(device_type)
    if not mock_class:
        raise ValueError(f"Unknown device type for mock: {device_type}")

    return mock_class(device_id, **kwargs)
