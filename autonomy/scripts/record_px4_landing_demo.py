from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.landing_target_projection import (
    DockTarget,
    build_projected_landing_target_frame,
    local_ned_offset_to_body,
)
from autonomy.drone_system.models import VehicleLocalPose
from autonomy.drone_system.precision_landing import (
    LandingTargetObservation,
    PrecisionLandingController,
    PrecisionLandingPhase,
    PrecisionLandingTuning,
)
from autonomy.drone_system.precision_landing_px4 import configure_px4_precision_landing
from autonomy.scripts.export_landing_demo_data import (
    OUTPUT_DIR,
    OUTPUT_JSON_PATH,
    PROOF_SOURCE_LIVE_PX4_SITL,
    build_command_entry,
    build_demo_proof,
    build_event_entry,
    sync_embedded_payload,
)

try:
    from mavsdk import System  # type: ignore
    from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw  # type: ignore
except ImportError:  # pragma: no cover
    System = None  # type: ignore[assignment]
    OffboardError = Exception  # type: ignore[assignment]
    PositionNedYaw = None  # type: ignore[assignment]
    VelocityNedYaw = None  # type: ignore[assignment]


SYSTEM_ADDRESS = "udp://:14540"
CONTROL_RATE_HZ = 10.0
CONTROL_INTERVAL_S = 1.0 / CONTROL_RATE_HZ
TAKEOFF_ALTITUDE_M = 6.0
APPROACH_NORTH_M = 5.0
APPROACH_EAST_M = 3.0
APPROACH_TOLERANCE_M = 0.6
APPROACH_TIMEOUT_S = 30.0
LANDING_TIMEOUT_S = 120.0
TOUCHDOWN_TIMEOUT_S = 30.0
CAMERA_HALF_ANGLE_RAD = math.radians(55.0)
CAMERA_MIN_RANGE_M = 0.15
STATE_FILE = Path(
    os.environ.get(
        "SKYLINK_COMPANION_STATE_FILE",
        str(Path(tempfile.gettempdir()) / "skylink_drone_state.json"),
    )
)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class LiveTelemetryState:
    position_velocity_ned: Any | None = None
    attitude_euler: Any | None = None
    in_air: bool = False
    landed_state: str | None = None
    flight_mode: str | None = None


def log_stage(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[{timestamp}] {message}", flush=True)


def current_recording_time_s(recording_start_s: float | None) -> float:
    if recording_start_s is None:
        return 0.0
    return max(0.0, time.monotonic() - recording_start_s)


def record_event(
    events: list[dict[str, object]],
    *,
    recording_start_s: float | None,
    kind: str,
    message: str,
    level: str = "info",
    summary: str | None = None,
    context: dict[str, object] | None = None,
) -> None:
    events.append(
        build_event_entry(
            current_recording_time_s(recording_start_s),
            kind=kind,
            message=message,
            level=level,
            summary=summary,
            context=context,
        )
    )


def controller_body_to_local_velocity(
    *,
    forward_velocity_mps: float,
    right_velocity_mps: float,
    yaw_deg: float,
) -> tuple[float, float]:
    yaw_rad = math.radians(yaw_deg)
    north_velocity_mps = (-forward_velocity_mps * math.cos(yaw_rad)) + (
        right_velocity_mps * math.sin(yaw_rad)
    )
    east_velocity_mps = (-forward_velocity_mps * math.sin(yaw_rad)) - (
        right_velocity_mps * math.cos(yaw_rad)
    )
    return north_velocity_mps, east_velocity_mps


def local_velocity_to_controller_body(
    *,
    north_velocity_mps: float,
    east_velocity_mps: float,
    yaw_deg: float,
) -> tuple[float, float]:
    forward_velocity_mps, right_velocity_mps, _ = local_ned_offset_to_body(
        north_m=north_velocity_mps,
        east_m=east_velocity_mps,
        down_m=0.0,
        yaw_rad=math.radians(yaw_deg),
    )
    return -forward_velocity_mps, -right_velocity_mps


def build_visibility_observation(
    vehicle_pose: VehicleLocalPose,
    dock_target: DockTarget,
) -> tuple[LandingTargetObservation, dict[str, float]]:
    projected_frame = build_projected_landing_target_frame(vehicle_pose, dock_target)
    delta_north_m = dock_target.north_m - vehicle_pose.north_m
    delta_east_m = dock_target.east_m - vehicle_pose.east_m
    delta_down_m = dock_target.down_m - vehicle_pose.down_m
    forward_offset_m, right_offset_m, down_offset_m = local_ned_offset_to_body(
        north_m=delta_north_m,
        east_m=delta_east_m,
        down_m=delta_down_m,
        yaw_rad=math.radians(vehicle_pose.yaw_deg),
    )
    range_m = max(down_offset_m, CAMERA_MIN_RANGE_M)
    forward_angle_rad = math.atan2(forward_offset_m, range_m)
    right_angle_rad = math.atan2(right_offset_m, range_m)
    in_view = (
        down_offset_m > CAMERA_MIN_RANGE_M
        and abs(forward_angle_rad) <= CAMERA_HALF_ANGLE_RAD
        and abs(right_angle_rad) <= CAMERA_HALF_ANGLE_RAD
    )
    angle_ratio = max(abs(forward_angle_rad), abs(right_angle_rad)) / CAMERA_HALF_ANGLE_RAD
    quality = 0.0 if not in_view else max(0.6, 1.0 - (angle_ratio * 0.35))
    observation = LandingTargetObservation(
        acquired=in_view,
        quality=quality,
        forward_angle_rad=forward_angle_rad if in_view else 0.0,
        right_angle_rad=right_angle_rad if in_view else 0.0,
        range_m=range_m,
    )
    return observation, {
        "target_north_m": projected_frame.target_north_m,
        "target_east_m": projected_frame.target_east_m,
        "forward_error_m": projected_frame.relative_target.forward_error_m,
        "right_error_m": projected_frame.relative_target.right_error_m,
        "horizontal_error_m": projected_frame.relative_target.horizontal_error_m,
        "altitude_m": max(0.0, -vehicle_pose.down_m),
    }


def pose_from_live_telemetry(telemetry_state: LiveTelemetryState) -> VehicleLocalPose | None:
    position_velocity_ned = telemetry_state.position_velocity_ned
    attitude_euler = telemetry_state.attitude_euler
    if position_velocity_ned is None or attitude_euler is None:
        return None
    return VehicleLocalPose(
        north_m=float(position_velocity_ned.position.north_m),
        east_m=float(position_velocity_ned.position.east_m),
        down_m=float(position_velocity_ned.position.down_m),
        yaw_deg=float(attitude_euler.yaw_deg),
        roll_deg=float(attitude_euler.roll_deg),
        pitch_deg=float(attitude_euler.pitch_deg),
    )


def append_frame(
    frames: list[dict[str, float | str]],
    *,
    t_s: float,
    vehicle_pose: VehicleLocalPose,
    geometry: dict[str, float],
    phase: str,
    forward_velocity_mps: float,
    right_velocity_mps: float,
) -> None:
    frames.append(
        {
            "t": round(t_s, 3),
            "north_m": round(vehicle_pose.north_m, 6),
            "east_m": round(vehicle_pose.east_m, 6),
            "down_m": round(vehicle_pose.down_m, 6),
            "target_north_m": round(geometry["target_north_m"], 6),
            "target_east_m": round(geometry["target_east_m"], 6),
            "phase": phase,
            "horizontal_error_m": round(geometry["horizontal_error_m"], 6),
            "altitude_m": round(geometry["altitude_m"], 6),
            "forward_vel": round(forward_velocity_mps, 6),
            "right_vel": round(right_velocity_mps, 6),
            "forward_error_m": round(geometry["forward_error_m"], 6),
            "right_error_m": round(geometry["right_error_m"], 6),
        }
    )


def build_companion_state_payload(
    *,
    vehicle_pose: VehicleLocalPose,
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    phase: str,
) -> dict[str, float | str | bool]:
    position_velocity_ned = telemetry_state.position_velocity_ned
    north_velocity_mps = 0.0
    east_velocity_mps = 0.0
    if position_velocity_ned is not None:
        north_velocity_mps = float(position_velocity_ned.velocity.north_m_s)
        east_velocity_mps = float(position_velocity_ned.velocity.east_m_s)
    return {
        "altitude_m": round(max(0.0, -vehicle_pose.down_m), 6),
        "offset_x_m": round(vehicle_pose.east_m - dock_target.east_m, 6),
        "offset_y_m": round(vehicle_pose.north_m - dock_target.north_m, 6),
        "roll_rad": round(math.radians(vehicle_pose.roll_deg), 6),
        "pitch_rad": round(math.radians(vehicle_pose.pitch_deg), 6),
        "vel_xy_ms": round(math.hypot(north_velocity_mps, east_velocity_mps), 6),
        "fsm_state": phase,
        "noise_enabled": True,
        "drop_prob": 0.0,
    }


def write_companion_state(
    *,
    vehicle_pose: VehicleLocalPose,
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    phase: str,
) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = build_companion_state_payload(
        vehicle_pose=vehicle_pose,
        telemetry_state=telemetry_state,
        dock_target=dock_target,
        phase=phase,
    )
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def wait_for_connection(drone: System, *, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    async for state in drone.core.connection_state():
        if state.is_connected:
            return
        if time.monotonic() >= deadline:
            break
    raise RuntimeError(f"Timed out connecting to PX4 at {SYSTEM_ADDRESS}.")


async def wait_for_health(drone: System, *, timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    async for health in drone.telemetry.health():
        if getattr(health, "is_global_position_ok", False) and getattr(
            health, "is_home_position_ok", False
        ):
            return
        if time.monotonic() >= deadline:
            break
    raise RuntimeError("Timed out waiting for PX4 global/home position health.")


async def wait_for_pose(
    telemetry_state: LiveTelemetryState,
    *,
    timeout_s: float = 20.0,
) -> VehicleLocalPose:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        vehicle_pose = pose_from_live_telemetry(telemetry_state)
        if vehicle_pose is not None:
            return vehicle_pose
        await asyncio.sleep(0.1)
    raise RuntimeError("Timed out waiting for live PX4 local pose telemetry.")


async def monitor_stream(stream, setter) -> None:
    async for item in stream:
        setter(item)


async def configure_telemetry_rates(drone: System) -> None:
    rate_requests = (
        ("set_rate_position_velocity_ned", CONTROL_RATE_HZ),
        ("set_rate_attitude_euler", CONTROL_RATE_HZ),
        ("set_rate_in_air", 2.0),
        ("set_rate_landed_state", 2.0),
        ("set_rate_flight_mode", 2.0),
    )
    telemetry = drone.telemetry
    for method_name, rate_hz in rate_requests:
        method = getattr(telemetry, method_name, None)
        if method is None:
            continue
        with contextlib.suppress(Exception):
            await method(rate_hz)


async def run_takeoff_phase(
    drone: System,
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    frames: list[dict[str, float | str]],
    events: list[dict[str, object]],
    commands: list[dict[str, object]],
    *,
    recording_start_s: float,
) -> VehicleLocalPose:
    log_stage(f"Takeoff start: target_altitude_m={TAKEOFF_ALTITUDE_M}")
    record_event(
        events,
        recording_start_s=recording_start_s,
        kind="action",
        message="Takeoff sequence started",
        summary=f"target_altitude={TAKEOFF_ALTITUDE_M:.1f} m",
    )
    await drone.action.set_takeoff_altitude(TAKEOFF_ALTITUDE_M)
    await drone.action.arm()
    commands.append(
        build_command_entry(
            current_recording_time_s(recording_start_s),
            phase="TAKEOFF",
            command_type="arm",
            source="mavsdk_action",
            note="PX4 arm command issued",
        )
    )
    await drone.action.takeoff()
    commands.append(
        build_command_entry(
            current_recording_time_s(recording_start_s),
            phase="TAKEOFF",
            command_type="takeoff",
            source="mavsdk_action",
            target_down_m=-TAKEOFF_ALTITUDE_M,
            note="PX4 takeoff command issued",
        )
    )

    while True:
        vehicle_pose = await wait_for_pose(telemetry_state, timeout_s=5.0)
        _, geometry = build_visibility_observation(vehicle_pose, dock_target)
        forward_vel, right_vel = (0.0, 0.0)
        position_velocity_ned = telemetry_state.position_velocity_ned
        if position_velocity_ned is not None:
            forward_vel, right_vel = local_velocity_to_controller_body(
                north_velocity_mps=float(position_velocity_ned.velocity.north_m_s),
                east_velocity_mps=float(position_velocity_ned.velocity.east_m_s),
                yaw_deg=vehicle_pose.yaw_deg,
            )
        append_frame(
            frames,
            t_s=time.monotonic() - recording_start_s,
            vehicle_pose=vehicle_pose,
            geometry=geometry,
            phase="TAKEOFF",
            forward_velocity_mps=forward_vel,
            right_velocity_mps=right_vel,
        )
        write_companion_state(
            vehicle_pose=vehicle_pose,
            telemetry_state=telemetry_state,
            dock_target=dock_target,
            phase="TAKEOFF",
        )
        if geometry["altitude_m"] >= TAKEOFF_ALTITUDE_M - 0.5 and telemetry_state.in_air:
            log_stage(
                f"Takeoff complete: altitude_m={geometry['altitude_m']:.2f} "
                f"north_m={vehicle_pose.north_m:.2f} east_m={vehicle_pose.east_m:.2f}"
            )
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="state",
                message="PX4 takeoff complete",
                summary=(
                    f"altitude={geometry['altitude_m']:.2f} m "
                    f"north={vehicle_pose.north_m:.2f} east={vehicle_pose.east_m:.2f}"
                ),
            )
            return vehicle_pose
        await asyncio.sleep(CONTROL_INTERVAL_S)


async def start_offboard(
    drone: System,
    vehicle_pose: VehicleLocalPose,
    events: list[dict[str, object]],
    commands: list[dict[str, object]],
    *,
    recording_start_s: float,
) -> None:
    if PositionNedYaw is None:
        raise RuntimeError("mavsdk offboard plugin is unavailable.")
    log_stage(
        "Offboard start: "
        f"north_m={vehicle_pose.north_m:.2f} east_m={vehicle_pose.east_m:.2f} down_m={vehicle_pose.down_m:.2f}"
    )
    await drone.offboard.set_position_ned(
        PositionNedYaw(
            vehicle_pose.north_m,
            vehicle_pose.east_m,
            vehicle_pose.down_m,
            vehicle_pose.yaw_deg,
        )
    )
    commands.append(
        build_command_entry(
            current_recording_time_s(recording_start_s),
            phase="APPROACH",
            command_type="position_ned",
            source="mavsdk_offboard",
            target_north_m=vehicle_pose.north_m,
            target_east_m=vehicle_pose.east_m,
            target_down_m=vehicle_pose.down_m,
            yaw_deg=vehicle_pose.yaw_deg,
            note="Initial offboard hold setpoint",
        )
    )
    await drone.offboard.start()
    record_event(
        events,
        recording_start_s=recording_start_s,
        kind="action",
        message="Offboard mode started",
        summary=(
            f"hold north={vehicle_pose.north_m:.2f} east={vehicle_pose.east_m:.2f} "
            f"down={vehicle_pose.down_m:.2f}"
        ),
    )


async def run_approach_phase(
    drone: System,
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    frames: list[dict[str, float | str]],
    events: list[dict[str, object]],
    commands: list[dict[str, object]],
    *,
    recording_start_s: float,
) -> VehicleLocalPose:
    if PositionNedYaw is None:
        raise RuntimeError("mavsdk offboard plugin is unavailable.")
    log_stage(
        f"Approach start: target_north_m={APPROACH_NORTH_M} "
        f"target_east_m={APPROACH_EAST_M} target_altitude_m={TAKEOFF_ALTITUDE_M}"
    )
    record_event(
        events,
        recording_start_s=recording_start_s,
        kind="command",
        message="Cinematic approach leg started",
        summary=(
            f"target_north={APPROACH_NORTH_M:.1f} m "
            f"target_east={APPROACH_EAST_M:.1f} m altitude={TAKEOFF_ALTITUDE_M:.1f} m"
        ),
    )
    deadline = time.monotonic() + APPROACH_TIMEOUT_S
    while time.monotonic() < deadline:
        vehicle_pose = await wait_for_pose(telemetry_state, timeout_s=5.0)
        await drone.offboard.set_position_ned(
            PositionNedYaw(
                APPROACH_NORTH_M,
                APPROACH_EAST_M,
                -TAKEOFF_ALTITUDE_M,
                vehicle_pose.yaw_deg,
            )
        )
        commands.append(
            build_command_entry(
                current_recording_time_s(recording_start_s),
                phase="APPROACH",
                command_type="position_ned",
                source="mavsdk_offboard",
                target_north_m=APPROACH_NORTH_M,
                target_east_m=APPROACH_EAST_M,
                target_down_m=-TAKEOFF_ALTITUDE_M,
                yaw_deg=vehicle_pose.yaw_deg,
                note="Cinematic offset approach setpoint",
            )
        )
        _, geometry = build_visibility_observation(vehicle_pose, dock_target)
        position_velocity_ned = telemetry_state.position_velocity_ned
        forward_vel, right_vel = (0.0, 0.0)
        if position_velocity_ned is not None:
            forward_vel, right_vel = local_velocity_to_controller_body(
                north_velocity_mps=float(position_velocity_ned.velocity.north_m_s),
                east_velocity_mps=float(position_velocity_ned.velocity.east_m_s),
                yaw_deg=vehicle_pose.yaw_deg,
            )
        append_frame(
            frames,
            t_s=time.monotonic() - recording_start_s,
            vehicle_pose=vehicle_pose,
            geometry=geometry,
            phase="APPROACH",
            forward_velocity_mps=forward_vel,
            right_velocity_mps=right_vel,
        )
        write_companion_state(
            vehicle_pose=vehicle_pose,
            telemetry_state=telemetry_state,
            dock_target=dock_target,
            phase="APPROACH",
        )
        horizontal_distance_m = math.hypot(
            vehicle_pose.north_m - APPROACH_NORTH_M,
            vehicle_pose.east_m - APPROACH_EAST_M,
        )
        altitude_error_m = abs((-TAKEOFF_ALTITUDE_M) - vehicle_pose.down_m)
        if horizontal_distance_m <= APPROACH_TOLERANCE_M and altitude_error_m <= 0.8:
            log_stage(
                f"Approach complete: north_m={vehicle_pose.north_m:.2f} "
                f"east_m={vehicle_pose.east_m:.2f} altitude_m={geometry['altitude_m']:.2f}"
            )
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="state",
                message="Approach leg reached",
                summary=(
                    f"north={vehicle_pose.north_m:.2f} east={vehicle_pose.east_m:.2f} "
                    f"altitude={geometry['altitude_m']:.2f} m"
                ),
            )
            return vehicle_pose
        await asyncio.sleep(CONTROL_INTERVAL_S)
    raise RuntimeError("Timed out moving to the cinematic approach offset.")


async def run_precision_landing_phase(
    drone: System,
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    controller: PrecisionLandingController,
    frames: list[dict[str, float | str]],
    events: list[dict[str, object]],
    commands: list[dict[str, object]],
    *,
    recording_start_s: float,
) -> None:
    if VelocityNedYaw is None:
        raise RuntimeError("mavsdk offboard plugin is unavailable.")
    deadline = time.monotonic() + LANDING_TIMEOUT_S
    handed_off_to_land = False
    last_phase: PrecisionLandingPhase | None = None
    target_acquired_logged = False
    companion_managed_descent = _env_flag("SKYLINK_ENABLE_COMPANION_SIM")

    while time.monotonic() < deadline:
        loop_start_s = time.monotonic()
        vehicle_pose = await wait_for_pose(telemetry_state, timeout_s=5.0)
        observation, geometry = build_visibility_observation(vehicle_pose, dock_target)
        state = controller.step(observation, time_s=loop_start_s - recording_start_s)

        if observation.acquired and not target_acquired_logged:
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="target",
                message="QR landing target acquired",
                summary=(
                    f"range={observation.range_m:.2f} m "
                    f"horizontal_error={geometry['horizontal_error_m']:.2f} m"
                ),
            )
            target_acquired_logged = True

        if state.phase != last_phase:
            log_stage(
                "Precision landing phase="
                f"{state.phase.name} acquired={observation.acquired} "
                f"horizontal_error_m={geometry['horizontal_error_m']:.2f} "
                f"altitude_m={geometry['altitude_m']:.2f}"
            )
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="phase",
                message=f"Precision landing phase changed to {state.phase.name}",
                summary=(
                    f"target_acquired={observation.acquired} "
                    f"horizontal_error={geometry['horizontal_error_m']:.2f} m "
                    f"altitude={geometry['altitude_m']:.2f} m"
                ),
            )
            last_phase = state.phase

        if state.phase == PrecisionLandingPhase.ABORT:
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="abort",
                message="Precision landing controller aborted",
                level="error",
                summary="PX4 landing takeover stopped because target tracking was lost.",
            )
            raise RuntimeError("Precision landing controller aborted after losing the target.")

        append_frame(
            frames,
            t_s=loop_start_s - recording_start_s,
            vehicle_pose=vehicle_pose,
            geometry=geometry,
            phase=state.phase.name,
            forward_velocity_mps=float(state.command.forward_velocity_mps),
            right_velocity_mps=float(state.command.right_velocity_mps),
        )
        write_companion_state(
            vehicle_pose=vehicle_pose,
            telemetry_state=telemetry_state,
            dock_target=dock_target,
            phase=state.phase.name,
        )

        if not handed_off_to_land:
            if companion_managed_descent and state.phase in {
                PrecisionLandingPhase.DESCEND,
                PrecisionLandingPhase.FLARE,
            }:
                log_stage("Companion-managed descent enabled; handing off to PX4 land mode")
                with contextlib.suppress(OffboardError, RuntimeError):
                    await drone.offboard.stop()
                await drone.action.land()
                commands.append(
                    build_command_entry(
                        current_recording_time_s(recording_start_s),
                        phase=state.phase.name,
                        command_type="land",
                        source="mavsdk_action",
                        note="Companion-managed descent handed off to PX4 land mode",
                    )
                )
                record_event(
                    events,
                    recording_start_s=recording_start_s,
                    kind="handoff",
                    message="Precision controller handed off to PX4 land mode",
                    summary=f"phase={state.phase.name} via companion-managed descent",
                )
                handed_off_to_land = True
                await asyncio.sleep(CONTROL_INTERVAL_S)
                continue
            north_velocity_mps, east_velocity_mps = controller_body_to_local_velocity(
                forward_velocity_mps=float(state.command.forward_velocity_mps),
                right_velocity_mps=float(state.command.right_velocity_mps),
                yaw_deg=vehicle_pose.yaw_deg,
            )
            await drone.offboard.set_velocity_ned(
                VelocityNedYaw(
                    north_velocity_mps,
                    east_velocity_mps,
                    float(state.command.descent_rate_mps),
                    vehicle_pose.yaw_deg,
                )
            )
            commands.append(
                build_command_entry(
                    current_recording_time_s(recording_start_s),
                    phase=state.phase.name,
                    command_type="velocity_ned",
                    source="precision_landing_controller",
                    forward_velocity_mps=float(state.command.forward_velocity_mps),
                    right_velocity_mps=float(state.command.right_velocity_mps),
                    down_velocity_mps=float(state.command.descent_rate_mps),
                    north_velocity_mps=north_velocity_mps,
                    east_velocity_mps=east_velocity_mps,
                    yaw_deg=vehicle_pose.yaw_deg,
                    note="Offboard velocity command sent to PX4",
                )
            )
            if state.phase == PrecisionLandingPhase.TOUCHDOWN:
                log_stage("Controller reached TOUCHDOWN window; handing off to PX4 land mode")
                with contextlib.suppress(OffboardError, RuntimeError):
                    await drone.offboard.stop()
                await drone.action.land()
                commands.append(
                    build_command_entry(
                        current_recording_time_s(recording_start_s),
                        phase=state.phase.name,
                        command_type="land",
                        source="mavsdk_action",
                        note="Touchdown window reached; PX4 land handoff issued",
                    )
                )
                record_event(
                    events,
                    recording_start_s=recording_start_s,
                    kind="handoff",
                    message="Touchdown window reached; PX4 land mode commanded",
                    summary=f"horizontal_error={geometry['horizontal_error_m']:.3f} m",
                )
                handed_off_to_land = True
        else:
            if not telemetry_state.in_air and geometry["altitude_m"] <= 0.15:
                log_stage("PX4 reported landed after land handoff")
                record_event(
                    events,
                    recording_start_s=recording_start_s,
                    kind="state",
                    message="PX4 reported landed after land handoff",
                    summary=f"horizontal_error={geometry['horizontal_error_m']:.3f} m",
                )
                return

        await asyncio.sleep(max(0.0, CONTROL_INTERVAL_S - (time.monotonic() - loop_start_s)))

    raise RuntimeError("Timed out completing the live precision landing sequence.")


async def finalize_touchdown(
    telemetry_state: LiveTelemetryState,
    dock_target: DockTarget,
    frames: list[dict[str, float | str]],
    events: list[dict[str, object]],
    *,
    recording_start_s: float,
) -> None:
    deadline = time.monotonic() + TOUCHDOWN_TIMEOUT_S
    while time.monotonic() < deadline:
        vehicle_pose = await wait_for_pose(telemetry_state, timeout_s=5.0)
        _, geometry = build_visibility_observation(vehicle_pose, dock_target)
        position_velocity_ned = telemetry_state.position_velocity_ned
        forward_vel, right_vel = (0.0, 0.0)
        if position_velocity_ned is not None:
            forward_vel, right_vel = local_velocity_to_controller_body(
                north_velocity_mps=float(position_velocity_ned.velocity.north_m_s),
                east_velocity_mps=float(position_velocity_ned.velocity.east_m_s),
                yaw_deg=vehicle_pose.yaw_deg,
            )
        append_frame(
            frames,
            t_s=time.monotonic() - recording_start_s,
            vehicle_pose=vehicle_pose,
            geometry=geometry,
            phase="TOUCHDOWN",
            forward_velocity_mps=forward_vel,
            right_velocity_mps=right_vel,
        )
        write_companion_state(
            vehicle_pose=vehicle_pose,
            telemetry_state=telemetry_state,
            dock_target=dock_target,
            phase="TOUCHDOWN",
        )
        if not telemetry_state.in_air and geometry["altitude_m"] <= 0.15:
            log_stage(
                f"Touchdown complete: north_m={vehicle_pose.north_m:.2f} "
                f"east_m={vehicle_pose.east_m:.2f} horizontal_error_m={geometry['horizontal_error_m']:.3f}"
            )
            record_event(
                events,
                recording_start_s=recording_start_s,
                kind="summary",
                message="Touchdown complete",
                summary=(
                    f"north={vehicle_pose.north_m:.2f} east={vehicle_pose.east_m:.2f} "
                    f"horizontal_error={geometry['horizontal_error_m']:.3f} m"
                ),
            )
            return
        await asyncio.sleep(CONTROL_INTERVAL_S)
    raise RuntimeError("Timed out waiting for PX4 to report touchdown after land handoff.")


async def main_async() -> None:
    if System is None:
        raise RuntimeError("mavsdk is not installed in the active Python environment.")

    baseline = load_system_baseline()
    tuning = PrecisionLandingTuning()
    controller = PrecisionLandingController(baseline, tuning)
    controller.reset()
    dock_target = DockTarget(
        north_m=1.25,
        east_m=-0.75,
        down_m=baseline.docking.dock_center_down_m,
    )
    log_stage(
        f"Recorder start: system_address={SYSTEM_ADDRESS} "
        f"dock_north_m={dock_target.north_m} dock_east_m={dock_target.east_m}"
    )

    telemetry_state = LiveTelemetryState()
    frames: list[dict[str, float | str]] = []
    events: list[dict[str, object]] = []
    commands: list[dict[str, object]] = []
    flight_modes_seen: set[str] = set()
    recording_start_s: float | None = None
    applied_parameter_count = 0
    drone = System()
    await drone.connect(system_address=SYSTEM_ADDRESS)
    await wait_for_connection(drone)
    log_stage("PX4 connection established")
    record_event(
        events,
        recording_start_s=recording_start_s,
        kind="connection",
        message="PX4 connection established",
        summary=f"vehicle_link={SYSTEM_ADDRESS}",
    )
    with contextlib.suppress(Exception):
        applied = await configure_px4_precision_landing(drone, baseline, tuning)
        applied_parameter_count = len(applied)
        log_stage(f"PX4 precision-landing parameters applied: count={len(applied)}")
        record_event(
            events,
            recording_start_s=recording_start_s,
            kind="configuration",
            message="PX4 precision-landing parameters applied",
            summary=f"count={len(applied)}",
        )
    await configure_telemetry_rates(drone)

    stream_tasks = [
        asyncio.create_task(
            monitor_stream(
                drone.telemetry.position_velocity_ned(),
                lambda item: setattr(telemetry_state, "position_velocity_ned", item),
            )
        ),
        asyncio.create_task(
            monitor_stream(
                drone.telemetry.attitude_euler(),
                lambda item: setattr(telemetry_state, "attitude_euler", item),
            )
        ),
        asyncio.create_task(
            monitor_stream(
                drone.telemetry.in_air(),
                lambda item: setattr(telemetry_state, "in_air", bool(item)),
            )
        ),
        asyncio.create_task(
            monitor_stream(
                drone.telemetry.landed_state(),
                lambda item: setattr(
                    telemetry_state,
                    "landed_state",
                    str(item).split(".")[-1].lower(),
                ),
            )
        ),
        asyncio.create_task(
            monitor_stream(
                drone.telemetry.flight_mode(),
                lambda item: (
                    setattr(
                        telemetry_state,
                        "flight_mode",
                        str(item).split(".")[-1].lower(),
                    ),
                    flight_modes_seen.add(str(item).split(".")[-1].lower()),
                ),
            )
        ),
    ]

    try:
        await wait_for_health(drone)
        log_stage("PX4 health ready: global and home position are valid")
        record_event(
            events,
            recording_start_s=recording_start_s,
            kind="health",
            message="PX4 health ready",
            summary="Global position and home position are valid",
        )
        await wait_for_pose(telemetry_state)
        recording_start_s = time.monotonic()

        current_pose = await run_takeoff_phase(
            drone,
            telemetry_state,
            dock_target,
            frames,
            events,
            commands,
            recording_start_s=recording_start_s,
        )
        await start_offboard(
            drone,
            current_pose,
            events,
            commands,
            recording_start_s=recording_start_s,
        )
        await run_approach_phase(
            drone,
            telemetry_state,
            dock_target,
            frames,
            events,
            commands,
            recording_start_s=recording_start_s,
        )
        await run_precision_landing_phase(
            drone,
            telemetry_state,
            dock_target,
            controller,
            frames,
            events,
            commands,
            recording_start_s=recording_start_s,
        )
        await finalize_touchdown(
            telemetry_state,
            dock_target,
            frames,
            events,
            recording_start_s=recording_start_s,
        )
    finally:
        with contextlib.suppress(Exception):
            await drone.offboard.stop()
        with contextlib.suppress(Exception):
            await drone.action.disarm()
        with contextlib.suppress(Exception):
            if STATE_FILE.exists():
                STATE_FILE.unlink()
        for task in stream_tasks:
            task.cancel()
        for task in stream_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    if not frames:
        raise RuntimeError("No live telemetry frames were recorded.")

    payload = {
        "schema_version": 2,
        "frames": frames,
        "dock_north_m": round(dock_target.north_m, 6),
        "dock_east_m": round(dock_target.east_m, 6),
        "accuracy_m": round(float(frames[-1]["horizontal_error_m"]), 6),
        "proof": build_demo_proof(
            source=PROOF_SOURCE_LIVE_PX4_SITL,
            live_pixhawk=True,
            vehicle_link=SYSTEM_ADDRESS,
            command_rate_hz=CONTROL_RATE_HZ,
            modes_seen=sorted(flight_modes_seen),
            parameter_count=applied_parameter_count,
        ),
        "events": events,
        "commands": commands,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    sync_embedded_payload(payload)
    log_stage(
        "Recorder complete: "
        f"frames={len(payload['frames'])} accuracy_m={payload['accuracy_m']}"
    )
    print(f"Wrote live landing demo data to: {OUTPUT_JSON_PATH.relative_to(REPO_ROOT).as_posix()}")
    print(f"Frame count: {len(payload['frames'])}")
    print(f"Final accuracy (m): {payload['accuracy_m']}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
