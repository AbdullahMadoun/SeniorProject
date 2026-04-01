from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_projection import (
    DockTarget,
    VehicleLocalPose,
    build_projected_landing_target_frame,
    build_projected_approach_landing_target_samples,
    local_ned_offset_to_body,
    sample_from_projected_frame,
    project_relative_target_to_local_ned,
)
from autonomy.drone_system.precision_landing import RelativeLandingTarget


class LandingTargetProjectionTests(unittest.TestCase):
    def test_local_ned_offset_to_body_and_back_round_trip(self) -> None:
        vehicle_pose = VehicleLocalPose(north_m=0.0, east_m=0.0, down_m=-5.0, yaw_deg=34.3774677)
        relative_target = RelativeLandingTarget(
            forward_error_m=1.4,
            right_error_m=-0.8,
            down_error_m=5.0,
            horizontal_error_m=(1.4**2 + (-0.8) ** 2) ** 0.5,
        )

        target_north_m, target_east_m, target_down_m = project_relative_target_to_local_ned(
            relative_target,
            vehicle_pose,
        )
        forward_m, right_m, down_m = local_ned_offset_to_body(
            north_m=target_north_m - vehicle_pose.north_m,
            east_m=target_east_m - vehicle_pose.east_m,
            down_m=target_down_m - vehicle_pose.down_m,
            yaw_rad=0.6,
        )

        self.assertAlmostEqual(forward_m, relative_target.forward_error_m, places=6)
        self.assertAlmostEqual(right_m, relative_target.right_error_m, places=6)
        self.assertAlmostEqual(down_m, relative_target.down_error_m, places=6)

    def test_projected_frame_and_sample_match_requested_dock_target(self) -> None:
        vehicle_pose = VehicleLocalPose(north_m=3.05, east_m=-1.85, down_m=-8.0, yaw_deg=0.0)
        dock_target = DockTarget(north_m=1.25, east_m=-0.75, down_m=0.0)

        frame = build_projected_landing_target_frame(vehicle_pose, dock_target)
        sample = sample_from_projected_frame(frame, time_usec=123)

        self.assertAlmostEqual(frame.target_north_m, 1.25, places=3)
        self.assertAlmostEqual(frame.target_east_m, -0.75, places=3)
        self.assertAlmostEqual(frame.target_down_m, 0.0, places=3)
        self.assertEqual(sample.time_usec, 123)
        self.assertAlmostEqual(sample.x_m, 1.25, places=3)
        self.assertAlmostEqual(sample.y_m, -0.75, places=3)
        self.assertAlmostEqual(sample.z_m, 0.0, places=3)

    def test_projected_approach_samples_hold_constant_dock_target(self) -> None:
        samples, frames = build_projected_approach_landing_target_samples(duration_s=5.0, rate_hz=10.0)

        self.assertEqual(len(samples), 50)
        self.assertEqual(len(frames), 50)
        self.assertAlmostEqual(samples[0].x_m, 1.25, places=3)
        self.assertAlmostEqual(samples[0].y_m, -0.75, places=3)
        self.assertAlmostEqual(samples[-1].x_m, 1.25, places=3)
        self.assertAlmostEqual(samples[-1].y_m, -0.75, places=3)
        self.assertAlmostEqual(samples[-1].z_m, 0.0, places=3)
