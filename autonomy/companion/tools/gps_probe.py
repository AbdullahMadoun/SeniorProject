#!/usr/bin/env python3
"""GPS probe for S5 (GPS signal quality) specification verification.

Connects to a MAVLink source, samples GPS_RAW_INT messages for a fixed
duration, and reports horizontal accuracy (eph) statistics and fix-type
distribution.  Intended to be run on the Pi companion against the
Docker SITL over a phone-hotspot LAN, mirroring the connection topology
proven in R10.

Note on target: this probe connects directly to the SITL container's
published GCS port (udpout:172.20.10.2:18570 from Pi) without going
through a local MAVProxy daemon.  MAVProxy was used in R10 as a
verification tool, not as a persistent daemon; no fan-out port is
available.  If MAVProxy is later configured with --out, the default
target should be changed to the fan-out address (e.g.
udp:127.0.0.1:14551) to match video_logger's convention.

Connection style mirrors autonomy/companion/video_logger.py:
  - pymavlink.mavutil.mavlink_connection with autoreconnect=True,
    source_system=250
  - URL normaliser strips '://' → ':' for UDP targets
  - recv_match with blocking=True and a per-iteration timeout

Note on eph units: GPS_RAW_INT.eph is a dimensionless HDOP×100 value
per MAVLink common.xml, not a distance in centimetres.  Most autopilots
and GCS tools interpret eph/100 as metres for display purposes, and PX4
SITL reports values consistent with that convention.  This probe follows
the same convention; eph_m values should be read as "metres equivalent"
not "true geometric error".

Exit codes:
  0 — at least MIN_MESSAGES GPS_RAW_INT messages received; stats printed
  1 — insufficient data; reason printed to stderr

Example (Pi against Docker SITL on Mac 172.20.10.2):
  python gps_probe.py --target udpout:172.20.10.2:18570 --duration 30

Example (inside container / Mac loopback):
  python gps_probe.py --target udpout:127.0.0.1:18570 --duration 30
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from typing import Any

from pymavlink import mavutil  # type: ignore

# MAVLink GPS_FIX_TYPE enum labels (MAVLink common.xml)
FIX_TYPE_NAMES: dict[int, str] = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "STATIC",
    8: "PPP",
}

# UINT16_MAX sentinel meaning "not available" in GPS_RAW_INT.eph
EPH_UNKNOWN_SENTINEL: int = 65535

# Minimum GPS_RAW_INT messages required for a successful probe
MIN_MESSAGES: int = 5


def _open_connection(target: str) -> Any:
    """Open a MAVLink connection from a URL-style target string, mirroring
    video_logger._open_mavlink_connection with autoreconnect=True.

    Strips '://' to ':' so that 'udpout://host:port' and 'udpout:host:port'
    are both accepted.

    Args:
        target: MAVLink target string, e.g. 'udpout:172.20.10.2:18570'.

    Returns:
        A pymavlink mavfile connection object.
    """
    cleaned = target.strip()
    if "://" in cleaned:
        cleaned = cleaned.replace("://", ":", 1)
    return mavutil.mavlink_connection(cleaned, autoreconnect=True, source_system=250)


def collect_gps_messages(
    conn: Any,
    duration_s: float,
) -> tuple[list[float], list[int]]:
    """Receive GPS_RAW_INT messages for *duration_s* seconds.

    Args:
        conn: Open pymavlink connection.
        duration_s: How long to listen, in seconds.

    Returns:
        A tuple (eph_values_m, fix_types) where:
          - eph_values_m: list of eph/100 values (metres-equivalent, see
            module docstring for unit caveat) for messages where eph is
            not the unknown sentinel (65535)
          - fix_types: list of raw GPS_FIX_TYPE integer values for every
            message received (including those with unknown eph)
    """
    eph_values_m: list[float] = []
    fix_types: list[int] = []
    deadline = time.monotonic() + duration_s

    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        msg = conn.recv_match(
            type="GPS_RAW_INT",
            blocking=True,
            timeout=min(remaining, 1.0),
        )
        if msg is None:
            continue
        fix_types.append(int(msg.fix_type))
        if int(msg.eph) != EPH_UNKNOWN_SENTINEL:
            # GPS_RAW_INT.eph is dimensionless HDOP×100 per MAVLink common.xml;
            # most autopilots and GCS tools interpret eph/100 as meters for
            # display, and PX4 SITL reports values consistent with that.
            eph_values_m.append(msg.eph / 100.0)

    return eph_values_m, fix_types


def build_report(eph_values_m: list[float], fix_types: list[int]) -> dict[str, Any]:
    """Compute summary statistics from collected GPS samples.

    Args:
        eph_values_m: Horizontal accuracy samples (metres-equivalent).
        fix_types: Raw GPS_FIX_TYPE integers, one per received message.

    Returns:
        A dict suitable for JSON serialisation and human display.
    """
    fix_counter = Counter(fix_types)
    fix_distribution = {
        FIX_TYPE_NAMES.get(k, f"UNKNOWN_{k}"): v
        for k, v in sorted(fix_counter.items())
    }
    return {
        "msg_count": len(fix_types),
        "eph_msg_count": len(eph_values_m),
        "eph_mean_m": round(statistics.mean(eph_values_m), 4) if eph_values_m else None,
        "eph_max_m": round(max(eph_values_m), 4) if eph_values_m else None,
        "eph_min_m": round(min(eph_values_m), 4) if eph_values_m else None,
        "fix_type_distribution": fix_distribution,
    }


def run_probe(target: str, duration_s: float) -> dict[str, Any]:
    """End-to-end probe: connect, collect, report.

    Args:
        target: MAVLink connection string.
        duration_s: Observation window length in seconds.

    Returns:
        Report dict (see build_report).

    Raises:
        SystemExit(1): If fewer than MIN_MESSAGES messages were received.
    """
    print(f"[gps_probe] connecting to {target!r} for {duration_s:.0f}s \u2026", file=sys.stderr)
    conn = _open_connection(target)
    try:
        eph_values_m, fix_types = collect_gps_messages(conn, duration_s)
    finally:
        conn.close()

    if len(fix_types) < MIN_MESSAGES:
        print(
            f"[gps_probe] FAIL: received {len(fix_types)} GPS_RAW_INT messages "
            f"(minimum required: {MIN_MESSAGES}). "
            "Is PX4 SITL running and is the MAVLink connection correct?",
            file=sys.stderr,
        )
        sys.exit(1)

    return build_report(eph_values_m, fix_types)


def print_report(report: dict[str, Any]) -> None:
    """Print a human-readable summary followed by the raw JSON."""
    print("\n=== GPS Probe Results ===")
    print(f"  Messages received : {report['msg_count']}")
    print(f"  EPH messages      : {report['eph_msg_count']}")
    if report["eph_mean_m"] is not None:
        print(f"  EPH mean          : {report['eph_mean_m']:.4f} m-equiv")
        print(f"  EPH min           : {report['eph_min_m']:.4f} m-equiv")
        print(f"  EPH max           : {report['eph_max_m']:.4f} m-equiv")
    else:
        print("  EPH               : all messages reported unknown (65535)")
    print("  Fix-type distribution:")
    for label, count in report["fix_type_distribution"].items():
        print(f"    {label}: {count}")
    print("\n--- JSON ---")
    print(json.dumps(report, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target",
        default="udpout:172.20.10.2:18570",
        help=(
            "MAVLink connection string. "
            "Default 'udpout:172.20.10.2:18570' connects directly to the Docker "
            "SITL container from Pi over hotspot LAN (no local MAVProxy required). "
            "Use 'udpout:127.0.0.1:18570' from inside the container."
        ),
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Observation window in seconds (default: 30).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = run_probe(target=args.target, duration_s=args.duration)
    print_report(report)


if __name__ == "__main__":
    main()
