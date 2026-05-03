#!/usr/bin/env python3
"""
test_rtl_monitor.py — Unit tests for autonomy/companion/rtl_monitor.py (IS2 proof).

Option 4 rationale
==================
SITL integration testing of rtl_monitor.py is blocked by PX4's single-partner-latch
architecture: PX4's GCS MAVLink port (udp:18570) maintains exactly one unicast partner
slot.  During a mission window the MAVSDK client inside the companion_sim Docker
container (127.0.0.1) holds that slot, so the Pi-from-NAT address never receives
BATTERY_STATUS.  We therefore prove IS2 via unit tests that inject synthetic MAVLink
messages through a MockConnection, exercising every logic branch in rtl_monitor.py
without a live PX4 stack.

Tests T1–T11
============
  T1  latch_vehicle_heartbeat       — vehicle HB accepted; target_system set
  T2  latch_skips_gcs_heartbeat     — GCS HB (type=6) logged as skipped; vehicle HB latches
  T3  latch_timeout_exits           — no vehicle HB within deadline → SystemExit(1)
  T4  battery_single_below_no_rtl   — 1 below-threshold reading: consecutive=1, no RTL
  T5  battery_debounce_fires_rtl    — 2 consecutive below → rtl_trigger + command sent
  T6  battery_reset_clears_count    — below, above, below: reset clears counter, no RTL
  T7  battery_unknown_skipped       — remaining=-1 → battery_unknown event, no RTL
  T8  wind_debounce_fires_rtl       — 2 consecutive WIND_COV above → rtl_trigger reason=wind
  T9  rtl_one_shot                  — 4 below messages: exactly one command_long_send
  T10 issue_rtl_confirmed           — ACK + RTL-mode HEARTBEAT → rtl_outcome: confirmed
  T11 issue_rtl_ack_timeout         — no ACK in queue → rtl_outcome: command_sent_ack_timeout
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest.mock
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure autonomy/companion is importable when run from repo root or tools/
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

import rtl_monitor  # noqa: E402  — path insert must precede this


# ===========================================================================
# Mock infrastructure
# ===========================================================================

class MockMessage:
    """Synthetic pymavlink message.  Routing fields as positional args; payload via kwargs."""

    def __init__(
        self,
        msg_type: str,
        src_system: int = 1,
        src_component: int = 1,
        **fields: Any,
    ) -> None:
        self._type = msg_type
        self._src_system = src_system
        self._src_component = src_component
        for k, v in fields.items():
            setattr(self, k, v)

    def get_type(self) -> str:
        return self._type

    def get_srcSystem(self) -> int:
        return self._src_system

    def get_srcComponent(self) -> int:
        return self._src_component


class MockMav:
    """Captures outbound MAVLink calls for assertion."""

    def __init__(self) -> None:
        self.heartbeat_sends: int = 0
        self.command_long_calls: list[tuple] = []
        self.param_set_calls: list[tuple] = []

    def heartbeat_send(self, *args: Any) -> None:
        self.heartbeat_sends += 1

    def command_long_send(self, *args: Any) -> None:
        self.command_long_calls.append(args)

    def param_set_send(self, *args: Any) -> None:
        self.param_set_calls.append(args)


class MockConnection:
    """Pre-loaded message queue that simulates a pymavlink connection.

    recv_match: consumes one message per call; type-filters silently (a non-
    matching message is consumed and None is returned, mirroring pymavlink's
    timeout-expiry behaviour).  When the queue is exhausted:
    - if auto_shutdown=True, sets rtl_monitor._shutdown_requested = True so
      the monitor's while-loop exits cleanly without spinning;
    - if auto_shutdown=False (used when testing _issue_rtl directly), returns
      None without touching global state.
    """

    def __init__(self, queue: list, auto_shutdown: bool = True) -> None:
        self._queue = list(queue)
        self._pos = 0
        self.mav = MockMav()
        self.target_system: int = 0
        self.target_component: int = 0
        self._closed: bool = False
        self._auto_shutdown = auto_shutdown

    def recv_match(
        self,
        type: Any = None,
        blocking: bool = True,
        timeout: float = 0.5,
    ) -> MockMessage | None:
        if self._pos >= len(self._queue):
            if self._auto_shutdown:
                rtl_monitor._shutdown_requested = True
            return None
        msg = self._queue[self._pos]
        self._pos += 1
        if msg is None:
            return None
        if type is not None:
            allowed = [type] if isinstance(type, str) else list(type)
            if msg.get_type() not in allowed:
                return None
        return msg

    def probably_vehicle_heartbeat(self, msg: MockMessage) -> bool:
        """Mirror pymavlink filter: reject GCS (type=6), GIMBAL (type=4),
        and INVALID autopilot (autopilot=8)."""
        if getattr(msg, "type", 0) in (4, 6):
            return False
        if getattr(msg, "autopilot", 0) == 8:
            return False
        return True

    def close(self) -> None:
        self._closed = True


# ===========================================================================
# Message factories
# ===========================================================================

def _vehicle_hb(src_system: int = 1) -> MockMessage:
    """Vehicle HEARTBEAT (MAV_TYPE_QUADROTOR=2, MAV_AUTOPILOT_PX4=12)."""
    return MockMessage(
        "HEARTBEAT", src_system=src_system, src_component=1,
        type=2, autopilot=12,
    )


def _gcs_hb(src_system: int = 245) -> MockMessage:
    """GCS HEARTBEAT (type=6, autopilot=8) — rejected by probably_vehicle_heartbeat."""
    return MockMessage(
        "HEARTBEAT", src_system=src_system, src_component=0,
        type=6, autopilot=8,
    )


def _battery(remaining: int, src_system: int = 1) -> MockMessage:
    return MockMessage(
        "BATTERY_STATUS", src_system=src_system,
        battery_remaining=remaining,
    )


def _wind_cov(wind_x: float, wind_y: float, src_system: int = 1) -> MockMessage:
    return MockMessage(
        "WIND_COV", src_system=src_system,
        wind_x=wind_x, wind_y=wind_y,
    )


def _command_ack(command: int, result: int = 0, src_system: int = 1) -> MockMessage:
    """COMMAND_ACK — result=0 is MAV_RESULT_ACCEPTED."""
    return MockMessage(
        "COMMAND_ACK", src_system=src_system,
        command=command, result=result,
    )


def _rtl_heartbeat(src_system: int = 1) -> MockMessage:
    """Vehicle HEARTBEAT advertising PX4 RTL custom_mode."""
    return MockMessage(
        "HEARTBEAT", src_system=src_system, src_component=1,
        type=2, autopilot=12,
        custom_mode=rtl_monitor.PX4_CUSTOM_MODE_RTL,
    )


# ===========================================================================
# Test runners
# ===========================================================================

def _events_from_log(tmpdir: str) -> list[dict]:
    """Parse JSONL events from the single log file written into tmpdir."""
    log_files = list(Path(tmpdir).glob("rtl_monitor_*.jsonl"))
    if not log_files:
        return []
    events: list[dict] = []
    with log_files[0].open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def _run_monitor(
    monitoring_messages: list,
    battery_threshold: int = 20,
    wind_threshold: float = 3.0,
) -> tuple[list[dict], MockConnection]:
    """Run run_monitor() with a pre-populated MockConnection.

    Prepends a vehicle HEARTBEAT so the latch step always succeeds.  Patches
    _open_connection and fast-forwards RTL verification timeouts to 50 ms each.
    Resets _shutdown_requested before the run.

    Note: callers that expect rtl_trigger to fire (T5, T8, T9) should be aware
    that _issue_rtl runs against a then-exhausted queue, producing an ack_timeout
    outcome in the log — this is an intentional side effect, not a test failure.

    Returns (events, conn) where events is the fully parsed JSONL list.
    """
    rtl_monitor._shutdown_requested = False

    queue = [_vehicle_hb()] + list(monitoring_messages)
    conn = MockConnection(queue, auto_shutdown=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            unittest.mock.patch.object(rtl_monitor, "_open_connection", return_value=conn),
            unittest.mock.patch.object(rtl_monitor, "_COMMAND_ACK_TIMEOUT_S", 0.05),
            unittest.mock.patch.object(rtl_monitor, "_MODE_VERIFY_TIMEOUT_S", 0.05),
        ):
            try:
                rtl_monitor.run_monitor(
                    target="udpout:127.0.0.1:14550",
                    output_dir=Path(tmpdir),
                    battery_threshold=battery_threshold,
                    wind_threshold=wind_threshold,
                    sitl_drain_rate=None,
                )
            except SystemExit:
                pass
        events = _events_from_log(tmpdir)  # inside tmpdir context — dir still exists

    return events, conn


def _run_issue_rtl(messages: list) -> tuple[list[dict], MockConnection]:
    """Call _issue_rtl() directly with a MockConnection and an in-memory log.

    auto_shutdown=False: _issue_rtl has no _shutdown_requested check; we must
    not corrupt the global flag mid-call.  Timeouts patched to 50 ms.

    Returns (events, conn).
    """
    conn = MockConnection(messages, auto_shutdown=False)
    conn.target_system = 1
    conn.target_component = 1
    log_io = io.StringIO()

    with (
        unittest.mock.patch.object(rtl_monitor, "_COMMAND_ACK_TIMEOUT_S", 0.05),
        unittest.mock.patch.object(rtl_monitor, "_MODE_VERIFY_TIMEOUT_S", 0.05),
    ):
        rtl_monitor._issue_rtl(conn, log_io)

    log_io.seek(0)
    events = [json.loads(ln) for ln in log_io if ln.strip()]
    return events, conn


# ===========================================================================
# Assertion helpers
# ===========================================================================

def _find(events: list[dict], event_name: str) -> dict | None:
    """Return the first event with the given 'event' key, or None."""
    for e in events:
        if e.get("event") == event_name:
            return e
    return None


def _all(events: list[dict], event_name: str) -> list[dict]:
    """Return all events with the given 'event' key."""
    return [e for e in events if e.get("event") == event_name]


# ===========================================================================
# Tests T1–T11
# ===========================================================================

def t1_latch_vehicle_heartbeat() -> None:
    """T1: Vehicle HEARTBEAT → 'latched' event logged; target_system set to 1."""
    events, conn = _run_monitor([])
    latched = _find(events, "latched")
    assert latched is not None, "expected 'latched' event"
    assert conn.target_system == 1, \
        f"expected target_system=1, got {conn.target_system}"


def t2_latch_skips_gcs_heartbeat() -> None:
    """T2: GCS HB (type=6) → skip event logged; next vehicle HB latches at target_system=3."""
    rtl_monitor._shutdown_requested = False
    queue = [_gcs_hb(), _vehicle_hb(src_system=3)]
    conn = MockConnection(queue, auto_shutdown=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            unittest.mock.patch.object(rtl_monitor, "_open_connection", return_value=conn),
            unittest.mock.patch.object(rtl_monitor, "_COMMAND_ACK_TIMEOUT_S", 0.05),
            unittest.mock.patch.object(rtl_monitor, "_MODE_VERIFY_TIMEOUT_S", 0.05),
        ):
            try:
                rtl_monitor.run_monitor(
                    target="udpout:127.0.0.1:14550",
                    output_dir=Path(tmpdir),
                    battery_threshold=20,
                    wind_threshold=3.0,
                    sitl_drain_rate=None,
                )
            except SystemExit:
                pass
        events = _events_from_log(tmpdir)

    assert _find(events, "latch_skipped_non_vehicle_heartbeat") is not None, \
        "expected latch_skipped_non_vehicle_heartbeat event for GCS HB"
    latched = _find(events, "latched")
    assert latched is not None, "expected 'latched' event after GCS skip"
    assert latched["target_system"] == 3, \
        f"expected target_system=3, got {latched['target_system']}"


def t3_latch_timeout_exits() -> None:
    """T3: Only GCS HBs in queue; _LATCH_TIMEOUT_S=0.05 → SystemExit(1) + latch_timeout event."""
    rtl_monitor._shutdown_requested = False
    # auto_shutdown=False: latch loop does not check _shutdown_requested;
    # the 50 ms deadline drives termination, not queue exhaustion.
    queue = [_gcs_hb(), _gcs_hb()]
    conn = MockConnection(queue, auto_shutdown=False)

    exited_1 = False
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            unittest.mock.patch.object(rtl_monitor, "_open_connection", return_value=conn),
            unittest.mock.patch.object(rtl_monitor, "_LATCH_TIMEOUT_S", 0.05),
        ):
            try:
                rtl_monitor.run_monitor(
                    target="udpout:127.0.0.1:14550",
                    output_dir=Path(tmpdir),
                    battery_threshold=20,
                    wind_threshold=3.0,
                    sitl_drain_rate=None,
                )
            except SystemExit as exc:
                exited_1 = exc.code == 1
        events = _events_from_log(tmpdir)

    assert exited_1, "expected SystemExit(1) on latch timeout"
    assert _find(events, "latch_timeout") is not None, "expected 'latch_timeout' event"


def t4_battery_single_below_no_rtl() -> None:
    """T4: One BATTERY_STATUS below threshold → battery_below_threshold consecutive=1; no RTL."""
    events, conn = _run_monitor([_battery(15)])
    below = _find(events, "battery_below_threshold")
    assert below is not None, "expected battery_below_threshold event"
    assert below["consecutive"] == 1, \
        f"expected consecutive=1, got {below['consecutive']}"
    assert _find(events, "rtl_trigger") is None, "unexpected rtl_trigger after single reading"
    assert len(conn.mav.command_long_calls) == 0, "unexpected command_long_send"


def t5_battery_debounce_fires_rtl() -> None:
    """T5: Two consecutive BATTERY_STATUS below threshold → rtl_trigger reason=battery + command."""
    events, conn = _run_monitor([_battery(15), _battery(10)])
    trigger = _find(events, "rtl_trigger")
    assert trigger is not None, "expected rtl_trigger event"
    assert trigger["reason"] == "battery", \
        f"expected reason=battery, got {trigger['reason']}"
    assert len(conn.mav.command_long_calls) >= 1, "expected command_long_send call"


def t6_battery_reset_clears_count() -> None:
    """T6: Below, above, below — reset clears counter; consecutive never reaches 2; no RTL."""
    events, conn = _run_monitor([_battery(15), _battery(80), _battery(15)])
    assert _find(events, "battery_reset") is not None, "expected battery_reset event"
    assert _find(events, "rtl_trigger") is None, "unexpected rtl_trigger after reset"
    below_events = _all(events, "battery_below_threshold")
    assert all(e["consecutive"] <= 1 for e in below_events), \
        "consecutive should never exceed 1 when reset occurred between readings"


def t7_battery_unknown_skipped() -> None:
    """T7: battery_remaining=-1 → battery_unknown event; no RTL regardless of count."""
    events, conn = _run_monitor([_battery(-1), _battery(-1)])
    assert _find(events, "battery_unknown") is not None, "expected battery_unknown event"
    assert _find(events, "rtl_trigger") is None, \
        "unexpected rtl_trigger for unknown (remaining=-1) battery"
    assert len(conn.mav.command_long_calls) == 0, "unexpected command_long_send"


def t8_wind_debounce_fires_rtl() -> None:
    """T8: Two WIND_COV with speed=5.0 m/s (>3.0 threshold) → rtl_trigger reason=wind."""
    # sqrt(4.0² + 3.0²) = 5.0 m/s  >  default 3.0 m/s threshold
    events, conn = _run_monitor([
        _wind_cov(4.0, 3.0),
        _wind_cov(4.0, 3.0),
    ])
    trigger = _find(events, "rtl_trigger")
    assert trigger is not None, "expected rtl_trigger event"
    assert trigger["reason"] == "wind", \
        f"expected reason=wind, got {trigger['reason']}"
    assert len(conn.mav.command_long_calls) >= 1, "expected command_long_send call"


def t9_rtl_one_shot() -> None:
    """T9: 4 below-threshold messages — monitor exits after first RTL; exactly one command sent."""
    events, conn = _run_monitor([
        _battery(10), _battery(10), _battery(10), _battery(10),
    ])
    triggers = _all(events, "rtl_trigger")
    assert len(triggers) == 1, \
        f"expected exactly 1 rtl_trigger, got {len(triggers)}"
    assert len(conn.mav.command_long_calls) == 1, \
        f"expected 1 command_long_send, got {len(conn.mav.command_long_calls)}"


def t10_issue_rtl_confirmed() -> None:
    """T10: _issue_rtl receives COMMAND_ACK then RTL-mode HEARTBEAT → rtl_outcome: confirmed."""
    from pymavlink import mavutil as _mavu
    messages = [
        _command_ack(_mavu.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, result=0),
        _rtl_heartbeat(src_system=1),
    ]
    events, conn = _run_issue_rtl(messages)
    outcome = _find(events, "rtl_outcome")
    assert outcome is not None, "expected rtl_outcome event"
    assert outcome["status"] == "confirmed", \
        f"expected status=confirmed, got {outcome['status']}"


def t11_issue_rtl_ack_timeout() -> None:
    """T11: _issue_rtl with empty queue; 50 ms ACK window expires → rtl_outcome ack_timeout."""
    events, conn = _run_issue_rtl([])
    outcome = _find(events, "rtl_outcome")
    assert outcome is not None, "expected rtl_outcome event"
    assert "ack_timeout" in outcome["status"], \
        f"expected 'ack_timeout' in status, got {outcome['status']}"


# ===========================================================================
# Runner
# ===========================================================================

_TESTS = [
    ("T1  latch_vehicle_heartbeat",      t1_latch_vehicle_heartbeat),
    ("T2  latch_skips_gcs_heartbeat",    t2_latch_skips_gcs_heartbeat),
    ("T3  latch_timeout_exits",          t3_latch_timeout_exits),
    ("T4  battery_single_below_no_rtl",  t4_battery_single_below_no_rtl),
    ("T5  battery_debounce_fires_rtl",   t5_battery_debounce_fires_rtl),
    ("T6  battery_reset_clears_count",   t6_battery_reset_clears_count),
    ("T7  battery_unknown_skipped",      t7_battery_unknown_skipped),
    ("T8  wind_debounce_fires_rtl",      t8_wind_debounce_fires_rtl),
    ("T9  rtl_one_shot",                 t9_rtl_one_shot),
    ("T10 issue_rtl_confirmed",          t10_issue_rtl_confirmed),
    ("T11 issue_rtl_ack_timeout",        t11_issue_rtl_ack_timeout),
]


def main() -> None:
    passed = 0
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {name}")
            print(f"      {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
