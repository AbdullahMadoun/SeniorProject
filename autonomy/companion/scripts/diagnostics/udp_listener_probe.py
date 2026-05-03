"""UDP listener probe for MAVLink datagrams.

Read-only diagnostic script. Binds a UDP socket on ``host:port`` and
counts incoming datagrams whose first byte matches the MAVLink v1
(``0xFE``) or v2 (``0xFD``) magic. The probe does not parse, validate,
acknowledge, or forward any packet — it only counts.

The probe is intended to verify a MAVLink bridge (e.g. MAVProxy reading
``/dev/ttyACM0`` and emitting to ``udpout:127.0.0.1:<port>``) is
producing traffic on the wire. Running this against any active MAVLink
producer should not perturb it: a UDP ``--out`` is fire-and-forget from
the producer's side.

On success the final stdout line is ``PROBE OK``; on failure
``PROBE FAIL: <reason>``. Distinct non-zero exit codes per failure mode.

Run with the companion venv::

    cd /home/pi/SeniorProject
    autonomy/companion/.venv-pi/bin/python \\
        -m autonomy.companion.scripts.diagnostics.udp_listener_probe \\
        --port 14551
"""
from __future__ import annotations

import argparse
import socket
import sys
import time

# Distinct exit codes so callers (and the systemd journal) can disambiguate
# failure modes without parsing stdout.
EXIT_OK: int = 0
EXIT_BAD_ARGS: int = 1
EXIT_BIND_FAILED: int = 2
EXIT_INSUFFICIENT_PACKETS: int = 3

# MAVLink wire magic bytes. v1 frames start with 0xFE, v2 with 0xFD.
_MAVLINK_V1_MAGIC: int = 0xFE
_MAVLINK_V2_MAGIC: int = 0xFD

# Cap per-recvfrom timeout so the loop exits promptly when the overall
# duration deadline expires, even if no packets are arriving.
_RECV_TIMEOUT_CAP_S: float = 0.5

# Generous read buffer: a MAVLink v2 frame caps at 280 bytes, but UDP
# datagrams from MAVProxy may carry larger STATUSTEXT or raw bytes;
# 4096 covers anything plausible without over-allocating.
_RECV_BUFFER_BYTES: int = 4096


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the UDP listener CLI.

    Returns:
        Configured parser with the four documented flags. ``--port`` is
        required; the others have defaults.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Read-only probe: bind a UDP socket and count incoming MAVLink "
            "datagrams to verify a UART->UDP bridge is producing traffic."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="UDP port to bind (required).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Seconds to listen before deciding pass/fail (default: 5).",
    )
    parser.add_argument(
        "--min-packets",
        type=int,
        default=10,
        help=(
            "Minimum number of MAVLink-magic datagrams required to pass "
            "(default: 10)."
        ),
    )
    return parser


def open_socket(host: str, port: int) -> socket.socket:
    """Open and bind a UDP socket on ``host:port``.

    The socket is non-blocking-ish: a per-recv timeout is set inside
    :func:`count_packets` rather than here, so the caller can adjust it
    against an external deadline.

    Args:
        host: Bind address.
        port: UDP port (1..65535).

    Returns:
        Bound :class:`socket.socket` ready for ``recvfrom``.

    Raises:
        OSError: If the bind fails (port in use, permission denied, etc.).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # SO_REUSEADDR lets us re-run the probe quickly after a previous
    # socket is in TIME_WAIT; safe for a localhost diagnostic.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    return sock


def count_packets(sock: socket.socket, duration_s: float) -> tuple[int, int, int]:
    """Receive UDP datagrams for ``duration_s`` and classify them.

    Each datagram is inspected only by its first byte: ``0xFE`` is
    counted as MAVLink v1, ``0xFD`` as MAVLink v2, anything else as
    "other". The probe does not validate framing, length, CRCs, or
    sequence numbers.

    Args:
        sock: Bound UDP socket from :func:`open_socket`.
        duration_s: Wall-clock seconds to listen. Must be > 0.

    Returns:
        Tuple ``(total, mavlink_v1, mavlink_v2)``. ``total`` counts every
        datagram received (including zero-length and "other"); the per-
        version counters sum to at most ``total``.
    """
    total = 0
    v1 = 0
    v2 = 0
    deadline_mono = time.monotonic() + duration_s

    while True:
        remaining = deadline_mono - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(min(remaining, _RECV_TIMEOUT_CAP_S))
        try:
            data, _addr = sock.recvfrom(_RECV_BUFFER_BYTES)
        except (TimeoutError, socket.timeout):
            # Timed out waiting for the next datagram; loop checks the
            # outer deadline and may exit, otherwise tries again.
            continue

        total += 1
        if not data:
            continue
        first = data[0]
        if first == _MAVLINK_V1_MAGIC:
            v1 += 1
        elif first == _MAVLINK_V2_MAGIC:
            v2 += 1

    return total, v1, v2


def run_probe(args: argparse.Namespace) -> int:
    """Execute the listener probe end-to-end and return a process exit code.

    Args:
        args: Parsed CLI namespace from :func:`build_parser`.

    Returns:
        Process exit code from the ``EXIT_*`` constants.
    """
    print(f"[probe] binding UDP {args.host}:{args.port}")
    try:
        sock = open_socket(args.host, args.port)
    except OSError as exc:
        print(
            f"PROBE FAIL: bind to {args.host}:{args.port} failed: {exc!r}"
        )
        return EXIT_BIND_FAILED

    try:
        print(
            f"[probe] counting datagrams for {args.duration:.1f}s "
            f"(need >= {args.min_packets} MAVLink datagram(s))"
        )
        total, v1, v2 = count_packets(sock, args.duration)
        mavlink_total = v1 + v2
        other = total - mavlink_total
        print(
            f"[probe] received {total} datagram(s) "
            f"(mavlink_v1={v1}, mavlink_v2={v2}, other={other})"
        )

        if mavlink_total < args.min_packets:
            print(
                f"PROBE FAIL: only {mavlink_total} MAVLink datagram(s) "
                f"in {args.duration:.1f}s; needed >= {args.min_packets}"
            )
            return EXIT_INSUFFICIENT_PACKETS

        print("PROBE OK")
        return EXIT_OK
    finally:
        try:
            sock.close()
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

    if args.duration <= 0:
        print("PROBE FAIL: --duration must be > 0")
        return EXIT_BAD_ARGS
    if args.min_packets < 1:
        print("PROBE FAIL: --min-packets must be >= 1")
        return EXIT_BAD_ARGS
    if args.port <= 0 or args.port > 65535:
        print("PROBE FAIL: --port must be in 1..65535")
        return EXIT_BAD_ARGS

    return run_probe(args)


if __name__ == "__main__":
    sys.exit(main())
