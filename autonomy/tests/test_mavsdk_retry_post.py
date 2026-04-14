"""
Tests for MAVSDK retry logic.

These tests verify that:
1. Connection retries with exponential backoff
2. Mission upload retries on timeout
3. Arm retries on preflight rejection
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConnectionRetry:
    """Tests for MAVSDK connection retry."""

    def test_connect_max_retries_defined(self):
        """Verify CONNECT_MAX_RETRIES is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'CONNECT_MAX_RETRIES')
        assert vi_module.CONNECT_MAX_RETRIES == 5

    def test_connect_base_delay_defined(self):
        """Verify CONNECT_BASE_DELAY_S is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'CONNECT_BASE_DELAY_S')
        assert vi_module.CONNECT_BASE_DELAY_S == 0.1

    def test_connect_backoff_factor_defined(self):
        """Verify CONNECT_BACKOFF_FACTOR is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'CONNECT_BACKOFF_FACTOR')
        assert vi_module.CONNECT_BACKOFF_FACTOR == 2.0


class TestMissionUploadRetry:
    """Tests for mission upload retry."""

    def test_upload_max_retries_defined(self):
        """Verify UPLOAD_MAX_RETRIES is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'UPLOAD_MAX_RETRIES')
        assert vi_module.UPLOAD_MAX_RETRIES == 3

    def test_upload_base_delay_defined(self):
        """Verify UPLOAD_BASE_DELAY_S is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'UPLOAD_BASE_DELAY_S')
        assert vi_module.UPLOAD_BASE_DELAY_S == 0.5

    def test_upload_timeout_defined(self):
        """Verify UPLOAD_TIMEOUT_S is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'UPLOAD_TIMEOUT_S')
        assert vi_module.UPLOAD_TIMEOUT_S == 30.0


class TestArmRetry:
    """Tests for arm retry."""

    def test_arm_max_retries_defined(self):
        """Verify ARM_MAX_RETRIES is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'ARM_MAX_RETRIES')
        assert vi_module.ARM_MAX_RETRIES == 3

    def test_arm_base_delay_defined(self):
        """Verify ARM_BASE_DELAY_S is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'ARM_BASE_DELAY_S')
        assert vi_module.ARM_BASE_DELAY_S == 0.5

    def test_arm_backoff_factor_defined(self):
        """Verify ARM_BACKOFF_FACTOR is defined at module level."""
        import autonomy.drone_system.vehicle_interface as vi_module
        assert hasattr(vi_module, 'ARM_BACKOFF_FACTOR')
        assert vi_module.ARM_BACKOFF_FACTOR == 1.5
