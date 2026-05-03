"""Heartbeat probe for the Pixhawk USB link.

Read-only diagnostic script. Opens a serial connection to the autopilot,
waits for a fixed number of MAVLink ``HEARTBEAT`` messages, then logs
``ATTITUDE`` messages for a fixed duration. On success the final stdout
line is ``PROBE OK``; on failure ``PROBE FAIL: <reason>``. The process
exits 0 on success and a distinct non-zero code per failure mode.

The probe never sends any MAVLink command, never requests data streams,
and never reconfigures the serial port baud rate beyond the value passed
to pymavlink. An autopilot on the other end of the link is undisturbed.

Run with the companion venv (which has pymavlink installed)::

    cd /home/pi/SeniorProject
    autonomy/companion/.venv-pi/bin/python \\
        -m autonomy.companion.scripts.diagnostics.heartbeat_probe \\
        --device /dev/ttyACM0
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Any

# Distinct exit codes so callers (and the systemd journal) can disambiguate
# failure modes without parsing stdout.
EXIT_OK: int = 0
EXIT_BAD_ARGS: int = 1
EXIT_CONNECT_FAILED: int = 2
EXIT_HEARTBEAT_TIMEOUT: int = 3
EXIT_ATTITUDE_TIMEOUT: int = 4

# Per-message timeout for heartbeats after the first one. The MAVLink
# default heartbeat rate is 1 Hz, so 3 s tolerates one missed heartbeat
# without giving up.
_HEARTBEAT_FOLLOWUP_TIMEOUT_S: float = 3.0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the heartbeat-probe CLI.

    Returns:
        Configured parser with the five documented flags.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Read-only probe: verify that the Pi receives MAVLink heartbeats "
            "and live attitude data from the Pixhawk over USB."
        ),
    )
    parser.add_argument(
        "--device",
        default="/dev/ttyACM0",
        help="Serial device path (default: /dev/ttyACM0).",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help=(
            "Baud rate passed to pymavlink (default: 115200). USB CDC ignores "
            "the value, but pymavlink requires the argument."
        ),
    )
    parser.add_argument(
        "--heartbeats",
        type=int,
        default=3,
        help="Number of HEARTBEAT messages to require (default: 3).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help=(
            "Seconds of ATTITUDE logging after the heartbeats are received "
            "(default: 5)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for the FIRST HEARTBEAT (default: 15).",
    )
    return parser


def open_connection(device: str, baud: int) -> Any:
    """Open a read-only MAVLink connection to the autopilot.

    Uses ``source_system=250`` (matches the rest of the SkyLink companion)
    so traffic from the probe is distinguishable from a real GCS, and
    ``autoreconnect=False`` so the probe fails cleanly if the link drops
    rather than silently retrying.

    Args:
        device: Serial device path or pymavlink connection string.
        baud: Baud rate forwarded to pymavlink.

    Returns:
        An open ``mavutil.mavfile`` instance.
    """
    from pymavlink import mavutil  # type: ignore[import-not-found]

    return mavutil.mavlink_connection(
        device,
        baud=baud,
        autoreconnect=False,
        source_system=250,
    )


def wait_for_heartbeats(
    connection: Any,
    count: int,
    first_timeout_s: float,
) -> list[dict[str, Any]]:
    """Block until ``count`` ``HEARTBEAT`` messages have been received.

    The first heartbeat may take a while (autopilot warm-up, link
    settling), hence the configurable ``first_timeout_s``. Subsequent
    heartbeats use a 3 s per-message ceiling because the standard MAVLink
    heartbeat rate is 1 Hz.

    Args:
        connection: Open mavutil connection from :func:`open_connection`.
        count: Number of HEARTBEAT messages to collect (must be >= 1).
        first_timeout_s: Wait at most this many seconds for the first
            heartbeat.

    Returns:
        List of length ``count`` where each entry has keys ``index``,
        ``recv_ts``, ``system_id``, ``component_id``, ``autopilot``,
        ``mav_type``, and ``system_status``.

    Raises:
        ValueError: If ``count < 1``.
        TimeoutError: If a heartbeat is not received within the allotted
            window. The message states how many heartbeats were collected
            before the timeout.
    """
    if count < 1:
        raise ValueError("heartbeat count must be >= 1")

    received: list[dict[str, Any]] = []

    for index in range(count):
        timeout_s = first_timeout_s if index == 0 else _HEARTBEAT_FOLLOWUP_TIMEOUT_S
        msg = connection.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout_s)
        if msg is None:
            raise TimeoutError(
                f"no HEARTBEAT received within {timeout_s:.1f}s "
                f"(received {index}/{count} so far)"
            )
        received.append(
            {
                "index": index + 1,
                "recv_ts": time.time(),
                "system_id": msg.get_srcSystem(),
                "component_id": msg.get_srcComponent(),
                "autopilot": int(getattr(msg, "autopilot", -1)),
                "mav_type": int(getattr(msg, "type", -1)),
                "system_status": int(getattr(msg, "system_status", -1)),
            }
        )

    return received


def collect_attitude(connection: Any, duration_s: float) -> list[dict[str, Any]]:
    """Collect ``ATTITUDE`` messages from the autopilot for ``duration_s``.

    Strictly read-only: does not request streams or send commands; relies
    on the autopilot's default streaming. PX4 and ArduPilot both stream
    ``ATTITUDE`` over USB by default, so absence of samples typically
    indicates a link or autopilot problem rather than a missing stream
    request.

    Args:
        connection: Open mavutil connection from :func:`open_connection`.
        duration_s: Wall-clock seconds to collect for. Must be > 0.

    Returns:
        List of dicts with keys ``recv_ts``, ``time_boot_ms``,
        ``roll_deg``, ``pitch_deg``, ``yaw_deg``. May be empty if no
        ATTITUDE messages arrive in the window.
    """
    samples: list[dict[str, Any]] = []
    deadline_mono = time.monotonic() + duration_s

    while True:
        remaining = deadline_mono - time.monotonic()
        if remaining <= 0:
            break
        # Cap the per-call timeout at 1 s so the loop exits promptly when
        # the deadline expires, even if no ATTITUDE messages are arriving.
        msg = connection.recv_match(
            type="ATTITUDE",
            blocking=True,
            timeout=min(remaining, 1.0),
        )
        if msg is None:
            continue
        samples.append(
            {
                "recv_ts": time.time(),
                "time_boot_ms": int(getattr(msg, "time_boot_ms", 0)),
                "roll_deg": math.degrees(float(msg.roll)),
                "pitch_deg": math.degrees(float(msg.pitch)),
                "yaw_deg": math.degrees(float(msg.yaw)),
            }
        )

    return samples


def print_heartbeats(heartbeats: list[dict[str, Any]]) -> None:
    """Print one human-readable line per heartbeat to stdout."""
    for hb in heartbeats:
        print(
            f"[heartbeat {hb['index']}] sys={hb['system_id']} "
            f"comp={hb['component_id']} autopilot={hb['autopilot']} "
            f"type={hb['mav_type']} status={hb['system_status']}"
        )


def print_attitude(samples: list[dict[str, Any]]) -> None:
    """Print attitude samples to stdout: a count line followed by one row each."""
    print(f"[attitude] received {len(samples)} sample(s)")
    for sample in samples:
        print(
            f"[attitude] t_boot_ms={sample['time_boot_ms']} "
            f"roll={sample['roll_deg']:+.2f} deg "
            f"pitch={sample['pitch_deg']:+.2f} deg "
            f"yaw={sample['yaw_deg']:+.2f} deg"
        )


def run_probe(args: argparse.Namespace) -> int:
    """Execute the probe end-to-end and return a process exit code.

    Args:
        args: Parsed CLI namespace from :func:`build_parser`.

    Returns:
        Process exit code from the ``EXIT_*`` constants.
    """
    print(f"[probe] opening {args.device} @ {args.baud} baud")
    try:
        connection = open_connection(args.device, args.baud)
    except Exception as exc:
        print(f"PROBE FAIL: could not open {args.device}: {exc!r}")
        return EXIT_CONNECT_FAILED

    try:
        print(
            f"[probe] waiting for {args.heartbeats} heartbeat(s) "
            f"(first within {args.timeout:.1f}s)"
        )
        try:
            heartbeats = wait_for_heartbeats(
                connection, args.heartbeats, args.timeout
            )
        except TimeoutError as exc:
            print(f"PROBE FAIL: heartbeat timeout: {exc}")
            return EXIT_HEARTBEAT_TIMEOUT

        print_heartbeats(heartbeats)

        print(
            f"[probe] collecting ATTITUDE for {args.duration:.1f}s "
            f"(read-only; not requesting streams)"
        )
        samples = collect_attitude(connection, args.duration)
        print_attitude(samples)

        if not samples:
            print(
                "PROBE FAIL: no ATTITUDE messages received during the "
                f"{args.duration:.1f}s window"
            )
            return EXIT_ATTITUDE_TIMEOUT

        print("PROBE OK")
        return EXIT_OK
    finally:
        # Best-effort close. The probe is read-only so any close error is
        # cosmetic and must not mask the run_probe return code.
        try:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, validate, and dispatch to :func:`run_probe`.

    Args:
        argv: Optional argv override (mainly for tests). When ``None``,
            argparse reads from ``sys.argv[1:]``.

    Returns:
        Process exit code from the ``EXIT_*`` constants.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.heartbeats < 1:
        print("PROBE FAIL: --heartbeats must be >= 1")
        return EXIT_BAD_ARGS
    if args.duration <= 0:
        print("PROBE FAIL: --duration must be > 0")
        return EXIT_BAD_ARGS
    if args.timeout <= 0:
        print("PROBE FAIL: --timeout must be > 0")
        return EXIT_BAD_ARGS

    return run_probe(args)


if __name__ == "__main__":
    sys.exit(main())
