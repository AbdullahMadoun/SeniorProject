from __future__ import annotations

import asyncio
import contextlib
import json
import math
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_stream import (
    LandingTargetPublisher,
    LandingTargetSample,
    connection_string_for_endpoint,
)

try:
    from mavsdk import System  # type: ignore
    from mavsdk.action import ActionError  # type: ignore
    from mavsdk.offboard import OffboardError, PositionNedYaw  # type: ignore
except ImportError:  # pragma: no cover
    System = None  # type: ignore[assignment]
    ActionError = RuntimeError  # type: ignore[assignment]
    OffboardError = RuntimeError  # type: ignore[assignment]
    PositionNedYaw = None  # type: ignore[assignment]


SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
TELEMETRY_RATE_HZ = 10.0
TAKEOFF_ALTITUDE_M = 20.0
FLY_AWAY_NORTH_M = 50.0
FLY_AWAY_TOLERANCE_M = 3.0
RTL_DESCENT_INJECTION_ALTITUDE_M = 10.5
RTL_HOME_WINDOW_M = 5.0
TARGET_OFFSET_NORTH_M = 0.0
TARGET_OFFSET_EAST_M = 3.0
TARGET_OFFSET_DOWN_M = 0.0
PROOF_TIMEOUT_S = 420.0
OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "rtl_precision_landing_proof.txt"
SUMMARY_PATH = REPO_ROOT / "artifacts" / "live_px4" / "rtl_precision_landing_summary.json"
PX4_PRECISION_LANDING_SETTINGS = (
    ("RTL_PLD_MD", "int", 2),
    ("LTEST_MODE", "int", 1),
    ("PLD_HACC_RAD", "float", 0.4),
    ("PLD_BTOUT", "float", 2.0),
    ("PLD_FAPPR_ALT", "float", 1.2),
    ("PLD_MAX_SRCH", "int", 3),
    ("RTL_RETURN_ALT", "float", TAKEOFF_ALTITUDE_M),
    ("RTL_DESCEND_ALT", "float", 10.0),
    ("RTL_LAND_DELAY", "float", 0.0),
    ("MPC_LAND_SPEED", "float", 0.4),
    ("MPC_LAND_ALT1", "float", 5.0),
    ("MPC_LAND_ALT2", "float", 1.0),
    ("EKF2_AID_MASK", "int", 321),
)


@dataclass
class LiveTelemetryState:
    position_velocity_ned: object | None = None
    in_air: bool = False
    flight_mode: str | None = None
    landed_state: str | None = None


@dataclass(frozen=True)
class TelemetrySample:
    t_s: float
    north_m: float
    east_m: float
    altitude_m: float
    north_velocity_mps: float
    east_velocity_mps: float
    down_velocity_mps: float
    home_distance_m: float


class ProofLogger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", encoding="utf-8")

    def log(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def current_time_s(recording_start_s: float) -> float:
    return max(0.0, time.monotonic() - recording_start_s)


async def monitor_stream(stream, setter) -> None:
    async for item in stream:
        setter(item)


async def wait_for_connection(drone: System, *, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    async for state in drone.core.connection_state():
        if state.is_connected:
            return
        if time.monotonic() >= deadline:
            break
    raise RuntimeError(f"Timed out connecting to PX4 at {SYSTEM_ADDRESS}")


async def wait_for_health(drone: System, logger: ProofLogger, *, timeout_s: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_status = ""
    async for health in drone.telemetry.health():
        global_ok = bool(getattr(health, "is_global_position_ok", False))
        home_ok = bool(getattr(health, "is_home_position_ok", False))
        status = f"global_ok={global_ok} home_ok={home_ok}"
        if status != last_status:
            logger.log(f"health_update {status}")
            last_status = status
        if global_ok and home_ok:
            return
        if time.monotonic() >= deadline:
            break
    raise RuntimeError("Timed out waiting for PX4 global/home position health")


async def configure_telemetry_rates(drone: System) -> None:
    telemetry = drone.telemetry
    calls = (
        ("set_rate_position_velocity_ned", TELEMETRY_RATE_HZ),
        ("set_rate_in_air", 2.0),
        ("set_rate_landed_state", 2.0),
        ("set_rate_flight_mode", 2.0),
    )
    for method_name, rate_hz in calls:
        method = getattr(telemetry, method_name, None)
        if method is None:
            continue
        with contextlib.suppress(Exception):
            await method(rate_hz)


def extract_pose(state: LiveTelemetryState) -> TelemetrySample | None:
    item = state.position_velocity_ned
    if item is None:
        return None
    north_m = float(item.position.north_m)
    east_m = float(item.position.east_m)
    altitude_m = max(0.0, -float(item.position.down_m))
    north_velocity_mps = float(item.velocity.north_m_s)
    east_velocity_mps = float(item.velocity.east_m_s)
    down_velocity_mps = float(item.velocity.down_m_s)
    home_distance_m = math.hypot(north_m, east_m)
    return TelemetrySample(
        t_s=0.0,
        north_m=north_m,
        east_m=east_m,
        altitude_m=altitude_m,
        north_velocity_mps=north_velocity_mps,
        east_velocity_mps=east_velocity_mps,
        down_velocity_mps=down_velocity_mps,
        home_distance_m=home_distance_m,
    )


async def wait_for_sample(
    state: LiveTelemetryState,
    recording_start_s: float,
    *,
    timeout_s: float = 10.0,
) -> TelemetrySample:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sample = extract_pose(state)
        if sample is not None:
            return TelemetrySample(
                t_s=current_time_s(recording_start_s),
                north_m=sample.north_m,
                east_m=sample.east_m,
                altitude_m=sample.altitude_m,
                north_velocity_mps=sample.north_velocity_mps,
                east_velocity_mps=sample.east_velocity_mps,
                down_velocity_mps=sample.down_velocity_mps,
                home_distance_m=sample.home_distance_m,
            )
        await asyncio.sleep(0.1)
    raise RuntimeError("Timed out waiting for live position_velocity_ned telemetry")


async def apply_precision_landing_profile(drone: System, logger: ProofLogger) -> None:
    applied: list[str] = []
    for name, param_type, value in PX4_PRECISION_LANDING_SETTINGS:
        if param_type == "int":
            await drone.param.set_param_int(name, int(value))
            readback = int(await drone.param.get_param_int(name))
        else:
            await drone.param.set_param_float(name, float(value))
            readback = float(await drone.param.get_param_float(name))
        applied.append(f"{name}={readback}")
    logger.log(f"precision_landing_profile_applied count={len(applied)} values={' '.join(applied[:8])}")


async def arm_with_retries(drone: System, logger: ProofLogger, *, retries: int = 20) -> None:
    for attempt in range(1, retries + 1):
        try:
            await drone.action.arm()
            logger.log(f"arm_success attempt={attempt}")
            return
        except ActionError as exc:
            logger.log(f"arm_retry attempt={attempt} error={exc}")
            await asyncio.sleep(3.0)
    raise RuntimeError("Unable to arm PX4 after repeated attempts")


async def wait_for_altitude(
    state: LiveTelemetryState,
    recording_start_s: float,
    target_altitude_m: float,
    *,
    tolerance_m: float,
    timeout_s: float,
) -> TelemetrySample:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sample = await wait_for_sample(state, recording_start_s, timeout_s=3.0)
        if sample.altitude_m >= target_altitude_m - tolerance_m:
            return sample
        await asyncio.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for altitude {target_altitude_m:.1f} m")


async def wait_for_north_target(
    drone: System,
    state: LiveTelemetryState,
    logger: ProofLogger,
    recording_start_s: float,
    target_north_m: float,
    target_east_m: float,
    *,
    tolerance_m: float,
    timeout_s: float,
) -> TelemetrySample:
    if PositionNedYaw is None:
        raise RuntimeError("mavsdk offboard plugin is unavailable")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sample = await wait_for_sample(state, recording_start_s, timeout_s=3.0)
        await drone.offboard.set_position_ned(
            PositionNedYaw(target_north_m, target_east_m, -TAKEOFF_ALTITUDE_M, 0.0)
        )
        north_error_m = abs(sample.north_m - target_north_m)
        east_error_m = abs(sample.east_m - target_east_m)
        altitude_error_m = abs(sample.altitude_m - TAKEOFF_ALTITUDE_M)
        if north_error_m <= tolerance_m and east_error_m <= tolerance_m and altitude_error_m <= 1.5:
            logger.log(
                "flyaway_target_reached "
                f"north_m={sample.north_m:.2f} east_m={sample.east_m:.2f} "
                f"north_error_m={north_error_m:.2f} east_error_m={east_error_m:.2f} "
                f"altitude_error_m={altitude_error_m:.2f}"
            )
            return sample
        await asyncio.sleep(0.2)
    raise RuntimeError("Timed out waiting for fly-away target")


async def telemetry_printer(
    state: LiveTelemetryState,
    logger: ProofLogger,
    recording_start_s: float,
    recent_samples: deque[TelemetrySample],
    *,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        sample = extract_pose(state)
        if sample is not None:
            timed = TelemetrySample(
                t_s=current_time_s(recording_start_s),
                north_m=sample.north_m,
                east_m=sample.east_m,
                altitude_m=sample.altitude_m,
                north_velocity_mps=sample.north_velocity_mps,
                east_velocity_mps=sample.east_velocity_mps,
                down_velocity_mps=sample.down_velocity_mps,
                home_distance_m=sample.home_distance_m,
            )
            recent_samples.append(timed)
            xy_speed_mps = math.hypot(timed.north_velocity_mps, timed.east_velocity_mps)
            logger.log(
                "telemetry "
                f"t_s={timed.t_s:.1f} mode={state.flight_mode or 'unknown'} "
                f"altitude_m={timed.altitude_m:.2f} "
                f"vz_down_mps={timed.down_velocity_mps:.2f} "
                f"vx_north_mps={timed.north_velocity_mps:.2f} "
                f"vy_east_mps={timed.east_velocity_mps:.2f} "
                f"xy_speed_mps={xy_speed_mps:.2f} "
                f"home_distance_m={timed.home_distance_m:.2f}"
            )
        await asyncio.sleep(0.5)


async def execute_proof() -> int:
    if System is None or PositionNedYaw is None:
        raise RuntimeError("mavsdk is not installed in the active Python environment")

    logger = ProofLogger(OUTPUT_PATH)
    stop_event = asyncio.Event()
    recent_samples: deque[TelemetrySample] = deque(maxlen=80)
    state = LiveTelemetryState()
    publisher: LandingTargetPublisher | None = None
    recording_start_s = time.monotonic()
    injection_started = False
    response_detected = False
    injection_count = 0
    injection_start_east_m = 0.0
    pre_injection_east_velocity_mps = 0.0
    peak_post_injection_east_velocity_mps = 0.0
    max_east_shift_m = 0.0

    telemetry_tasks: list[asyncio.Task] = []
    telemetry_printer_task: asyncio.Task | None = None
    drone = System()

    try:
        logger.log(f"connect_start system_address={SYSTEM_ADDRESS}")
        await drone.connect(system_address=SYSTEM_ADDRESS)
        await wait_for_connection(drone)
        logger.log("connect_success")

        telemetry_tasks = [
            asyncio.create_task(
                monitor_stream(
                    drone.telemetry.position_velocity_ned(),
                    lambda item: setattr(state, "position_velocity_ned", item),
                )
            ),
            asyncio.create_task(
                monitor_stream(
                    drone.telemetry.in_air(),
                    lambda item: setattr(state, "in_air", bool(item)),
                )
            ),
            asyncio.create_task(
                monitor_stream(
                    drone.telemetry.flight_mode(),
                    lambda item: setattr(state, "flight_mode", str(item).split(".")[-1].lower()),
                )
            ),
            asyncio.create_task(
                monitor_stream(
                    drone.telemetry.landed_state(),
                    lambda item: setattr(state, "landed_state", str(item).split(".")[-1].lower()),
                )
            ),
        ]
        await configure_telemetry_rates(drone)
        await wait_for_health(drone, logger)
        await wait_for_sample(state, recording_start_s)
        telemetry_printer_task = asyncio.create_task(
            telemetry_printer(
                state,
                logger,
                recording_start_s,
                recent_samples,
                stop_event=stop_event,
            )
        )

        await apply_precision_landing_profile(drone, logger)
        await arm_with_retries(drone, logger)
        await drone.action.set_takeoff_altitude(TAKEOFF_ALTITUDE_M)
        logger.log(f"takeoff_command initial_altitude_request_m={TAKEOFF_ALTITUDE_M}")
        await drone.action.takeoff()
        sample = await wait_for_altitude(
            state,
            recording_start_s,
            1.8,
            tolerance_m=0.4,
            timeout_s=45.0,
        )
        logger.log(
            f"takeoff_transition_complete altitude_m={sample.altitude_m:.2f} "
            f"north_m={sample.north_m:.2f} east_m={sample.east_m:.2f}"
        )

        target_north_m = sample.north_m + FLY_AWAY_NORTH_M
        target_east_m = sample.east_m
        logger.log(
            f"flyaway_start target_north_m={target_north_m:.2f} "
            f"target_east_m={target_east_m:.2f} target_altitude_m={TAKEOFF_ALTITUDE_M:.2f}"
        )
        await drone.offboard.set_position_ned(
            PositionNedYaw(sample.north_m, sample.east_m, -TAKEOFF_ALTITUDE_M, 0.0)
        )
        await drone.offboard.start()
        await wait_for_north_target(
            drone,
            state,
            logger,
            recording_start_s,
            target_north_m,
            target_east_m,
            tolerance_m=FLY_AWAY_TOLERANCE_M,
            timeout_s=120.0,
        )
        with contextlib.suppress(OffboardError, RuntimeError):
            await drone.offboard.stop()

        logger.log("rtl_command")
        await drone.action.return_to_launch()

        target_north = TARGET_OFFSET_NORTH_M
        target_east = TARGET_OFFSET_EAST_M
        target_connection_string = connection_string_for_endpoint(
            "offboard",
            bridge_ip=None,
            direct_px4=True,
        )
        logger.log(
            "landing_target_endpoint "
            f"connection_string={target_connection_string} "
            f"target_north_m={target_north:.2f} target_east_m={target_east:.2f}"
        )

        deadline = time.monotonic() + PROOF_TIMEOUT_S
        while time.monotonic() < deadline:
            sample = await wait_for_sample(state, recording_start_s, timeout_s=3.0)
            descending = sample.down_velocity_mps > 0.15
            near_home = sample.home_distance_m <= RTL_HOME_WINDOW_M
            if (
                not injection_started
                and descending
                and near_home
                and sample.altitude_m <= RTL_DESCENT_INJECTION_ALTITUDE_M
            ):
                publisher = LandingTargetPublisher(target_connection_string)
                injection_started = True
                injection_start_east_m = sample.east_m
                baseline_window = [
                    item.east_velocity_mps
                    for item in recent_samples
                    if item.altitude_m >= sample.altitude_m
                ]
                pre_injection_east_velocity_mps = (
                    statistics.fmean(baseline_window[-10:]) if baseline_window else 0.0
                )
                logger.log(
                    "landing_target_injection_started "
                    f"altitude_m={sample.altitude_m:.2f} "
                    f"home_distance_m={sample.home_distance_m:.2f} "
                    f"pre_injection_east_velocity_mps={pre_injection_east_velocity_mps:.2f}"
                )

            if injection_started and publisher is not None:
                publisher.send_sample(
                    LandingTargetSample(
                        time_usec=int(time.time() * 1_000_000),
                        x_m=target_north,
                        y_m=target_east,
                        z_m=TARGET_OFFSET_DOWN_M,
                    )
                )
                injection_count += 1
                peak_post_injection_east_velocity_mps = max(
                    peak_post_injection_east_velocity_mps,
                    sample.east_velocity_mps,
                )
                max_east_shift_m = max(max_east_shift_m, sample.east_m - injection_start_east_m)
                if not response_detected:
                    recent_east = [item.east_velocity_mps for item in list(recent_samples)[-8:]]
                    avg_recent_east_mps = statistics.fmean(recent_east) if recent_east else 0.0
                    if avg_recent_east_mps > pre_injection_east_velocity_mps + 0.15 and max_east_shift_m > 0.5:
                        response_detected = True
                        logger.log(
                            "precision_landing_response_detected "
                            f"avg_recent_east_velocity_mps={avg_recent_east_mps:.2f} "
                            f"peak_post_injection_east_velocity_mps={peak_post_injection_east_velocity_mps:.2f} "
                            f"east_shift_m={max_east_shift_m:.2f}"
                        )

            if injection_started and not state.in_air and sample.altitude_m <= 0.2:
                logger.log(
                    "touchdown_detected "
                    f"east_m={sample.east_m:.2f} north_m={sample.north_m:.2f} "
                    f"east_shift_m={sample.east_m - injection_start_east_m:.2f}"
                )
                break

            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Proof sequence timed out before touchdown")

        final_sample = await wait_for_sample(state, recording_start_s, timeout_s=3.0)
        summary = {
            "injection_started": injection_started,
            "response_detected": response_detected,
            "injection_count": injection_count,
            "pre_injection_east_velocity_mps": round(pre_injection_east_velocity_mps, 4),
            "peak_post_injection_east_velocity_mps": round(peak_post_injection_east_velocity_mps, 4),
            "max_east_shift_m": round(max_east_shift_m, 4),
            "final_north_m": round(final_sample.north_m, 4),
            "final_east_m": round(final_sample.east_m, 4),
            "final_altitude_m": round(final_sample.altitude_m, 4),
            "target_offset_east_m": TARGET_OFFSET_EAST_M,
            "target_offset_north_m": TARGET_OFFSET_NORTH_M,
        }
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        logger.log(f"summary {summary}")
        if not injection_started:
            logger.log("proof_failed reason=landing_target_injection_never_started")
            return 1
        if not response_detected:
            logger.log("proof_failed reason=vehicle_velocity_did_not_shift_toward_target")
            return 1
        logger.log("proof_success live_px4_rtl_precision_landing_verified=true")
        return 0
    finally:
        stop_event.set()
        if telemetry_printer_task is not None:
            telemetry_printer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await telemetry_printer_task
        for task in telemetry_tasks:
            task.cancel()
        for task in telemetry_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        with contextlib.suppress(Exception):
            await drone.offboard.stop()
        with contextlib.suppress(Exception):
            await drone.action.disarm()
        logger.close()


def main() -> None:
    raise SystemExit(asyncio.run(execute_proof()))


if __name__ == "__main__":
    main()
