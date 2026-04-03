"""
Pytest configuration and fixtures for Skylink2 robustness tests.
"""

from __future__ import annotations

import json
import math
import os
import signal
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SKYLINK_ROOT = Path(__file__).resolve().parents[3]
if str(SKYLINK_ROOT) not in sys.path:
    sys.path.insert(0, str(SKYLINK_ROOT))


@pytest.fixture
def mock_mavsdk():
    mock = MagicMock()
    mock.System = MagicMock()
    mock.connect = AsyncMock()
    mock.core.connection_state = MagicMock()
    mock.telemetry.position = MagicMock()
    mock.telemetry.battery = MagicMock()
    mock.telemetry.armed = AsyncMock()
    mock.telemetry.flight_mode = AsyncMock()
    return mock


@pytest.fixture
def mock_gpio():
    gpio = MagicMock()
    gpio.BCM = 11
    gpio.OUT = 1
    gpio.LOW = 0
    gpio.HIGH = 1
    gpio.pin_state = {}
    gpio.setup = MagicMock()
    gpio.output = MagicMock()
    gpio.cleanup = MagicMock()
    return gpio


@pytest.fixture
def valid_calibration_json(tmp_path: Path) -> Path:
    calib = {
        "status": "calibrated",
        "camera_matrix": [
            [615.0, 0.0, 320.0],
            [0.0, 615.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "rms_error": 0.5,
    }
    path = tmp_path / "calib.json"
    path.write_text(json.dumps(calib))
    return path


@pytest.fixture
def placeholder_calibration_json(tmp_path: Path) -> Path:
    calib = {
        "status": "template",
        "camera_matrix": [
            [615.0, 0.0, 320.0],
            [0.0, 615.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
    }
    path = tmp_path / "placeholder.json"
    path.write_text(json.dumps(calib))
    return path


@pytest.fixture
def bad_rms_calibration_json(tmp_path: Path) -> Path:
    calib = {
        "status": "calibrated",
        "camera_matrix": [
            [615.0, 0.0, 320.0],
            [0.0, 615.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "rms_error": 3.5,
    }
    path = tmp_path / "bads_rms.json"
    path.write_text(json.dumps(calib))
    return path


@pytest.fixture
def invalid_focal_calibration_json(tmp_path: Path) -> Path:
    calib = {
        "status": "calibrated",
        "camera_matrix": [
            [0.0, 0.0, 320.0],
            [0.0, -615.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "rms_error": 0.3,
    }
    path = tmp_path / "bad_focal.json"
    path.write_text(json.dumps(calib))
    return path


@pytest.fixture
def baseline():
    from autonomy.drone_system.config import load_system_baseline
    return load_system_baseline()


@pytest.fixture
def mock_ads():
    ads = MagicMock()
    ads.contact_voltage = 12.5
    ads.battery_voltage = 12.5
    ads.simulate_failure = False
    ads.failure_count = 0
    return ads


@pytest.fixture
def observation_valid():
    from autonomy.drone_system.precision_landing import LandingTargetObservation
    return LandingTargetObservation(
        acquired=True,
        quality=0.95,
        forward_angle_rad=math.radians(5.0),
        right_angle_rad=math.radians(-3.0),
        range_m=10.0,
    )


@pytest.fixture
def observation_nan():
    from autonomy.drone_system.precision_landing import LandingTargetObservation
    return LandingTargetObservation(
        acquired=True,
        quality=0.95,
        forward_angle_rad=float('nan'),
        right_angle_rad=math.radians(-3.0),
        range_m=10.0,
    )


@pytest.fixture
def observation_inf():
    from autonomy.drone_system.precision_landing import LandingTargetObservation
    return LandingTargetObservation(
        acquired=True,
        quality=0.95,
        forward_angle_rad=float('inf'),
        right_angle_rad=math.radians(-3.0),
        range_m=10.0,
    )


@pytest.fixture
def observation_negative_range():
    from autonomy.drone_system.precision_landing import LandingTargetObservation
    return LandingTargetObservation(
        acquired=True,
        quality=0.95,
        forward_angle_rad=math.radians(5.0),
        right_angle_rad=math.radians(-3.0),
        range_m=-1.0,
    )


@pytest.fixture(autouse=True)
def reset_env():
    env_backup = os.environ.get("SKYLINK_PREFLIGHT_STRICT")
    yield
    if env_backup is not None:
        os.environ["SKYLINK_PREFLIGHT_STRICT"] = env_backup
    else:
        os.environ.pop("SKYLINK_PREFLIGHT_STRICT", None)
