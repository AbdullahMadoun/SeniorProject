from __future__ import annotations

import re
from dataclasses import asdict, dataclass


ULOG_RELATIVE_PATH_PATTERN = re.compile(
    r"Opened full log file:\s+\./log/(?P<relative>[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{2}_[0-9]{2}_[0-9]{2}\.ulg)"
)
RECEIVER_LOG_PATTERN = re.compile(
    r"LANDING_TARGET rx:\s+position_valid=(?P<position_valid>\d+)\s+frame=(?P<frame>\d+)\s+"
    r"x=(?P<x>-?\d+\.\d+)\s+y=(?P<y>-?\d+\.\d+)\s+z=(?P<z>-?\d+\.\d+)"
)


@dataclass(frozen=True)
class ShellObservation:
    vehicle_status_seen: bool
    landing_target_pose_seen: bool
    never_published_seen: bool
    excerpt: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiverObservation:
    count: int
    first_match: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_ulog_relative_path(log_text: str) -> str | None:
    match = ULOG_RELATIVE_PATH_PATTERN.search(log_text)
    if not match:
        return None
    return match.group("relative")


def parse_shell_observation(shell_text: str) -> ShellObservation:
    stripped_lines = tuple(line.strip() for line in shell_text.splitlines() if line.strip())
    lowered_lines = tuple(line.lower() for line in stripped_lines)
    return ShellObservation(
        vehicle_status_seen=any("vehicle_status" in line for line in lowered_lines),
        landing_target_pose_seen=any("landing_target_pose" in line for line in lowered_lines),
        never_published_seen=any("never published" in line for line in lowered_lines),
        excerpt=stripped_lines[-20:],
    )


def parse_receiver_observation(log_text: str) -> ReceiverObservation:
    matches = list(RECEIVER_LOG_PATTERN.finditer(log_text))
    if not matches:
        return ReceiverObservation(count=0, first_match={})

    first = matches[0]
    return ReceiverObservation(
        count=len(matches),
        first_match={
            "position_valid": int(first.group("position_valid")),
            "frame": int(first.group("frame")),
            "x": float(first.group("x")),
            "y": float(first.group("y")),
            "z": float(first.group("z")),
        },
    )


def count_bridge_direction(log_text: str, *, bridge_name: str, direction: str) -> int:
    pattern = re.compile(rf"\[bridge\]\s+{re.escape(bridge_name)}\s+{re.escape(direction)}")
    return len(pattern.findall(log_text))
