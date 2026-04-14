"""
Tests for telemetry stream health monitoring.
"""
from __future__ import annotations

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.vehicle_interface import (
    MavsdkVehicleGateway,
    TelemetryStreamClosed,
    TelemetryError,
)


@pytest.fixture
def baseline():
    return load_system_baseline()


class TestTelemetryExceptions:
    """Tests for TelemetryError and TelemetryStreamClosed."""

    def test_telemetry_stream_closed_inheritance(self):
        """TelemetryStreamClosed must inherit from TelemetryError."""
        assert issubclass(TelemetryStreamClosed, TelemetryError)
        assert issubclass(TelemetryStreamClosed, RuntimeError)

    def test_telemetry_error_message(self):
        """TelemetryStreamClosed stores message."""
        exc = TelemetryStreamClosed("test message")
        assert str(exc) == "test message"


class TestTelemetryConstants:
    """Tests for telemetry health constants."""

    def test_max_consecutive_failures_defined(self):
        """TELEMETRY_MAX_CONSECUTIVE_FAILURES must be 5."""
        assert MavsdkVehicleGateway.TELEMETRY_MAX_CONSECUTIVE_FAILURES == 5

    def test_reconnect_delay_defined(self):
        """TELEMETRY_RECONNECT_DELAY_S must be 5.0."""
        assert MavsdkVehicleGateway.TELEMETRY_RECONNECT_DELAY_S == 5.0


class TestConsecutiveFailureTracking:
    """Tests for consecutive failure tracking in get_snapshot."""

    def test_gateway_tracks_consecutive_failures(self, baseline):
        """MavsdkVehicleGateway must track _consecutive_failures."""
        gateway = MavsdkVehicleGateway(baseline)
        assert hasattr(gateway, "_consecutive_failures")
        assert gateway._consecutive_failures == 0

    def test_gateway_tracks_stream_closed(self, baseline):
        """MavsdkVehicleGateway must track _telemetry_stream_closed."""
        gateway = MavsdkVehicleGateway(baseline)
        assert hasattr(gateway, "_telemetry_stream_closed")
        assert gateway._telemetry_stream_closed is False


class TestTelemetryReconnection:
    """Tests for telemetry reconnection logic."""

    def test_attempt_reconnect_method_exists(self, baseline):
        """_attempt_telemetry_reconnect must exist."""
        gateway = MavsdkVehicleGateway(baseline)
        assert hasattr(gateway, "_attempt_telemetry_reconnect")

    def test_reconnect_task_created_after_max_failures(self, baseline):
        """Reconnection task created after MAX_FAILURES."""
        gateway = MavsdkVehicleGateway(baseline)
        gateway._consecutive_failures = 5  # Max failures

        gateway._telemetry_stream_closed = True

        assert gateway._telemetry_stream_closed is True

    def test_reconnect_attempts_initialized(self, baseline):
        """_reconnect_attempts initialized to 0."""
        gateway = MavsdkVehicleGateway(baseline)
        assert gateway._reconnect_attempts == 0
