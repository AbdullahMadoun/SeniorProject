from __future__ import annotations

import argparse
import selectors
import socket
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PortBridge:
    name: str
    listen_port: int
    host_port: int
    px4_target_port: int


BRIDGES = (
    PortBridge(name="offboard", listen_port=14540, host_port=14540, px4_target_port=14580),
    PortBridge(name="gcs", listen_port=14550, host_port=14550, px4_target_port=18570),
)


def detect_windows_host_ip() -> str:
    result = subprocess.run(
        ["bash", "-lc", "ip route show default | awk '/default/ {print $3; exit}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    host_ip = result.stdout.strip()
    if result.returncode != 0 or not host_ip:
        raise RuntimeError("Unable to detect Windows host IP from default route.")
    return host_ip


def bind_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.setblocking(False)
    return sock


def run_bridge(host_ip: str) -> None:
    selector = selectors.DefaultSelector()
    sockets: dict[int, tuple[socket.socket, PortBridge]] = {}

    for bridge in BRIDGES:
        sock = bind_socket(bridge.listen_port)
        selector.register(sock, selectors.EVENT_READ, data=bridge)
        sockets[sock.fileno()] = (sock, bridge)
        print(
            f"[bridge] {bridge.name}: "
            f"0.0.0.0:{bridge.listen_port} <-> {host_ip}:{bridge.host_port} "
            f"(PX4 target 127.0.0.1:{bridge.px4_target_port})",
            flush=True,
        )

    try:
        while True:
            for key, _ in selector.select(timeout=1.0):
                sock, bridge = sockets[key.fd]
                payload, source = sock.recvfrom(65535)
                source_ip, _ = source
                if source_ip == host_ip:
                    destination = ("127.0.0.1", bridge.px4_target_port)
                    direction = "host->px4"
                else:
                    destination = (host_ip, bridge.host_port)
                    direction = "px4->host"
                sock.sendto(payload, destination)
                print(
                    f"[bridge] {bridge.name} {direction} "
                    f"{source_ip}:{source[1]} -> {destination[0]}:{destination[1]} "
                    f"bytes={len(payload)}",
                    flush=True,
                )
    finally:
        for sock, _ in sockets.values():
            selector.unregister(sock)
            sock.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge PX4 SITL MAVLink UDP traffic from WSL to the Windows host."
    )
    parser.add_argument(
        "--host-ip",
        help="Windows host IP. Defaults to the WSL default gateway.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    host_ip = args.host_ip or detect_windows_host_ip()
    print(f"[bridge] using Windows host IP {host_ip}", flush=True)
    run_bridge(host_ip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
