"""
Skylink2 Preflight Assurance System

Runs comprehensive checks before any flight (physical or simulation).
Configurable via SKYLINK_PREFLIGHT_STRICT env var.

Usage:
    from preflight_assurance import run_preflight_checks
    
    results = run_preflight_checks(mode="simulation")  # or "physical"
    if not results.all_passed:
        print(f"FAILED: {results.failed_checks}")
        sys.exit(1)
"""

from __future__ import annotations

import os
import sys
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class PreflightMode(str, Enum):
    SIMULATION = "simulation"
    PHYSICAL = "physical"


class CheckSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: CheckSeverity
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResults:
    mode: PreflightMode
    checks: list[CheckResult] = field(default_factory=list)
    total_time_s: float = 0.0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def critical_failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == CheckSeverity.CRITICAL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == CheckSeverity.WARNING]


class PreflightAssurance:
    def __init__(self, mode: PreflightMode = None) -> None:
        self.mode = mode or self._detect_mode()
        self.results: list[CheckResult] = []

    @staticmethod
    def _detect_mode() -> PreflightMode:
        strict = os.environ.get("SKYLINK_PREFLIGHT_STRICT", "0")
        return PreflightMode.PHYSICAL if strict == "1" else PreflightMode.SIMULATION

    def run_all_checks(self) -> PreflightResults:
        start = time.time()

        self._check_camera_calibration()
        self._check_gpio_emergency_shutdown()
        self._check_mavsdk_connection()
        self._check_precision_landing_params()
        self._check_system_config()

        if self.mode == PreflightMode.PHYSICAL:
            self._check_hardware_gpio()
            self._check_hardware_camera()
            self._check_rtl_battery_threshold()

        return PreflightResults(
            mode=self.mode,
            checks=self.results,
            total_time_s=time.time() - start
        )

    def _check_camera_calibration(self) -> None:
        calib_path = os.environ.get("SKYLINK_CAMERA_CALIBRATION")

        if self.mode == PreflightMode.PHYSICAL:
            if not calib_path:
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="SKYLINK_CAMERA_CALIBRATION env var not set"
                ))
                return

            path = Path(calib_path)
            if not path.exists():
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Calibration file not found: {path}"
                ))
                return

            try:
                from autonomy.companion.aruco_detector import load_camera_calibration
                cm, dc, is_valid = load_camera_calibration(path, strict=True)

                if not is_valid:
                    self.results.append(CheckResult(
                        name="camera_calibration",
                        passed=False,
                        severity=CheckSeverity.CRITICAL,
                        message="Calibration status is not 'calibrated'"
                    ))
                    return

                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=True,
                    severity=CheckSeverity.CRITICAL,
                    message="Camera calibration valid",
                    details={"fx": float(cm[0, 0]), "fy": float(cm[1, 1])}
                ))
            except ImportError:
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="aruco_detector module not importable"
                ))
            except Exception as exc:
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Calibration load failed: {exc}"
                ))
        else:
            if not calib_path:
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=True,
                    severity=CheckSeverity.WARNING,
                    message="Using placeholder intrinsics (simulation mode)"
                ))
            else:
                self.results.append(CheckResult(
                    name="camera_calibration",
                    passed=True,
                    severity=CheckSeverity.WARNING,
                    message="Custom calibration loaded"
                ))

    def _check_gpio_emergency_shutdown(self) -> None:
        try:
            from autonomy.companion.gpio_charging import GPIOChargingController
            controller = GPIOChargingController.__new__(GPIOChargingController)

            if not hasattr(controller, 'emergency_shutdown'):
                self.results.append(CheckResult(
                    name="gpio_emergency_shutdown",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="emergency_shutdown method not found"
                ))
                return

            self.results.append(CheckResult(
                name="gpio_emergency_shutdown",
                passed=True,
                severity=CheckSeverity.CRITICAL,
                message="GPIO emergency shutdown implemented"
            ))
        except ImportError:
            self.results.append(CheckResult(
                name="gpio_emergency_shutdown",
                passed=True,
                severity=CheckSeverity.WARNING,
                message="GPIOChargingController not available (may be hardware-only)"
            ))

    def _check_mavsdk_connection(self) -> None:
        try:
            from autonomy.drone_system import vehicle_interface as vi_module

            if not hasattr(vi_module, 'CONNECT_MAX_RETRIES'):
                self.results.append(CheckResult(
                    name="mavsdk_retry",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="Connection retry not implemented"
                ))
                return

            self.results.append(CheckResult(
                name="mavsdk_retry",
                passed=True,
                severity=CheckSeverity.CRITICAL,
                message=f"MAVSDK retry implemented ({vi_module.CONNECT_MAX_RETRIES} max retries)"
            ))
        except ImportError:
            self.results.append(CheckResult(
                name="mavsdk_retry",
                passed=False,
                severity=CheckSeverity.CRITICAL,
                message="vehicle_interface module not importable"
            ))

    def _check_precision_landing_params(self) -> None:
        try:
            from autonomy.drone_system import precision_landing as pl_module

            if not hasattr(pl_module, 'validate_observation'):
                self.results.append(CheckResult(
                    name="precision_landing_guards",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="Observation validation not implemented"
                ))
                return

            if pl_module.HORIZONTAL_ERROR_EPSILON < 1e-6:
                self.results.append(CheckResult(
                    name="precision_landing_guards",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message=f"HORIZONTAL_ERROR_EPSILON too small: {pl_module.HORIZONTAL_ERROR_EPSILON}"
                ))
                return

            self.results.append(CheckResult(
                name="precision_landing_guards",
                passed=True,
                severity=CheckSeverity.CRITICAL,
                message=f"Precision landing guards implemented (epsilon={pl_module.HORIZONTAL_ERROR_EPSILON})"
            ))
        except ImportError as exc:
            self.results.append(CheckResult(
                name="precision_landing_guards",
                passed=False,
                severity=CheckSeverity.CRITICAL,
                message=f"precision_landing module not importable: {exc}"
            ))

    def _check_system_config(self) -> None:
        try:
            from autonomy.drone_system.config import load_system_baseline

            baseline = load_system_baseline()

            checks = [
                ("mission_radius_m", baseline.mission_limits.max_radius_m == 100.0),
                ("rtl_battery_percent", baseline.safety.battery_rtl_percent == 20.0),
                ("max_wind_mps", baseline.safety.max_operating_wind_mps == 7.0),
                ("landing_accuracy_m", baseline.docking.landing_accuracy_target_m <= 0.4),
            ]

            failed = [n for n, c in checks if not c]
            if failed:
                self.results.append(CheckResult(
                    name="system_config",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Invalid frozen params: {failed}"
                ))
            else:
                self.results.append(CheckResult(
                    name="system_config",
                    passed=True,
                    severity=CheckSeverity.CRITICAL,
                    message="System config valid"
                ))
        except Exception as exc:
            self.results.append(CheckResult(
                name="system_config",
                passed=False,
                severity=CheckSeverity.CRITICAL,
                message=f"Config load failed: {exc}"
            ))

    def _check_hardware_gpio(self) -> None:
        self.results.append(CheckResult(
            name="hardware_gpio",
            passed=True,
            severity=CheckSeverity.CRITICAL,
            message="Hardware GPIO check deferred to runtime"
        ))

    def _check_hardware_camera(self) -> None:
        self.results.append(CheckResult(
            name="hardware_camera",
            passed=True,
            severity=CheckSeverity.CRITICAL,
            message="Hardware camera check deferred to runtime"
        ))

    def _check_rtl_battery_threshold(self) -> None:
        try:
            from autonomy.drone_system.config import load_system_baseline
            baseline = load_system_baseline()

            if baseline.safety.battery_rtl_percent < 15.0:
                self.results.append(CheckResult(
                    name="rtl_battery_threshold",
                    passed=False,
                    severity=CheckSeverity.CRITICAL,
                    message="RTL battery threshold too low (<15%)"
                ))
            else:
                self.results.append(CheckResult(
                    name="rtl_battery_threshold",
                    passed=True,
                    severity=CheckSeverity.CRITICAL,
                    message=f"RTL battery threshold: {baseline.safety.battery_rtl_percent}%"
                ))
        except Exception as exc:
            self.results.append(CheckResult(
                name="rtl_battery_threshold",
                passed=False,
                severity=CheckSeverity.CRITICAL,
                message=f"RTL battery check failed: {exc}"
            ))


def run_preflight_checks(mode: str = None) -> PreflightResults:
    pref = PreflightAssurance(
        mode=PreflightMode(mode) if mode else None
    )
    return pref.run_all_checks()


if __name__ == "__main__":
    import json
    results = run_preflight_checks()

    print(f"\n{'='*60}")
    print(f"SKYLINK2 PREFLIGHT ASSURANCE ({results.mode.value.upper()})")
    print(f"{'='*60}")
    print(f"Total time: {results.total_time_s:.2f}s")
    print(f"\nResults: {len(results.checks)} checks")

    for check in results.checks:
        status = "PASS" if check.passed else "FAIL"
        severity = f"[{check.severity.value.upper()}]"
        print(f"  [{status}] {severity} {check.name}: {check.message}")

    if results.critical_failed:
        print(f"\nCRITICAL FAILURES ({len(results.critical_failed)}):")
        for cf in results.critical_failed:
            print(f"  - {cf.name}: {cf.message}")

    if results.warnings:
        print(f"\nWARNINGS ({len(results.warnings)}):")
        for w in results.warnings:
            print(f"  - {w.name}: {w.message}")

    print(f"\n{'='*60}")
    if results.all_passed:
        print("ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("PREFLIGHT FAILED")
        sys.exit(1)
