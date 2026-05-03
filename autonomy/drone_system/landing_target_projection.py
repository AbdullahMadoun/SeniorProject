from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

from .landing_target_stream import LandingTargetSample
from .models import VehicleLocalPose
from .precision_landing import (
    LandingTargetObservation,
    RelativeLandingTarget,
    estimate_relative_target,
)


@dataclass(frozen=True)
class DockTarget:
    north_m: float
    east_m: float
    down_m: float = 0.0


@dataclass(frozen=True)
class ProjectedLandingTargetFrame:
    vehicle_pose: VehicleLocalPose
    dock_target: DockTarget
    observation: LandingTargetObservation
    relative_target: RelativeLandingTarget
    target_north_m: float
    target_east_m: float
    target_down_m: float


def frame_to_dict(frame: ProjectedLandingTargetFrame) -> dict[str, object]:
    return asdict(frame)


def body_offset_to_local_ned(
    *,
    forward_m: float,
    right_m: float,
    down_m: float,
    yaw_rad: float,
) -> tuple[float, float, float]:
    north_m = (forward_m * math.cos(yaw_rad)) - (right_m * math.sin(yaw_rad))
    east_m = (forward_m * math.sin(yaw_rad)) + (right_m * math.cos(yaw_rad))
    return north_m, east_m, down_m


def local_ned_offset_to_body(
    *,
    north_m: float,
    east_m: float,
    down_m: float,
    yaw_rad: float,
) -> tuple[float, float, float]:
    forward_m = (north_m * math.cos(yaw_rad)) + (east_m * math.sin(yaw_rad))
    right_m = (-north_m * math.sin(yaw_rad)) + (east_m * math.cos(yaw_rad))
    return forward_m, right_m, down_m


def project_relative_target_to_local_ned(
    relative_target: RelativeLandingTarget,
    vehicle_pose: VehicleLocalPose,
) -> tuple[float, float, float]:
    north_offset_m, east_offset_m, down_offset_m = body_offset_to_local_ned(
        forward_m=relative_target.forward_error_m,
        right_m=relative_target.right_error_m,
        down_m=relative_target.down_error_m,
        yaw_rad=math.radians(vehicle_pose.yaw_deg),
    )
    return (
        vehicle_pose.north_m + north_offset_m,
        vehicle_pose.east_m + east_offset_m,
        vehicle_pose.down_m + down_offset_m,
    )


def build_projected_landing_target_frame(
    vehicle_pose: VehicleLocalPose,
    dock_target: DockTarget,
) -> ProjectedLandingTargetFrame:
    delta_north_m = dock_target.north_m - vehicle_pose.north_m
    delta_east_m = dock_target.east_m - vehicle_pose.east_m
    delta_down_m = dock_target.down_m - vehicle_pose.down_m
    forward_error_m, right_error_m, down_error_m = local_ned_offset_to_body(
        north_m=delta_north_m,
        east_m=delta_east_m,
        down_m=delta_down_m,
        yaw_rad=math.radians(vehicle_pose.yaw_deg),
    )
    range_m = max(down_error_m, 0.01)
    observation = LandingTargetObservation(
        acquired=True,
        quality=0.95,
        forward_angle_rad=math.atan2(forward_error_m, range_m),
        right_angle_rad=math.atan2(right_error_m, range_m),
        range_m=range_m,
    )
    relative_target = estimate_relative_target(observation)
    target_north_m, target_east_m, target_down_m = project_relative_target_to_local_ned(
        relative_target,
        vehicle_pose,
    )
    return ProjectedLandingTargetFrame(
        vehicle_pose=vehicle_pose,
        dock_target=dock_target,
        observation=observation,
        relative_target=relative_target,
        target_north_m=target_north_m,
        target_east_m=target_east_m,
        target_down_m=target_down_m,
    )


def sample_from_projected_frame(
    frame: ProjectedLandingTargetFrame,
    *,
    time_usec: int | None = None,
) -> LandingTargetSample:
    return LandingTargetSample(
        time_usec=int(time.time() * 1_000_000) if time_usec is None else time_usec,
        x_m=frame.target_north_m,
        y_m=frame.target_east_m,
        z_m=frame.target_down_m,
    )


def build_projected_approach_landing_target_samples(
    *,
    duration_s: float,
    rate_hz: float,
    dock_north_m: float = 1.25,
    dock_east_m: float = -0.75,
    dock_down_m: float = 0.0,
    initial_altitude_m: float = 8.0,
    final_altitude_m: float = 2.0,
    initial_north_error_m: float = 1.8,
    initial_east_error_m: float = -1.1,
    yaw_rad: float = 0.0,
) -> tuple[tuple[LandingTargetSample, ...], tuple[ProjectedLandingTargetFrame, ...]]:
    count = max(1, int(duration_s * rate_hz))
    interval_usec = int((1.0 / rate_hz) * 1_000_000)
    base_time_usec = int(time.time() * 1_000_000)
    dock_target = DockTarget(
        north_m=dock_north_m,
        east_m=dock_east_m,
        down_m=dock_down_m,
    )

    samples: list[LandingTargetSample] = []
    frames: list[ProjectedLandingTargetFrame] = []

    for index in range(count):
        progress = index / max(count - 1, 1)
        vehicle_pose = VehicleLocalPose(
            north_m=dock_target.north_m + (initial_north_error_m * (1.0 - progress)),
            east_m=dock_target.east_m + (initial_east_error_m * (1.0 - progress)),
            down_m=-(initial_altitude_m - ((initial_altitude_m - final_altitude_m) * progress)),
            yaw_deg=math.degrees(yaw_rad),
        )
        frame = build_projected_landing_target_frame(vehicle_pose, dock_target)
        samples.append(
            sample_from_projected_frame(
                frame,
                time_usec=base_time_usec + (index * interval_usec),
            )
        )
        frames.append(frame)

    return tuple(samples), tuple(frames)
