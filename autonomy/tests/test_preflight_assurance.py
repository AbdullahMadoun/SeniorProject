"""
Tests for preflight assurance system.

These tests verify that:
1. Preflight checks run correctly in simulation mode
2. Preflight checks run correctly in physical mode
3. Critical checks are enforced in physical mode
4. Warning checks are advisory in simulation mode
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestPreflightMode:
    """Tests for preflight mode detection."""

    def test_detect_simulation_mode_default(self):
        """Default mode should be simulation when STRICT not set."""
        os.environ.pop("SKYLINK_PREFLIGHT_STRICT", None)
        from autonomy.drone_system.preflight_assurance import PreflightAssurance, PreflightMode

        pref = PreflightAssurance()
        assert pref.mode == PreflightMode.SIMULATION

    def test_detect_physical_mode_when_strict(self):
        """Mode should be physical when STRICT=1."""
        os.environ["SKYLINK_PREFLIGHT_STRICT"] = "1"
        from autonomy.drone_system.preflight_assurance import PreflightAssurance, PreflightMode

        pref = PreflightAssurance()
        assert pref.mode == PreflightMode.PHYSICAL

    def test_detect_simulation_mode_when_not_strict(self):
        """Mode should be simulation when STRICT=0."""
        os.environ["SKYLINK_PREFLIGHT_STRICT"] = "0"
        from autonomy.drone_system.preflight_assurance import PreflightAssurance, PreflightMode

        pref = PreflightAssurance()
        assert pref.mode == PreflightMode.SIMULATION


class TestPreflightGPIO:
    """Tests for GPIO emergency shutdown preflight check."""

    def test_gpio_emergency_shutdown_check_passes(self):
        """GPIO emergency shutdown check should pass when method exists."""
        from autonomy.drone_system.preflight_assurance import PreflightAssurance

        pref = PreflightAssurance()
        pref._check_gpio_emergency_shutdown()

        results = pref.results
        assert len(results) == 1
        assert results[0].name == "gpio_emergency_shutdown"
        assert results[0].passed is True


class TestPreflightMAVSDK:
    """Tests for MAVSDK retry preflight check."""

    def test_mavsdk_retry_check_passes(self):
        """MAVSDK retry check should pass when constants defined."""
        from autonomy.drone_system.preflight_assurance import PreflightAssurance

        pref = PreflightAssurance()
        pref._check_mavsdk_connection()

        results = pref.results
        assert len(results) == 1
        assert results[0].name == "mavsdk_retry"
        assert results[0].passed is True


class TestPreflightPrecisionLanding:
    """Tests for precision landing preflight check."""

    def test_precision_landing_guards_check_passes(self):
        """Precision landing guards check should pass when implemented."""
        from autonomy.drone_system.preflight_assurance import PreflightAssurance

        pref = PreflightAssurance()
        pref._check_precision_landing_params()

        results = pref.results
        assert len(results) == 1
        assert results[0].name == "precision_landing_guards"
        assert results[0].passed is True


class TestPreflightResults:
    """Tests for PreflightResults dataclass."""

    def test_all_passed_true_when_all_pass(self):
        """all_passed should be True when all checks pass."""
        from autonomy.drone_system.preflight_assurance import PreflightResults, CheckResult, CheckSeverity, PreflightMode

        results = PreflightResults(mode=PreflightMode.SIMULATION)
        results.checks = [
            CheckResult(name="test1", passed=True, severity=CheckSeverity.CRITICAL),
            CheckResult(name="test2", passed=True, severity=CheckSeverity.WARNING),
        ]

        assert results.all_passed is True

    def test_all_passed_false_when_one_fails(self):
        """all_passed should be False when any check fails."""
        from autonomy.drone_system.preflight_assurance import PreflightResults, CheckResult, CheckSeverity, PreflightMode

        results = PreflightResults(mode=PreflightMode.SIMULATION)
        results.checks = [
            CheckResult(name="test1", passed=True, severity=CheckSeverity.CRITICAL),
            CheckResult(name="test2", passed=False, severity=CheckSeverity.CRITICAL),
        ]

        assert results.all_passed is False

    def test_critical_failed_lists_only_critical_failures(self):
        """critical_failed should list only CRITICAL failures."""
        from autonomy.drone_system.preflight_assurance import PreflightResults, CheckResult, CheckSeverity, PreflightMode

        results = PreflightResults(mode=PreflightMode.SIMULATION)
        results.checks = [
            CheckResult(name="test1", passed=False, severity=CheckSeverity.CRITICAL),
            CheckResult(name="test2", passed=False, severity=CheckSeverity.WARNING),
        ]

        critical = results.critical_failed
        assert len(critical) == 1
        assert critical[0].name == "test1"


class TestRunPreflightChecks:
    """Tests for run_preflight_checks function."""

    def test_run_preflight_checks_returns_results(self):
        """run_preflight_checks should return PreflightResults."""
        from autonomy.drone_system.preflight_assurance import run_preflight_checks

        results = run_preflight_checks(mode="simulation")

        assert results is not None
        assert len(results.checks) > 0
        assert results.mode.value == "simulation"

    def test_run_preflight_checks_simulation_mode(self):
        """Simulation mode should allow placeholder calibration."""
        from autonomy.drone_system.preflight_assurance import run_preflight_checks

        results = run_preflight_checks(mode="simulation")

        calib_check = next((c for c in results.checks if c.name == "camera_calibration"), None)
        assert calib_check is not None
        assert calib_check.passed is True


class TestPhysicalPreflightThresholds:
    def test_rtl_battery_threshold_check_reads_safety_baseline(self):
        from autonomy.drone_system.preflight_assurance import PreflightAssurance, PreflightMode

        pref = PreflightAssurance(mode=PreflightMode.PHYSICAL)
        pref._check_rtl_battery_threshold()

        results = pref.results
        assert len(results) == 1
        assert results[0].name == "rtl_battery_threshold"
        assert results[0].passed is True
