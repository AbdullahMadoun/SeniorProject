from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np


DEFAULT_FRAME_WIDTH = 640
DEFAULT_FRAME_HEIGHT = 480
DEFAULT_CONTACT_VOLTAGE = 1.2
DEFAULT_BATTERY_VOLTAGE = 16.8


def _mock_env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mock_env_float(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class MockGPIOBackend:
    BCM = "BCM"
    BOARD = "BOARD"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0

    def __init__(self) -> None:
        self.mode: str | None = None
        self.pin_state: dict[int, dict[str, Any]] = {}

    def setmode(self, mode: str) -> None:
        self.mode = mode

    def setup(self, pin: int, direction: str, initial: int | None = None) -> None:
        self.pin_state[pin] = {
            "direction": direction,
            "value": self.LOW if initial is None else initial,
        }

    def output(self, pin: int, value: int) -> None:
        self.pin_state.setdefault(pin, {"direction": self.OUT, "value": self.LOW})
        self.pin_state[pin]["value"] = value

    def input(self, pin: int) -> int:
        return int(self.pin_state.get(pin, {}).get("value", self.LOW))

    def cleanup(self) -> None:
        self.pin_state.clear()
        self.mode = None


class MockBoardModule:
    SCL = "MOCK_SCL"
    SDA = "MOCK_SDA"


class MockI2C:
    def __init__(self, scl: Any, sda: Any) -> None:
        self.scl = scl
        self.sda = sda


class MockBusIOModule:
    def I2C(self, scl: Any, sda: Any) -> MockI2C:
        return MockI2C(scl=scl, sda=sda)


class MockADS1115:
    def __init__(self, i2c: MockI2C, *, gain: float | None = None) -> None:
        self.i2c = i2c
        self.gain = gain
        self.channel_values = {
            0: _mock_env_float("SKYLINK_MOCK_CONTACT_VOLTAGE", default=DEFAULT_CONTACT_VOLTAGE),
            1: _mock_env_float("SKYLINK_MOCK_BATTERY_VOLTAGE", default=DEFAULT_BATTERY_VOLTAGE),
            2: 0.0,
            3: 0.0,
        }


class MockADSModule:
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3
    ADS1115 = MockADS1115


class MockAnalogIn:
    def __init__(self, ads: MockADS1115, channel: int) -> None:
        self.ads = ads
        self.channel = channel

    @property
    def voltage(self) -> float:
        return float(self.ads.channel_values.get(self.channel, 0.0))


class MockVideoCapture:
    def __init__(self, source: Any = 0, *_args: Any, **_kwargs: Any) -> None:
        self.source = source
        self.width = DEFAULT_FRAME_WIDTH
        self.height = DEFAULT_FRAME_HEIGHT
        self._opened = True
        self._frame_index = 0

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self._opened:
            return False, None
        self._frame_index += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        gradient = np.linspace(0, 255, self.width, dtype=np.uint8)
        frame[:, :, 1] = gradient
        band_height = 28
        band_y = (self._frame_index * 7) % max(1, self.height - band_height)
        frame[band_y : band_y + band_height, :, 0] = 150
        frame[band_y : band_y + band_height, :, 2] = 225
        return True, frame

    def set(self, prop_id: int, value: float) -> bool:
        if prop_id == 3:
            self.width = int(value)
        elif prop_id == 4:
            self.height = int(value)
        return True

    def release(self) -> None:
        self._opened = False


class MockArucoModule:
    DICT_4X4_50 = "DICT_4X4_50"

    def getPredefinedDictionary(self, dictionary_id: Any) -> dict[str, Any]:
        return {"dictionary_id": dictionary_id}

    def DetectorParameters(self) -> SimpleNamespace:
        return SimpleNamespace()

    def detectMarkers(
        self,
        _frame: np.ndarray,
        _dictionary: Any,
        parameters: Any | None = None,
    ) -> tuple[list[np.ndarray], np.ndarray | None, list[np.ndarray]]:
        del parameters
        if _mock_env_flag("SKYLINK_MOCK_ARUCO_DETECTION", default=False):
            corners = np.array(
                [[[280.0, 200.0], [360.0, 200.0], [360.0, 280.0], [280.0, 280.0]]],
                dtype=np.float32,
            )
            ids = np.array([[0]], dtype=np.int32)
            return [corners], ids, []
        return [], None, []

    def estimatePoseSingleMarkers(
        self,
        corners: list[np.ndarray],
        marker_length: float,
        _camera_matrix: np.ndarray,
        _dist_coeffs: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, Any]:
        count = len(corners)
        rvecs = np.zeros((count, 1, 3), dtype=np.float32)
        tvecs = np.zeros((count, 1, 3), dtype=np.float32)
        for index in range(count):
            tvecs[index, 0, :] = np.array([0.05, -0.03, max(marker_length, 0.2)], dtype=np.float32)
        return rvecs, tvecs, None


class MockCV2Module:
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 16
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self) -> None:
        self.aruco = MockArucoModule()

    def VideoCapture(self, source: Any, *_args: Any, **_kwargs: Any) -> MockVideoCapture:
        return MockVideoCapture(source)

    def putText(
        self,
        image: np.ndarray,
        text: str,
        org: tuple[int, int],
        _font_face: int,
        _font_scale: float,
        color: tuple[int, int, int],
        _thickness: int,
        lineType: int | None = None,
    ) -> np.ndarray:
        del lineType
        y = max(0, min(image.shape[0] - 2, org[1]))
        x = max(0, min(image.shape[1] - 2, org[0]))
        width = min(image.shape[1] - x, max(12, len(text) * 5))
        image[y : y + 2, x : x + width, :] = np.array(color, dtype=np.uint8)
        return image

    def imwrite(self, filename: str | os.PathLike[str], image: np.ndarray) -> bool:
        target = Path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.save(target.with_suffix(target.suffix + ".npy"), image)
        return True

    def destroyAllWindows(self) -> None:
        return None


def _resolve_optional(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def load_gpio_module() -> tuple[Any, bool]:
    if _mock_env_flag("SKYLINK_FORCE_MOCK_GPIO"):
        return MockGPIOBackend(), True
    module = _resolve_optional("RPi.GPIO")
    return (module, False) if module is not None else (MockGPIOBackend(), True)


def load_board_module() -> tuple[Any, bool]:
    if _mock_env_flag("SKYLINK_FORCE_MOCK_GPIO"):
        return MockBoardModule(), True
    module = _resolve_optional("board")
    return (module, False) if module is not None else (MockBoardModule(), True)


def load_busio_module() -> tuple[Any, bool]:
    if _mock_env_flag("SKYLINK_FORCE_MOCK_GPIO"):
        return MockBusIOModule(), True
    module = _resolve_optional("busio")
    return (module, False) if module is not None else (MockBusIOModule(), True)


def load_ads_backend() -> tuple[Any, Any, bool]:
    if _mock_env_flag("SKYLINK_FORCE_MOCK_GPIO"):
        return MockADSModule(), MockAnalogIn, True
    ads_module = _resolve_optional("adafruit_ads1x15.ads1115")
    analog_in_module = _resolve_optional("adafruit_ads1x15.analog_in")
    if ads_module is not None and analog_in_module is not None:
        return ads_module, analog_in_module.AnalogIn, False
    return MockADSModule(), MockAnalogIn, True


def load_cv2_module() -> tuple[Any, bool]:
    if _mock_env_flag("SKYLINK_FORCE_MOCK_CAMERA"):
        return MockCV2Module(), True
    module = _resolve_optional("cv2")
    return (module, False) if module is not None else (MockCV2Module(), True)


def build_mock_camera_source(source: Any = 0) -> MockVideoCapture:
    return MockVideoCapture(source)
