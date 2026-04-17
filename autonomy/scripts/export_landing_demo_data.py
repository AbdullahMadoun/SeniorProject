from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.landing_target_projection import (
    DockTarget,
    build_projected_approach_landing_target_samples,
    build_projected_landing_target_frame,
)
from autonomy.drone_system.models import VehicleLocalPose
from autonomy.drone_system.precision_landing import (
    LandingTargetObservation,
    PrecisionLandingController,
    PrecisionLandingPhase,
    PrecisionLandingTuning,
)


OUTPUT_DIR = REPO_ROOT / "artifacts" / "demo"
OUTPUT_JSON_PATH = OUTPUT_DIR / "landing_trajectory.json"
OUTPUT_HTML_PATH = OUTPUT_DIR / "precision_landing_3d_demo.html"
EMBEDDED_DATA_PATTERN = re.compile(
    r"<!-- LANDING_DATA_START -->.*?<!-- LANDING_DATA_END -->",
    re.DOTALL,
)


def build_observation_from_pose(
    vehicle_pose: VehicleLocalPose,
    dock_target: DockTarget,
) -> LandingTargetObservation:
    frame = build_projected_landing_target_frame(vehicle_pose, dock_target)
    return frame.observation


def integrate_vehicle_pose(
    vehicle_pose: VehicleLocalPose,
    *,
    forward_velocity_mps: float,
    right_velocity_mps: float,
    descent_rate_mps: float,
    dt_s: float,
) -> VehicleLocalPose:
    yaw_rad = math.radians(vehicle_pose.yaw_deg)
    north_delta_m = (-forward_velocity_mps * math.cos(yaw_rad)) + (right_velocity_mps * math.sin(yaw_rad))
    east_delta_m = (-forward_velocity_mps * math.sin(yaw_rad)) - (right_velocity_mps * math.cos(yaw_rad))
    altitude_m = max(0.0, -vehicle_pose.down_m - (descent_rate_mps * dt_s))
    return VehicleLocalPose(
        north_m=vehicle_pose.north_m + (north_delta_m * dt_s),
        east_m=vehicle_pose.east_m + (east_delta_m * dt_s),
        down_m=-altitude_m,
        yaw_deg=vehicle_pose.yaw_deg,
        roll_deg=vehicle_pose.roll_deg,
        pitch_deg=vehicle_pose.pitch_deg,
    )


def simulate_landing_trajectory() -> dict[str, object]:
    duration_s = 30.0
    rate_hz = 10.0
    initial_altitude_m = 8.0
    final_altitude_m = 0.15
    initial_north_error_m = 1.8
    initial_east_error_m = -1.1

    _, reference_frames = build_projected_approach_landing_target_samples(
        duration_s=duration_s,
        rate_hz=rate_hz,
        initial_altitude_m=initial_altitude_m,
        final_altitude_m=final_altitude_m,
        initial_north_error_m=initial_north_error_m,
        initial_east_error_m=initial_east_error_m,
    )
    if not reference_frames:
        raise RuntimeError("No reference frames were generated for the landing demo.")

    baseline = load_system_baseline()
    tuning = PrecisionLandingTuning()
    controller = PrecisionLandingController(baseline, tuning)
    controller.reset()

    dock_target = reference_frames[0].dock_target
    current_pose = reference_frames[0].vehicle_pose
    dt_s = 1.0 / rate_hz
    frame_count = len(reference_frames)
    exported_frames: list[dict[str, float | str]] = []

    for index in range(frame_count):
        t_s = round(index * dt_s, 3)
        projected_frame = build_projected_landing_target_frame(current_pose, dock_target)
        observation = build_observation_from_pose(current_pose, dock_target)
        state = controller.step(observation, time_s=t_s)
        target = state.target or projected_frame.relative_target
        altitude_m = -current_pose.down_m

        exported_frames.append(
            {
                "t": t_s,
                "north_m": round(current_pose.north_m, 6),
                "east_m": round(current_pose.east_m, 6),
                "down_m": round(current_pose.down_m, 6),
                "target_north_m": round(projected_frame.target_north_m, 6),
                "target_east_m": round(projected_frame.target_east_m, 6),
                "phase": state.phase.name,
                "horizontal_error_m": round(target.horizontal_error_m, 6),
                "altitude_m": round(altitude_m, 6),
                "forward_vel": round(float(state.command.forward_velocity_mps), 6),
                "right_vel": round(float(state.command.right_velocity_mps), 6),
                "forward_error_m": round(target.forward_error_m, 6),
                "right_error_m": round(target.right_error_m, 6),
            }
        )

        if state.phase not in {PrecisionLandingPhase.TOUCHDOWN, PrecisionLandingPhase.ABORT}:
            current_pose = integrate_vehicle_pose(
                current_pose,
                forward_velocity_mps=float(state.command.forward_velocity_mps),
                right_velocity_mps=float(state.command.right_velocity_mps),
                descent_rate_mps=float(state.command.descent_rate_mps),
                dt_s=dt_s,
            )

    accuracy_m = float(exported_frames[-1]["horizontal_error_m"])
    return {
        "frames": exported_frames,
        "dock_north_m": round(dock_target.north_m, 6),
        "dock_east_m": round(dock_target.east_m, 6),
        "accuracy_m": round(accuracy_m, 6),
    }


def sync_embedded_payload(payload: dict[str, object]) -> None:
    if not OUTPUT_HTML_PATH.exists():
        return

    html = OUTPUT_HTML_PATH.read_text(encoding="utf-8")
    embedded_block = (
        "<!-- LANDING_DATA_START -->\n"
        "<script id=\"landing-data\" type=\"application/json\">"
        f"{json.dumps(payload, separators=(',', ':'))}"
        "</script>\n"
        "<!-- LANDING_DATA_END -->"
    )
    updated_html, replacements = EMBEDDED_DATA_PATTERN.subn(embedded_block, html, count=1)
    if replacements != 1:
        raise ValueError(
            f"Expected one embedded landing-data placeholder block in {OUTPUT_HTML_PATH}, found {replacements}."
        )
    OUTPUT_HTML_PATH.write_text(updated_html, encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = simulate_landing_trajectory()
    OUTPUT_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    sync_embedded_payload(payload)
    relative_json_path = OUTPUT_JSON_PATH.relative_to(REPO_ROOT)
    print(f"Wrote landing demo data to: {relative_json_path.as_posix()}")
    print(f"Frame count: {len(payload['frames'])}")
    print(f"Final accuracy (m): {payload['accuracy_m']}")


if __name__ == "__main__":
    main()
