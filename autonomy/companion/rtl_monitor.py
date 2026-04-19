#!/usr/bin/env python3
"""
rtl_monitor.py — Pi-side Return-to-Launch safety monitor.

Watches BATTERY_STATUS and WIND_COV (plus legacy WIND for older firmwares)
over a direct pymavlink UDP connection.  Issues MAV_CMD_NAV_RETURN_TO_LAUNCH
when a safety threshold is breached for two consecutive messages (debounce),
then verifies the command via COMMAND_ACK and a HEARTBEAT mode transition.

SINGLE-PARTNER-LATCH AWARENESS
===============================
PX4's GCS MAVLink port (default udpout:172.20.10.2:18570) has a single-
partner slot. Running rtl_monitor simultaneously with any other direct
pymavlink client (video_logger in direct mode, gps_probe, etc.) means only
one client receives telemetry. When the full stack runs concurrently, route
all clients through a MAVProxy fan-out and point this script at the fan-out
port instead of directly at PX4.

DEBOUNCE LOGIC
==============
For each message type:
  - battery_consecutive_below: incremented each BATTERY_STATUS where
    battery_remaining <= threshold, reset to 0 on any message above
    threshold.
  - wind_consecutive_above: incremented each WIND_COV/WIND where derived
    horizontal speed > threshold, reset to 0 on any message at or below
    threshold.
  - RTL fires when a counter reaches DEBOUNCE_COUNT (2).
  - After RTL fires, rtl_issued is set True. No further RTL commands are
    issued in this session regardless of subsequent readings.

WIND PATH NOTE
==============
PX4 SITL does not emit WIND or WIND_COV over the GCS MAVLink stream by
default; wind is an internal Gazebo physics parameter (SIM_WIND_SPD) not
broadcast to GCS clients. The wind-threshold code path is implemented and
unit-testable via synthetic injection but requires field-flight with a real
Pixhawk for operational validation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymavlink import mavutil  # type: ignore

# ---------------------------------------------------------------------------
# PX4 RTL custom_mode constant
#
# PX4 packs custom_mode as a 32-bit struct (px4_custom_mode.h):
#   bits  0-15  reserved (always 0)
#   bits 16-23  main_mode  (uint8)   — PX4_CUSTOM_MAIN_MODE_AUTO    = 4
#   bits 24-31  sub_mode   (uint8)   — PX4_CUSTOM_SUB_MODE_AUTO_RTL = 5
#
# custom_mode = (sub_mode << 24) | (main_mode << 16)
#             = (5 << 24) | (4 << 16)
#             = 0x05040000 = 84148224
# ---------------------------------------------------------------------------
_PX4_MAIN_MODE_AUTO: int = 4
_PX4_SUB_MODE_AUTO_RTL: int = 5
PX4_CUSTOM_MODE_RTL: int = (_PX4_SUB_MODE_AUTO_RTL << 24) | (_PX4_MAIN_MODE_AUTO << 16)

_DEBOUNCE_COUNT: int = 2
_HEARTBEAT_INTERVAL_S: float = 1.0
_RECV_TIMEOUT_S: float = 0.5
_COMMAND_ACK_TIMEOUT_S: float = 3.0
_MODE_VERIFY_TIMEOUT_S: float = 5.0
_LATCH_TIMEOUT_S: float = 15.0
_PARAM_CONFIRM_TIMEOUT_S: float = 2.0

_MONITOR_MSG_TYPES: list[str] = ["BATTERY_STATUS", "WIND_COV", "WIND"]

# Global flag set by SIGTERM/SIGINT handler.
_shutdown_requested: bool = False


def _sigterm_handler(signum: int, frame: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _open_connection(target: str) -> Any:
    """Open pymavlink connection, mirroring gps_probe._open_connection."""
    cleaned = target.strip()
    if "://" in cleaned:
        cleaned = cleaned.replace("://", ":", 1)
    return mavutil.mavlink_connection(cleaned, autoreconnect=True, source_system=250)


def _heartbeat_send(conn: Any) -> None:
    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0, 0, 0,
    )


# ---------------------------------------------------------------------------
# JSONL logging
# ---------------------------------------------------------------------------

def _log(log_file: Any, record: dict) -> None:
    record["ts"] = datetime.now(timezone.utc).isoformat()
    log_file.write(json.dumps(record) + "\n")
    log_file.flush()


# ---------------------------------------------------------------------------
# SITL battery drain injection (test-only)
# ---------------------------------------------------------------------------

def _inject_sitl_drain(conn: Any, drain_rate: float, log_file: Any) -> None:
    """
    SITL TESTING ONLY — never pass --sitl-test-drain-rate on real hardware.

    Issues PARAM_SET(SIM_BAT_DRAIN=drain_rate) so the simulated battery drains
    at drain_rate percent per minute, driving battery_remaining below the RTL
    threshold within the monitor session.

    param_id is passed as b"SIM_BAT_DRAIN" (13 bytes). Python's struct module
    auto-null-pads 's' format strings to the declared field width (16 bytes);
    no manual padding is needed.
    """
    conn.mav.param_set_send(
        conn.target_system,
        conn.target_component,
        b"SIM_BAT_DRAIN",
        float(drain_rate),
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )
    deadline = time.monotonic() + _PARAM_CONFIRM_TIMEOUT_S
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.3)
        if msg and msg.param_id.rstrip("\x00") == "SIM_BAT_DRAIN":
            _log(log_file, {
                "event": "sitl_drain_set",
                "param": "SIM_BAT_DRAIN",
                "confirmed_value": msg.param_value,
            })
            return
    _log(log_file, {
        "event": "sitl_drain_set_unconfirmed",
        "requested_value": drain_rate,
    })


# ---------------------------------------------------------------------------
# RTL issuance and verification
# ---------------------------------------------------------------------------

def _issue_rtl(conn: Any, log_file: Any) -> None:
    """Send MAV_CMD_NAV_RETURN_TO_LAUNCH; verify via COMMAND_ACK then HEARTBEAT.

    During both wait loops (ACK and mode verify) we continue sending 1 Hz
    heartbeats so PX4 does not drop our peer status mid-verification.

    Note: while blocked in these loops, BATTERY_STATUS and WIND_COV messages
    arriving in the buffer are discarded by the type filter. This is acceptable
    because RTL is one-shot and the monitor exits after _issue_rtl returns.
    """
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
        0,               # confirmation — 0 for first attempt
        0, 0, 0, 0, 0, 0, 0,  # params 1-7: all unused for RTL
    )
    _log(log_file, {"event": "rtl_command_sent",
                    "command": "MAV_CMD_NAV_RETURN_TO_LAUNCH"})

    # Step 1 — COMMAND_ACK (3 s window, heartbeat maintained)
    ack_deadline = time.monotonic() + _COMMAND_ACK_TIMEOUT_S
    last_hb = time.monotonic()
    ack_received = False
    while time.monotonic() < ack_deadline:
        now = time.monotonic()
        if now - last_hb >= _HEARTBEAT_INTERVAL_S:
            _heartbeat_send(conn)
            last_hb = now
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.3)
        if msg is None:
            continue
        if msg.command != mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH:
            continue
        try:
            result_name = mavutil.mavlink.enums["MAV_RESULT"][msg.result].name
        except (KeyError, AttributeError):
            result_name = f"UNKNOWN({msg.result})"
        _log(log_file, {
            "event": "command_ack",
            "result": result_name,
            "result_raw": msg.result,
        })
        ack_received = True
        break

    if not ack_received:
        _log(log_file, {"event": "command_ack_timeout",
                         "waited_s": _COMMAND_ACK_TIMEOUT_S})
        _log(log_file, {"event": "rtl_outcome",
                         "status": "command_sent_ack_timeout"})
        return

    # Step 2 — HEARTBEAT custom_mode == PX4_CUSTOM_MODE_RTL (5 s window, heartbeat maintained)
    mode_deadline = time.monotonic() + _MODE_VERIFY_TIMEOUT_S
    last_hb = time.monotonic()
    while time.monotonic() < mode_deadline:
        now = time.monotonic()
        if now - last_hb >= _HEARTBEAT_INTERVAL_S:
            _heartbeat_send(conn)
            last_hb = now
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
        if msg is None:
            continue
        if msg.get_srcSystem() != conn.target_system:
            continue
        custom_mode = msg.custom_mode
        _log(log_file, {
            "event": "heartbeat_observed",
            "custom_mode": custom_mode,
            "custom_mode_hex": hex(custom_mode),
        })
        if custom_mode == PX4_CUSTOM_MODE_RTL:
            _log(log_file, {
                "event": "rtl_outcome",
                "status": "confirmed",
                "custom_mode": custom_mode,
                "custom_mode_hex": hex(custom_mode),
            })
            return

    _log(log_file, {
        "event": "rtl_outcome",
        "status": "command_sent_mode_transition_unconfirmed",
    })


# ---------------------------------------------------------------------------
# Monitor loop
# ---------------------------------------------------------------------------

def run_monitor(
    target: str,
    output_dir: Path,
    battery_threshold: int,
    wind_threshold: float,
    sitl_drain_rate: float | None,
) -> None:
    global _shutdown_requested

    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

    output_dir.mkdir(parents=True, exist_ok=True)
    # One file per session — startup timestamp in filename, open mode "w".
    # Matches gps_probe convention; avoids ambiguous multi-session appends.
    startup_dt = datetime.now(timezone.utc)
    log_path = output_dir / f"rtl_monitor_{startup_dt.strftime('%Y%m%d_%H%M%S')}.jsonl"

    with log_path.open("w", encoding="utf-8") as log_file:
        _log(log_file, {
            "event": "startup",
            "target": target,
            "battery_threshold_pct": battery_threshold,
            "wind_threshold_ms": wind_threshold,
            "sitl_drain_rate": sitl_drain_rate,
            "px4_custom_mode_rtl": PX4_CUSTOM_MODE_RTL,
            "px4_custom_mode_rtl_hex": hex(PX4_CUSTOM_MODE_RTL),
        })

        conn = _open_connection(target)

        # recv_match(type="HEARTBEAT") returns the first HEARTBEAT of ANY class,
        # including GCS-class heartbeats broadcast by mission_api and companion_sim
        # on the LAN. wait_heartbeat() is identical — it is recv_match(HEARTBEAT)
        # with no additional filtering; probably_vehicle_heartbeat() is only used
        # internally to auto-populate sysid, not to gate the return value.
        # We loop explicitly, skipping HEARTBEATs that fail
        # conn.probably_vehicle_heartbeat() (GCS, GIMBAL, ADSB, INVALID autopilot).
        _heartbeat_send(conn)
        latch_deadline = time.monotonic() + _LATCH_TIMEOUT_S
        hb = None
        while time.monotonic() < latch_deadline:
            remaining = max(0.1, latch_deadline - time.monotonic())
            candidate = conn.recv_match(
                type="HEARTBEAT", blocking=True, timeout=min(remaining, 1.0)
            )
            if candidate is None:
                continue
            if not conn.probably_vehicle_heartbeat(candidate):
                _log(log_file, {
                    "event": "latch_skipped_non_vehicle_heartbeat",
                    "src_system": candidate.get_srcSystem(),
                    "src_component": candidate.get_srcComponent(),
                    "mav_type": candidate.type,
                    "autopilot": candidate.autopilot,
                })
                continue
            hb = candidate
            break

        if hb is None:
            _log(log_file, {
                "event": "latch_timeout",
                "error": f"no vehicle HEARTBEAT received within {_LATCH_TIMEOUT_S}s",
            })
            conn.close()
            sys.exit(1)

        # pymavlink's recv_msg() auto-populates conn.target_system from vehicle
        # HEARTBEATs when sysid==0. Explicit assignment here makes the dependency
        # visible and ensures correct routing for PARAM_SET and COMMAND_LONG.
        conn.target_system = hb.get_srcSystem()
        conn.target_component = hb.get_srcComponent()
        _log(log_file, {
            "event": "latched",
            "target_system": conn.target_system,
            "target_component": conn.target_component,
            "mav_type": hb.type,
            "autopilot": hb.autopilot,
        })

        if sitl_drain_rate is not None:
            _inject_sitl_drain(conn, sitl_drain_rate, log_file)

        rtl_issued: bool = False
        battery_consecutive_below: int = 0
        wind_consecutive_above: int = 0
        last_heartbeat_ts: float = time.monotonic()

        while not _shutdown_requested and not rtl_issued:
            now = time.monotonic()
            if now - last_heartbeat_ts >= _HEARTBEAT_INTERVAL_S:
                _heartbeat_send(conn)
                last_heartbeat_ts = now

            msg = conn.recv_match(
                type=_MONITOR_MSG_TYPES,
                blocking=True,
                timeout=_RECV_TIMEOUT_S,
            )
            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == "BATTERY_STATUS":
                remaining = msg.battery_remaining
                if remaining < 0:
                    _log(log_file, {"event": "battery_unknown",
                                     "battery_remaining": remaining})
                    continue

                if remaining <= battery_threshold:
                    battery_consecutive_below += 1
                    _log(log_file, {
                        "event": "battery_below_threshold",
                        "battery_remaining": remaining,
                        "threshold": battery_threshold,
                        "consecutive": battery_consecutive_below,
                    })
                    if battery_consecutive_below >= _DEBOUNCE_COUNT:
                        _log(log_file, {
                            "event": "rtl_trigger",
                            "reason": "battery",
                            "battery_remaining": remaining,
                        })
                        _issue_rtl(conn, log_file)
                        rtl_issued = True
                else:
                    if battery_consecutive_below > 0:
                        _log(log_file, {"event": "battery_reset",
                                         "battery_remaining": remaining})
                    battery_consecutive_below = 0

            elif msg_type in ("WIND_COV", "WIND"):
                if msg_type == "WIND_COV":
                    # wind_x/wind_y are NED north/east components (m/s)
                    wind_speed = math.sqrt(msg.wind_x ** 2 + msg.wind_y ** 2)
                else:
                    # Deprecated WIND (#168): speed field is ground-plane m/s
                    wind_speed = float(msg.speed)

                if wind_speed > wind_threshold:
                    wind_consecutive_above += 1
                    _log(log_file, {
                        "event": "wind_above_threshold",
                        "wind_speed_ms": round(wind_speed, 3),
                        "threshold": wind_threshold,
                        "consecutive": wind_consecutive_above,
                        "source": msg_type,
                    })
                    if wind_consecutive_above >= _DEBOUNCE_COUNT:
                        _log(log_file, {
                            "event": "rtl_trigger",
                            "reason": "wind",
                            "wind_speed_ms": round(wind_speed, 3),
                        })
                        _issue_rtl(conn, log_file)
                        rtl_issued = True
                else:
                    if wind_consecutive_above > 0:
                        _log(log_file, {"event": "wind_reset",
                                         "wind_speed_ms": round(wind_speed, 3)})
                    wind_consecutive_above = 0

        _log(log_file, {
            "event": "shutdown",
            "rtl_issued": rtl_issued,
            "reason": "sigterm" if _shutdown_requested else "rtl_complete",
        })
        conn.close()

    print(f"[rtl_monitor] log written: {log_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pi-side RTL safety monitor — watches battery and wind over MAVLink.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables (override defaults; CLI flags override env vars):
  SKYLINK_RTL_BATTERY_PCT   Battery RTL threshold percent   (default: 20)
  SKYLINK_RTL_WIND_MS       Wind speed RTL threshold m/s    (default: 3.0)
  SKYLINK_MAV_TARGET        MAVLink target string           (default: udpout:172.20.10.2:18570)

Typical invocations:

  # Production (real Pixhawk or SITL without battery injection):
  python3 rtl_monitor.py --target udpout:172.20.10.2:18570

  # SITL test — drain battery at 50%%/min to trigger RTL threshold:
  python3 rtl_monitor.py --target udpout:172.20.10.2:18570 \\
    --sitl-test-drain-rate 50

WARNING: --sitl-test-drain-rate issues PARAM_SET(SIM_BAT_DRAIN) to the
flight controller. NEVER pass this flag when connected to real hardware.
""",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("SKYLINK_MAV_TARGET", "udpout:172.20.10.2:18570"),
        help="MAVLink connection string (default: udpout:172.20.10.2:18570)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/skylink_rtl_monitor"),
        help="Directory for JSONL log output (default: /tmp/skylink_rtl_monitor)",
    )
    parser.add_argument(
        "--sitl-test-drain-rate",
        type=float,
        default=None,
        metavar="PCT_PER_MIN",
        help=(
            "SITL TESTING ONLY — inject PARAM_SET(SIM_BAT_DRAIN=N) on startup "
            "to drain battery at N%% per minute. NEVER use on real hardware."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    battery_threshold = int(os.environ.get("SKYLINK_RTL_BATTERY_PCT", "20"))
    wind_threshold = float(os.environ.get("SKYLINK_RTL_WIND_MS", "3.0"))
    run_monitor(
        target=args.target,
        output_dir=args.output_dir,
        battery_threshold=battery_threshold,
        wind_threshold=wind_threshold,
        sitl_drain_rate=args.sitl_test_drain_rate,
    )


if __name__ == "__main__":
    main()
