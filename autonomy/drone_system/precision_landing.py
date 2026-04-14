from __future__ import annotations

import json
import math

import numpy as np
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from .config import SystemBaseline


HORIZONTAL_ERROR_EPSILON = 1e-6
MAX_VELOCITY_RATIO = 10.0
MAX_CAMERA_ANGLE_RAD = math.radians(60.0)
MIN_ANGLE_RAD = math.radians(0.1)
MAX_RANGE_M = 100.0
MIN_RANGE_M = 0.01


def clamp_angle(angle_rad: float) -> float:
    if abs(angle_rad) > MAX_CAMERA_ANGLE_RAD:
        return math.copysign(MAX_CAMERA_ANGLE_RAD, angle_rad)
    return angle_rad


def validate_observation(observation: LandingTargetObservation) -> LandingTargetObservation:
    if not math.isfinite(observation.forward_angle_rad):
        raise ValueError(f"forward_angle_rad is not finite: {observation.forward_angle_rad}")
    if not math.isfinite(observation.right_angle_rad):
        raise ValueError(f"right_angle_rad is not finite: {observation.right_angle_rad}")
    if not math.isfinite(observation.range_m):
        raise ValueError(f"range_m is not finite: {observation.range_m}")
    if observation.range_m <= MIN_RANGE_M:
        raise ValueError(f"range_m must be > {MIN_RANGE_M}, got: {observation.range_m}")
    if observation.range_m > MAX_RANGE_M:
        raise ValueError(f"range_m exceeds maximum sensor range: {observation.range_m}")
    if not (0.0 <= observation.quality <= 1.0):
        raise ValueError(f"quality must be in [0, 1], got: {observation.quality}")
    return observation


class PrecisionLandingPhase(str, Enum):
    SEARCH = "search"
    ALIGN = "align"
    DESCEND = "descend"
    FLARE = "flare"
    TOUCHDOWN = "touchdown"
    ABORT = "abort"


@dataclass(frozen=True)
class LandingTargetObservation:
    acquired: bool
    quality: float
    forward_angle_rad: float
    right_angle_rad: float
    range_m: float


@dataclass(frozen=True)
class RelativeLandingTarget:
    forward_error_m: float
    right_error_m: float
    down_error_m: float
    horizontal_error_m: float


@dataclass(frozen=True)
class PrecisionLandingCommand:
    phase: PrecisionLandingPhase
    forward_velocity_mps: float
    right_velocity_mps: float
    descent_rate_mps: float
    reason: str


@dataclass(frozen=True)
class PrecisionLandingControllerState:
    phase: PrecisionLandingPhase
    target: RelativeLandingTarget | None
    command: PrecisionLandingCommand
    target_locked: bool
    time_since_last_lock_s: float | None


@dataclass(frozen=True)
class PrecisionLandingScenarioStep:
    t_s: float
    phase: str
    altitude_m: float
    forward_error_m: float
    right_error_m: float
    horizontal_error_m: float
    target_acquired: bool
    command_forward_velocity_mps: float
    command_right_velocity_mps: float
    command_descent_rate_mps: float


@dataclass(frozen=True)
class PrecisionLandingScenarioResult:
    name: str
    passed: bool
    final_phase: str
    touchdown_error_m: float | None
    total_time_s: float
    details: tuple[str, ...]


@dataclass(frozen=True)
class PrecisionLandingTuning:
    max_horizontal_speed_mps: float = 1.0
    align_gain: float = 0.8
    descent_rate_mps: float = 0.6
    flare_descent_rate_mps: float = 0.25
    flare_altitude_m: float = 1.2
    touchdown_altitude_m: float = 0.15
    min_observation_quality: float = 0.6
    reacquire_timeout_s: float = 2.0


def estimate_relative_target(observation: LandingTargetObservation) -> RelativeLandingTarget:
    forward_angle = clamp_angle(observation.forward_angle_rad)
    right_angle = clamp_angle(observation.right_angle_rad)
    if abs(forward_angle) < MIN_ANGLE_RAD:
        forward_angle = 0.0
    if abs(right_angle) < MIN_ANGLE_RAD:
        right_angle = 0.0
    forward_error_m = math.tan(forward_angle) * observation.range_m
    right_error_m = math.tan(right_angle) * observation.range_m
    forward_error_m = max(-observation.range_m, min(observation.range_m, forward_error_m))
    right_error_m = max(-observation.range_m, min(observation.range_m, right_error_m))
    horizontal_error_m = math.hypot(forward_error_m, right_error_m)
    return RelativeLandingTarget(
        forward_error_m=forward_error_m,
        right_error_m=right_error_m,
        down_error_m=observation.range_m,
        horizontal_error_m=horizontal_error_m,
    )


class PrecisionLandingController:
    def __init__(
        self,
        baseline: SystemBaseline,
        tuning: PrecisionLandingTuning | None = None,
        use_pid: bool = False,
    ) -> None:
        self._baseline = baseline
        self._tuning = tuning or PrecisionLandingTuning()
        self._last_lock_time_s: float | None = None
        
        self._use_pid = use_pid
        if self._use_pid:
            from .pid_controller import PIDController
            self._pid_forward = PIDController(p=self._tuning.align_gain, i=0.01, d=0.05)
            self._pid_right = PIDController(p=self._tuning.align_gain, i=0.01, d=0.05)
            self._pid_forward.set_windup(min(self._tuning.max_horizontal_speed_mps, 2.0))
            self._pid_right.set_windup(min(self._tuning.max_horizontal_speed_mps, 2.0))

    def reset(self) -> None:
        self._last_lock_time_s = None

    def step(
        self,
        observation: LandingTargetObservation,
        *,
        time_s: float,
    ) -> PrecisionLandingControllerState:
        if observation.acquired and observation.quality >= self._tuning.min_observation_quality:
            self._last_lock_time_s = time_s
            observation = validate_observation(observation)
            target = estimate_relative_target(observation)
            if self._use_pid:
                self._pid_forward.setpoint = 0.0
                self._pid_right.setpoint = 0.0
                
                # We feed the error directly into the PID and retrieve the velocity output
                self._pid_forward.update(target.forward_error_m, current_time=time_s)
                self._pid_right.update(target.right_error_m, current_time=time_s)
                
                # The output needs to push the drone towards the target, so we negate if error is positive
                forward_velocity = np.clip(
                    -self._pid_forward.output, 
                    -self._tuning.max_horizontal_speed_mps, 
                    self._tuning.max_horizontal_speed_mps
                )
                right_velocity = np.clip(
                    -self._pid_right.output, 
                    -self._tuning.max_horizontal_speed_mps, 
                    self._tuning.max_horizontal_speed_mps
                )
            else:
                horizontal_velocity_scale = min(
                    target.horizontal_error_m * self._tuning.align_gain,
                    self._tuning.max_horizontal_speed_mps,
                )
                if target.horizontal_error_m > HORIZONTAL_ERROR_EPSILON:
                    ratio = np.clip(
                        target.forward_error_m / target.horizontal_error_m,
                        -MAX_VELOCITY_RATIO,
                        MAX_VELOCITY_RATIO,
                    )
                    forward_velocity = -horizontal_velocity_scale * ratio
                    ratio = np.clip(
                        target.right_error_m / target.horizontal_error_m,
                        -MAX_VELOCITY_RATIO,
                        MAX_VELOCITY_RATIO,
                    )
                    right_velocity = -horizontal_velocity_scale * ratio
                elif target.horizontal_error_m > 0.0:
                    forward_velocity = 0.0
                    right_velocity = 0.0
                else:
                    forward_velocity = 0.0
                    right_velocity = 0.0

            if target.horizontal_error_m > self._baseline.docking.landing_accuracy_target_m:
                command = PrecisionLandingCommand(
                    phase=PrecisionLandingPhase.ALIGN,
                    forward_velocity_mps=forward_velocity,
                    right_velocity_mps=right_velocity,
                    descent_rate_mps=0.0,
                    reason="horizontal_error_above_target",
                )
            elif target.down_error_m > self._tuning.flare_altitude_m:
                command = PrecisionLandingCommand(
                    phase=PrecisionLandingPhase.DESCEND,
                    forward_velocity_mps=forward_velocity,
                    right_velocity_mps=right_velocity,
                    descent_rate_mps=self._tuning.descent_rate_mps,
                    reason="target_locked_descend",
                )
            elif target.down_error_m > self._tuning.touchdown_altitude_m:
                command = PrecisionLandingCommand(
                    phase=PrecisionLandingPhase.FLARE,
                    forward_velocity_mps=forward_velocity * 0.5,
                    right_velocity_mps=right_velocity * 0.5,
                    descent_rate_mps=self._tuning.flare_descent_rate_mps,
                    reason="flare_descent",
                )
            else:
                command = PrecisionLandingCommand(
                    phase=PrecisionLandingPhase.TOUCHDOWN,
                    forward_velocity_mps=0.0,
                    right_velocity_mps=0.0,
                    descent_rate_mps=0.0,
                    reason="touchdown_window_reached",
                )
            return PrecisionLandingControllerState(
                phase=command.phase,
                target=target,
                command=command,
                target_locked=True,
                time_since_last_lock_s=0.0,
            )

        time_since_last_lock_s = None
        if self._last_lock_time_s is not None:
            time_since_last_lock_s = max(0.0, time_s - self._last_lock_time_s)

        if time_since_last_lock_s is None or time_since_last_lock_s <= self._tuning.reacquire_timeout_s:
            command = PrecisionLandingCommand(
                phase=PrecisionLandingPhase.SEARCH,
                forward_velocity_mps=0.0,
                right_velocity_mps=0.0,
                descent_rate_mps=0.0,
                reason="target_not_visible_reacquire",
            )
            phase = PrecisionLandingPhase.SEARCH
        else:
            command = PrecisionLandingCommand(
                phase=PrecisionLandingPhase.ABORT,
                forward_velocity_mps=0.0,
                right_velocity_mps=0.0,
                descent_rate_mps=0.0,
                reason="target_lost_timeout",
            )
            phase = PrecisionLandingPhase.ABORT

        return PrecisionLandingControllerState(
            phase=phase,
            target=None,
            command=command,
            target_locked=False,
            time_since_last_lock_s=time_since_last_lock_s,
        )


class PrecisionLandingSimulator:
    def __init__(
        self,
        baseline: SystemBaseline,
        tuning: PrecisionLandingTuning | None = None,
        dt_s: float = 0.5,
    ) -> None:
        self._baseline = baseline
        self._tuning = tuning or PrecisionLandingTuning()
        self._controller = PrecisionLandingController(baseline, self._tuning)
        self._dt_s = dt_s

    def run_scenario(
        self,
        *,
        name: str,
        initial_forward_error_m: float,
        initial_right_error_m: float,
        initial_altitude_m: float,
        max_time_s: float = 60.0,
        target_loss_windows: tuple[tuple[float, float], ...] = (),
    ) -> tuple[PrecisionLandingScenarioResult, list[PrecisionLandingScenarioStep]]:
        forward_error_m = initial_forward_error_m
        right_error_m = initial_right_error_m
        altitude_m = initial_altitude_m
        steps: list[PrecisionLandingScenarioStep] = []

        self._controller.reset()
        t_s = 0.0
        while t_s <= max_time_s:
            target_acquired = not any(start <= t_s <= end for start, end in target_loss_windows)
            horizontal_error_m = math.hypot(forward_error_m, right_error_m)
            observation = LandingTargetObservation(
                acquired=target_acquired,
                quality=0.95 if target_acquired else 0.0,
                forward_angle_rad=math.atan2(forward_error_m, max(altitude_m, 0.01)) if target_acquired else 0.0,
                right_angle_rad=math.atan2(right_error_m, max(altitude_m, 0.01)) if target_acquired else 0.0,
                range_m=max(altitude_m, 0.01),
            )
            state = self._controller.step(observation, time_s=t_s)

            steps.append(
                PrecisionLandingScenarioStep(
                    t_s=t_s,
                    phase=state.phase.value,
                    altitude_m=altitude_m,
                    forward_error_m=forward_error_m,
                    right_error_m=right_error_m,
                    horizontal_error_m=horizontal_error_m,
                    target_acquired=target_acquired,
                    command_forward_velocity_mps=state.command.forward_velocity_mps,
                    command_right_velocity_mps=state.command.right_velocity_mps,
                    command_descent_rate_mps=state.command.descent_rate_mps,
                )
            )

            if state.phase == PrecisionLandingPhase.ABORT:
                return (
                    PrecisionLandingScenarioResult(
                        name=name,
                        passed=False,
                        final_phase=state.phase.value,
                        touchdown_error_m=None,
                        total_time_s=t_s,
                        details=("target_lost_timeout",),
                    ),
                    steps,
                )

            if state.phase == PrecisionLandingPhase.TOUCHDOWN:
                touchdown_error_m = math.hypot(forward_error_m, right_error_m)
                passed = touchdown_error_m <= self._baseline.docking.landing_accuracy_target_m
                details = (
                    "touchdown_within_target",
                ) if passed else (
                    "touchdown_outside_target",
                )
                return (
                    PrecisionLandingScenarioResult(
                        name=name,
                        passed=passed,
                        final_phase=state.phase.value,
                        touchdown_error_m=touchdown_error_m,
                        total_time_s=t_s,
                        details=details,
                    ),
                    steps,
                )

            forward_error_m += state.command.forward_velocity_mps * self._dt_s
            right_error_m += state.command.right_velocity_mps * self._dt_s
            altitude_m = max(0.0, altitude_m - (state.command.descent_rate_mps * self._dt_s))
            t_s += self._dt_s

        return (
            PrecisionLandingScenarioResult(
                name=name,
                passed=False,
                final_phase=PrecisionLandingPhase.ABORT.value,
                touchdown_error_m=None,
                total_time_s=max_time_s,
                details=("max_time_exceeded",),
            ),
            steps,
        )

    def run_default_scenarios(self) -> tuple[list[PrecisionLandingScenarioResult], dict[str, list[PrecisionLandingScenarioStep]]]:
        results: list[PrecisionLandingScenarioResult] = []
        step_map: dict[str, list[PrecisionLandingScenarioStep]] = {}
        definitions = (
            {
                "name": "nominal_precision_touchdown",
                "initial_forward_error_m": 1.8,
                "initial_right_error_m": -1.1,
                "initial_altitude_m": 8.0,
                "target_loss_windows": (),
            },
            {
                "name": "short_target_loss_reacquire",
                "initial_forward_error_m": 1.2,
                "initial_right_error_m": 0.9,
                "initial_altitude_m": 6.0,
                "target_loss_windows": ((4.0, 5.0),),
            },
            {
                "name": "sustained_target_loss_abort",
                "initial_forward_error_m": 1.0,
                "initial_right_error_m": -0.8,
                "initial_altitude_m": 5.0,
                "target_loss_windows": ((1.0, 5.0),),
            },
        )
        for definition in definitions:
            result, steps = self.run_scenario(**definition)
            results.append(result)
            step_map[result.name] = steps
        return results, step_map


def write_precision_landing_artifacts(
    output_dir: str | Path,
    results: list[PrecisionLandingScenarioResult],
    step_map: dict[str, list[PrecisionLandingScenarioStep]],
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    manifest_path = destination / "manifest.json"
    summary_path = destination / "summary.md"

    manifest = {
        "scenario_count": len(results),
        "passed_count": sum(1 for result in results if result.passed),
        "results": [asdict(result) for result in results],
        "steps": {
            name: [asdict(step) for step in steps]
            for name, steps in step_map.items()
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Precision Landing Scenario Summary",
        "",
        f"- scenario count: `{manifest['scenario_count']}`",
        f"- passed count: `{manifest['passed_count']}`",
        "",
        "| Scenario | Passed | Final Phase | Touchdown Error (m) | Details |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        touchdown_error = (
            f"{result.touchdown_error_m:.3f}" if result.touchdown_error_m is not None else "-"
        )
        lines.append(
            f"| {result.name} | {'yes' if result.passed else 'no'} | "
            f"{result.final_phase} | {touchdown_error} | {', '.join(result.details)} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
