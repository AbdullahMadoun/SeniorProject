from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass

os.environ.setdefault("MAVLINK20", "1")
os.environ.setdefault("MAVLINK_DIALECT", "common")

from pymavlink import mavutil  # type: ignore

mavutil.set_dialect("common")

LANDING_TARGET_ENDPOINT_PORTS = {
    "gcs": 14550,
    "offboard": 14540,
}
LANDING_TARGET_DIRECT_PX4_PORTS = {
    "gcs": 18570,
    "offboard": 14580,
}


@dataclass(frozen=True)
class LandingTargetSample:
    time_usec: int
    x_m: float
    y_m: float
    z_m: float
    target_num: int = 0
    frame: int = mavutil.mavlink.MAV_FRAME_LOCAL_NED
    angle_x_rad: float = 0.0
    angle_y_rad: float = 0.0
    distance_m: float = 0.0
    size_x_rad: float = 0.0
    size_y_rad: float = 0.0
    q: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    target_type: int = mavutil.mavlink.LANDING_TARGET_TYPE_VISION_FIDUCIAL
    position_valid: int = 1


def build_stationary_landing_target_samples(
    *,
    duration_s: float,
    rate_hz: float,
    x_m: float = 0.0,
    y_m: float = 0.0,
    z_m: float = 0.0,
) -> tuple[LandingTargetSample, ...]:
    interval_usec = int((1.0 / rate_hz) * 1_000_000)
    count = max(1, int(duration_s * rate_hz))
    base_time_usec = int(time.time() * 1_000_000)
    return tuple(
        LandingTargetSample(
            time_usec=base_time_usec + (index * interval_usec),
            x_m=x_m,
            y_m=y_m,
            z_m=z_m,
        )
        for index in range(count)
    )


def sample_to_dict(sample: LandingTargetSample) -> dict[str, object]:
    return asdict(sample)


def connection_string_for_endpoint(
    endpoint: str,
    *,
    bridge_ip: str | None,
    direct_px4: bool = False,
) -> str:
    ports = LANDING_TARGET_DIRECT_PX4_PORTS if direct_px4 else LANDING_TARGET_ENDPOINT_PORTS
    try:
        port = ports[endpoint]
    except KeyError as exc:
        valid = ", ".join(sorted(ports))
        raise ValueError(f"Unsupported landing-target endpoint '{endpoint}'. Valid endpoints: {valid}.") from exc

    host = bridge_ip or "127.0.0.1"
    return f"udpout:{host}:{port}"


def observer_connection_string_for_endpoint(
    endpoint: str,
    *,
    direct_px4: bool = False,
) -> str:
    try:
        if direct_px4:
            port = LANDING_TARGET_DIRECT_PX4_PORTS[endpoint]
            return f"udpout:127.0.0.1:{port}"
        port = LANDING_TARGET_ENDPOINT_PORTS[endpoint]
    except KeyError as exc:
        valid = ", ".join(sorted(LANDING_TARGET_ENDPOINT_PORTS))
        raise ValueError(f"Unsupported landing-target endpoint '{endpoint}'. Valid endpoints: {valid}.") from exc
    return f"udpin:0.0.0.0:{port}"


class LandingTargetPublisher:
    def __init__(
        self,
        connection_string: str = "udpout:127.0.0.1:14550",
        *,
        source_system: int = 245,
        source_component: int = 196,
    ) -> None:
        self._connection = mavutil.mavlink_connection(
            connection_string,
            source_system=source_system,
            source_component=source_component,
        )

    def send_sample(self, sample: LandingTargetSample) -> None:
        self._connection.mav.landing_target_send(
            sample.time_usec,
            sample.target_num,
            sample.frame,
            sample.angle_x_rad,
            sample.angle_y_rad,
            sample.distance_m,
            sample.size_x_rad,
            sample.size_y_rad,
            sample.x_m,
            sample.y_m,
            sample.z_m,
            sample.q,
            sample.target_type,
            sample.position_valid,
        )

    def send_samples(
        self,
        samples: tuple[LandingTargetSample, ...],
        *,
        rate_hz: float,
    ) -> int:
        interval_s = 1.0 / rate_hz
        sent_count = 0
        for sample in samples:
            self.send_sample(sample)
            sent_count += 1
            time.sleep(interval_s)
        return sent_count
