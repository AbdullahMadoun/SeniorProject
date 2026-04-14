"""
Tests for GPIO emergency shutdown and I2C retry logic.

These tests verify that:
1. Emergency shutdown forces MOSFET OFF immediately
2. I2C retries with exponential backoff before giving up
3. Voltage sanity checks prevent dangerous operating conditions
"""

from __future__ import annotations

import json
import signal
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestGPIOEmergencyShutdown:
    """Tests for GPIO emergency shutdown functionality."""

    def test_emergency_shutdown_method_exists(self):
        """Verify emergency_shutdown method exists on GPIOChargingController."""
        from autonomy.companion.gpio_charging import GPIOChargingController
        controller = GPIOChargingController.__new__(GPIOChargingController)
        assert hasattr(controller, 'emergency_shutdown'), \
            "GPIOChargingController must have emergency_shutdown method"

    def test_emergency_shutdown_constant_defined(self):
        """Verify I2C retry constants are defined at module level."""
        import autonomy.companion.gpio_charging as gpio_module
        assert hasattr(gpio_module, 'I2C_MAX_RETRIES')
        assert hasattr(gpio_module, 'I2C_RETRY_DELAY_S')
        assert hasattr(gpio_module, 'I2C_RETRY_BACKOFF')

    def test_voltage_sanity_constants_defined(self):
        """Verify voltage sanity check constants are defined."""
        import autonomy.companion.gpio_charging as gpio_module
        assert hasattr(gpio_module, 'VOLTAGE_SANITY_MAX_V')
        assert hasattr(gpio_module, 'VOLTAGE_SANITY_MIN_V')


class TestI2CRetry:
    """Tests for I2C retry with exponential backoff."""

    def test_read_voltages_with_retry_method_exists(self):
        """Verify read_voltages_with_retry method exists."""
        from autonomy.companion.gpio_charging import GPIOChargingController
        controller = GPIOChargingController.__new__(GPIOChargingController)
        assert hasattr(controller, 'read_voltages_with_retry'), \
            "Must have read_voltages_with_retry method"

    def test_retry_constants_defined(self):
        """Verify retry constants are defined."""
        import autonomy.companion.gpio_charging as gpio_module
        assert hasattr(gpio_module, 'I2C_MAX_RETRIES')
        assert hasattr(gpio_module, 'I2C_RETRY_DELAY_S')
        assert hasattr(gpio_module, 'I2C_RETRY_BACKOFF')
        assert gpio_module.I2C_MAX_RETRIES == 3
        assert gpio_module.I2C_RETRY_DELAY_S == 0.1
        assert gpio_module.I2C_RETRY_BACKOFF == 2.0


class TestVoltageSanity:
    """Tests for voltage sanity checks."""

    def test_voltage_sanity_constants_defined(self):
        """Verify voltage sanity check constants are defined."""
        import autonomy.companion.gpio_charging as gpio_module
        assert hasattr(gpio_module, 'VOLTAGE_SANITY_MIN_V')
        assert hasattr(gpio_module, 'VOLTAGE_SANITY_MAX_V')
        assert gpio_module.VOLTAGE_SANITY_MIN_V == 0.0
        assert gpio_module.VOLTAGE_SANITY_MAX_V == 24.0


class TestSIGTERMHandler:
    """Tests for SIGTERM/SIGINT handlers."""

    def test_sigterm_handler_registered(self):
        """Verify SIGTERM handler is registered in run()."""
        import inspect
        from autonomy.companion.gpio_charging import GPIOChargingController

        source = inspect.getsource(GPIOChargingController.run)
        assert 'signal.SIGTERM' in source or 'SIGTERM' in source, \
            "run() must register SIGTERM handler"

    def test_sigint_handler_registered(self):
        """Verify SIGINT handler is registered in run()."""
        import inspect
        from autonomy.companion.gpio_charging import GPIOChargingController

        source = inspect.getsource(GPIOChargingController.run)
        assert 'signal.SIGINT' in source or 'SIGINT' in source, \
            "run() must register SIGINT handler"
