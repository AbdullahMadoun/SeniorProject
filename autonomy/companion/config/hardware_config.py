from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import os
import logging

try:
    import tomllib
except ImportError:
    import tomli as tomllib

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    device_id: str
    device_type: str
    enabled: bool = True
    use_mock: Optional[bool] = None
    connection_string: Optional[str] = None
    i2c_address: Optional[int] = None
    i2c_bus: int = 1
    gpio_pin: Optional[int] = None
    gpio_direction: str = "in"
    camera_index: int = 0
    width: int = 640
    height: int = 480
    min_distance: float = 0.0
    max_distance: float = 100.0
    model: str = "tfmini"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthMonitorConfig:
    enabled: bool = True
    check_interval: float = 5.0
    offline_threshold: float = 30.0
    degraded_threshold: int = 3


@dataclass
class WatchdogConfig:
    enabled: bool = True
    timeout: float = 10.0
    tick_interval: float = 1.0


@dataclass
class HardwareProfile:
    name: str
    description: str = ""
    devices: List[DeviceConfig] = field(default_factory=list)
    health_monitor: HealthMonitorConfig = field(default_factory=HealthMonitorConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)

    def get_device(self, device_id: str) -> Optional[DeviceConfig]:
        for device in self.devices:
            if device.device_id == device_id:
                return device
        return None

    def get_devices_by_type(self, device_type: str) -> List[DeviceConfig]:
        return [d for d in self.devices if d.device_type == device_type and d.enabled]

    def get_enabled_devices(self) -> List[DeviceConfig]:
        return [d for d in self.devices if d.enabled]


def load_profile(path: str) -> HardwareProfile:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        logger.error(f"Profile not found: {path}")
        raise
    except Exception as e:
        logger.error(f"Failed to load profile {path}: {e}")
        raise

    profile = HardwareProfile(
        name=data.get("name", "unnamed"),
        description=data.get("description", ""),
    )

    health_data = data.get("health_monitor", {})
    profile.health_monitor = HealthMonitorConfig(
        enabled=health_data.get("enabled", True),
        check_interval=health_data.get("check_interval", 5.0),
        offline_threshold=health_data.get("offline_threshold", 30.0),
        degraded_threshold=health_data.get("degraded_threshold", 3),
    )

    watchdog_data = data.get("watchdog", {})
    profile.watchdog = WatchdogConfig(
        enabled=watchdog_data.get("enabled", True),
        timeout=watchdog_data.get("timeout", 10.0),
        tick_interval=watchdog_data.get("tick_interval", 1.0),
    )

    for device_data in data.get("devices", []):
        device = DeviceConfig(
            device_id=device_data["device_id"],
            device_type=device_data["device_type"],
            enabled=device_data.get("enabled", True),
            use_mock=device_data.get("use_mock"),
            connection_string=device_data.get("connection_string"),
            i2c_address=device_data.get("i2c_address"),
            i2c_bus=device_data.get("i2c_bus", 1),
            gpio_pin=device_data.get("gpio_pin"),
            gpio_direction=device_data.get("gpio_direction", "in"),
            camera_index=device_data.get("camera_index", 0),
            width=device_data.get("width", 640),
            height=device_data.get("height", 480),
            min_distance=device_data.get("min_distance", 0.0),
            max_distance=device_data.get("max_distance", 100.0),
            model=device_data.get("model", "tfmini"),
            metadata=device_data.get("metadata", {}),
        )
        profile.devices.append(device)

    return profile


def get_default_profile_path(profile_name: str = "simulation") -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "config", f"hardware_profile_{profile_name}.toml")


def load_default_profile(profile_name: str = "simulation") -> HardwareProfile:
    path = get_default_profile_path(profile_name)
    return load_profile(path)
