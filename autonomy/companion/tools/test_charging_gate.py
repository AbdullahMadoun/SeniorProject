#!/usr/bin/env python3
"""IS3 charging gate verification: asserts charge_enabled follows contact-pin state.

Tests the core safety invariant of GPIOChargingController: the charge-enable
signal must track the dock contact pin, not just battery state.

Design notes
------------
GPIOChargingController.evaluate() is a pure function of two voltage values;
it does not touch GPIO, I2C, or any hardware resource.  This allows the full
gate logic to be verified without physical pin manipulation.

A second test exercises the full software path (setup -> read -> decide -> apply)
using the automatic mock fallback: SKYLINK_FORCE_MOCK_GPIO=1 forces all four
load_*() helpers (gpio, board, busio, ads) to return mock objects, as verified
in mock_rpi.py lines 295, 302, 309, 316.  MockADS1115.channel_values is a plain
dict, so test voltage injection is deterministic and hardware-free.

Hardware state required at test start
--------------------------------------
- No hardware state required for any test.  Tests 1-4 call evaluate()
  directly (pure function, no hardware path).  Test 5 sets
  SKYLINK_FORCE_MOCK_GPIO=1 before constructing the controller, forcing
  all backends to mock regardless of what is installed.
- The test does NOT toggle physical GPIO; charge_enable_pin BCM 17 is
  never driven HIGH during this run.

Exit codes:
  0 -- all assertions passed
  1 -- at least one assertion failed (reason printed to stderr)
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Ensure repo root is importable when run as a script
if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from autonomy.companion.gpio_charging import (
    ChargingConfig,
    ChargingDecision,
    GPIOChargingController,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASSED: list[str] = []
_FAILED: list[str] = []


def _assert(name: str, condition: bool, detail: str = "") -> None:
    """Record a named assertion; print result immediately for live feedback."""
    if condition:
        _PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        _FAILED.append(name)
        msg = f"  FAIL  {name}" + (f": {detail}" if detail else "")
        print(msg, file=sys.stderr)


def _make_controller(battery_nominal_v: float = 16.8) -> GPIOChargingController:
    config = ChargingConfig(
        contact_threshold_v=0.5,
        battery_nominal_v=battery_nominal_v,
        battery_tolerance_v=1.5,
    )
    return GPIOChargingController(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_contact_absent_disables_charging() -> None:
    """Test 1 (IS3-A): charge_enabled=False when contact voltage is below threshold.

    Physical analogue: drone not on dock, contact pin reads LOW.
    """
    ctrl = _make_controller()
    decision: ChargingDecision = ctrl.evaluate(
        contact_voltage_v=0.0,      # below 0.5 V threshold
        battery_voltage_v=16.8,     # nominal, in range
    )
    _assert(
        "IS3-A: contact_absent -> charge_enabled=False",
        not decision.charge_enabled,
        f"got charge_enabled={decision.charge_enabled!r}, reason={decision.reason!r}",
    )
    _assert(
        "IS3-A: contact_detected=False",
        not decision.contact_detected,
        f"got contact_detected={decision.contact_detected!r}",
    )


def test_contact_present_enables_charging() -> None:
    """Test 2 (IS3-B): charge_enabled=True when contact voltage is above threshold
    and battery is within the nominal charging band.

    Physical analogue: drone seated on dock, contact pin reads HIGH.
    """
    ctrl = _make_controller()
    decision: ChargingDecision = ctrl.evaluate(
        contact_voltage_v=1.5,      # well above 0.5 V threshold
        battery_voltage_v=16.8,     # nominal
    )
    _assert(
        "IS3-B: contact_present + battery_ok -> charge_enabled=True",
        decision.charge_enabled,
        f"got charge_enabled={decision.charge_enabled!r}, reason={decision.reason!r}",
    )
    _assert(
        "IS3-B: contact_detected=True",
        decision.contact_detected,
        f"got contact_detected={decision.contact_detected!r}",
    )


def test_contact_present_but_battery_out_of_range_disables_charging() -> None:
    """Test 3 (IS3-C): charge_enabled=False when contact present but battery voltage
    is outside the safe charging band.  Guards against charging a damaged pack.
    """
    ctrl = _make_controller()
    decision: ChargingDecision = ctrl.evaluate(
        contact_voltage_v=1.5,
        battery_voltage_v=10.0,     # far outside nominal 16.8 +/- 1.5 V
    )
    _assert(
        "IS3-C: contact_present + battery_out_of_range -> charge_enabled=False",
        not decision.charge_enabled,
        f"got charge_enabled={decision.charge_enabled!r}, reason={decision.reason!r}",
    )
    _assert(
        "IS3-C: battery_in_range=False",
        not decision.battery_in_range,
        f"got battery_in_range={decision.battery_in_range!r}",
    )


def test_threshold_boundary_is_strict_greater_than() -> None:
    """Test 4 (IS3-D): contact voltage exactly at threshold does NOT enable charging.

    evaluate() uses '>' not '>=', so threshold voltage itself is insufficient.
    """
    ctrl = _make_controller()
    decision: ChargingDecision = ctrl.evaluate(
        contact_voltage_v=0.5,      # exactly at threshold -- must NOT trigger
        battery_voltage_v=16.8,
    )
    _assert(
        "IS3-D: contact_voltage == threshold -> charge_enabled=False (strict >)",
        not decision.charge_enabled,
        f"got charge_enabled={decision.charge_enabled!r}",
    )


def test_full_mock_path_contact_state_change() -> None:
    """Test 5 (IS3-E): full software path via mock ADS -- channel_values written
    directly to simulate contact-pin state change without hardware.

    SKYLINK_FORCE_MOCK_GPIO=1 forces all four load_*() helpers to return mock
    objects (verified in mock_rpi.py lines 295, 302, 309, 316), making this
    test fully deterministic on any host, including Pi with real hardware
    installed.

    Verifies setup() -> MockAnalogIn.voltage -> evaluate() -> apply() chain.
    """
    os.environ["SKYLINK_FORCE_MOCK_GPIO"] = "1"
    config = ChargingConfig(
        contact_threshold_v=0.5,
        battery_nominal_v=16.8,
        battery_tolerance_v=1.5,
        cycles=1,
        output_dir=Path("/tmp/skylink_test_charging"),
    )
    ctrl = GPIOChargingController(config)
    ctrl.setup()

    # Contact absent: default channel_values[0] == 0.0
    ctrl._ads_device.channel_values[0] = 0.0    # contact channel
    ctrl._ads_device.channel_values[1] = 16.8   # battery channel
    decision_off = ctrl.run_cycle()
    _assert(
        "IS3-E: mock path, contact=0V -> charge_enabled=False",
        not decision_off.charge_enabled,
        f"got {decision_off.charge_enabled!r}",
    )

    # Contact present: drive contact channel above threshold
    ctrl._ads_device.channel_values[0] = 1.5
    decision_on = ctrl.run_cycle()
    _assert(
        "IS3-E: mock path, contact=1.5V -> charge_enabled=True",
        decision_on.charge_enabled,
        f"got {decision_on.charge_enabled!r}",
    )

    try:
        ctrl.GPIO.cleanup()
    except Exception:
        pass
    os.environ.pop("SKYLINK_FORCE_MOCK_GPIO", None)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    tests = [
        test_contact_absent_disables_charging,
        test_contact_present_enables_charging,
        test_contact_present_but_battery_out_of_range_disables_charging,
        test_threshold_boundary_is_strict_greater_than,
        test_full_mock_path_contact_state_change,
    ]

    print("=== IS3 Charging Gate Test ===\n")
    for test_fn in tests:
        print(f"[{test_fn.__name__}]")
        try:
            test_fn()
        except Exception:
            _FAILED.append(test_fn.__name__)
            traceback.print_exc(file=sys.stderr)
        print()

    print(f"Results: {len(_PASSED)} passed, {len(_FAILED)} failed")
    if _FAILED:
        print(f"FAILED: {', '.join(_FAILED)}", file=sys.stderr)
        sys.exit(1)
    print("ALL PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
