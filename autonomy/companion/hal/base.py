from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Callable
import threading
import time


class HealthStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    OFFLINE = "offline"


@dataclass
class HardwareStatus:
    device_id: str
    device_type: str
    health: HealthStatus = HealthStatus.UNKNOWN
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    boot_time: Optional[float] = None
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "health": self.health.value,
            "message": self.message,
            "metadata": self.metadata,
            "last_seen": self.last_seen,
            "boot_time": self.boot_time,
            "error_count": self.error_count,
        }


class HardwareDevice(ABC):
    def __init__(self, device_id: str, device_type: str):
        self._device_id = device_id
        self._device_type = device_type
        self._status = HardwareStatus(device_id=device_id, device_type=device_type)
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[HardwareStatus], None]] = []

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def device_type(self) -> str:
        return self._device_type

    @property
    def status(self) -> HardwareStatus:
        with self._lock:
            return self._status

    def _update_status(
        self,
        health: HealthStatus,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self._status.health = health
            self._status.message = message
            self._status.last_seen = time.time()
            if metadata:
                self._status.metadata.update(metadata)
            updated_status = self._status
        for callback in self._callbacks:
            callback(updated_status)

    def register_callback(self, callback: Callable[[HardwareStatus], None]) -> None:
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[HardwareStatus], None]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    @abstractmethod
    def boot(self) -> bool:
        pass

    @abstractmethod
    def shutdown(self) -> bool:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass

    def get_metadata(self) -> Dict[str, Any]:
        return self._status.metadata.copy()


class I2CSensor(HardwareDevice):
    def __init__(
        self,
        device_id: str,
        sensor_type: str,
        i2c_address: int,
        bus: int = 1,
    ):
        super().__init__(device_id, f"i2c_{sensor_type}")
        self._i2c_address = i2c_address
        self._bus = bus

    @property
    def i2c_address(self) -> int:
        return self._i2c_address

    @property
    def bus(self) -> int:
        return self._bus

    @abstractmethod
    def read_raw_data(self) -> Optional[bytes]:
        pass

    @abstractmethod
    def get_measurement(self) -> Optional[Dict[str, Any]]:
        pass


class GPIODevice(HardwareDevice):
    def __init__(self, device_id: str, gpio_pin: int, direction: str = "in"):
        super().__init__(device_id, "gpio")
        self._gpio_pin = gpio_pin
        self._direction = direction

    @property
    def gpio_pin(self) -> int:
        return self._gpio_pin

    @property
    def direction(self) -> str:
        return self._direction

    @abstractmethod
    def read(self) -> Optional[int]:
        pass

    @abstractmethod
    def write(self, value: int) -> bool:
        pass


class CameraDevice(HardwareDevice):
    def __init__(self, device_id: str, camera_index: int = 0):
        super().__init__(device_id, "camera")
        self._camera_index = camera_index

    @property
    def camera_index(self) -> int:
        return self._camera_index

    @abstractmethod
    def capture_frame(self) -> Optional[Any]:
        pass

    @abstractmethod
    def get_calibration(self) -> Optional[Dict[str, Any]]:
        pass


class MAVLinkDevice(HardwareDevice):
    def __init__(self, device_id: str, connection_string: str):
        super().__init__(device_id, "mavlink")
        self._connection_string = connection_string

    @property
    def connection_string(self) -> str:
        return self._connection_string

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def send_command(self, command: int, params: List[float]) -> bool:
        pass

    @abstractmethod
    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        pass


class GPSDevice(I2CSensor):
    def __init__(self, device_id: str, i2c_address: int, bus: int = 1):
        super().__init__(device_id, "gps", i2c_address, bus)

    @abstractmethod
    def get_position(self) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_satellite_count(self) -> int:
        pass


class RangefinderDevice(I2CSensor):
    def __init__(
        self,
        device_id: str,
        i2c_address: int,
        bus: int = 1,
        min_distance: float = 0.0,
        max_distance: float = 100.0,
    ):
        super().__init__(device_id, "rangefinder", i2c_address, bus)
        self._min_distance = min_distance
        self._max_distance = max_distance

    @property
    def min_distance(self) -> float:
        return self._min_distance

    @property
    def max_distance(self) -> float:
        return self._max_distance

    @abstractmethod
    def get_distance(self) -> Optional[float]:
        pass


class ADCDevice(I2CSensor):
    def __init__(self, device_id: str, i2c_address: int, bus: int = 1):
        super().__init__(device_id, "adc", i2c_address, bus)

    @abstractmethod
    def read_voltage(self, channel: int) -> Optional[float]:
        pass

    @abstractmethod
    def read_raw(self, channel: int) -> Optional[int]:
        pass
