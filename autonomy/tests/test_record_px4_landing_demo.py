from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_projection import DockTarget
from autonomy.drone_system.models import VehicleLocalPose
from autonomy.scripts.record_px4_landing_demo import (
    build_visibility_observation,
    controller_body_to_local_velocity,
    local_velocity_to_controller_body,
)


class RecordPx4LandingDemoTests(unittest.TestCase):
    def test_controller_velocity_conversion_matches_exporter_sign_convention(self) -> None:
        north_mps, east_mps = controller_body_to_local_velocity(
            forward_velocity_mps=-0.8,
            right_velocity_mps=0.3,
            yaw_deg=0.0,
        )

        self.assertAlmostEqual(north_mps, 0.8, places=6)
        self.assertAlmostEqual(east_mps, -0.3, places=6)

        forward_mps, right_mps = local_velocity_to_controller_body(
            north_velocity_mps=north_mps,
            east_velocity_mps=east_mps,
            yaw_deg=0.0,
        )
        self.assertAlmostEqual(forward_mps, -0.8, places=6)
        self.assertAlmostEqual(right_mps, 0.3, places=6)

    def test_build_visibility_observation_detects_visible_target(self) -> None:
        vehicle_pose = VehicleLocalPose(
            north_m=1.25,
            east_m=-0.75,
            down_m=-6.0,
            yaw_deg=0.0,
        )
        dock_target = DockTarget(north_m=1.25, east_m=-0.75, down_m=0.0)

        observation, geometry = build_visibility_observation(vehicle_pose, dock_target)

        self.assertTrue(observation.acquired)
        self.assertGreaterEqual(observation.quality, 0.6)
        self.assertAlmostEqual(geometry["horizontal_error_m"], 0.0, places=6)

    def test_build_visibility_observation_rejects_target_outside_camera_cone(self) -> None:
        vehicle_pose = VehicleLocalPose(
            north_m=12.0,
            east_m=10.0,
            down_m=-2.0,
            yaw_deg=0.0,
        )
        dock_target = DockTarget(north_m=1.25, east_m=-0.75, down_m=0.0)

        observation, geometry = build_visibility_observation(vehicle_pose, dock_target)

        self.assertFalse(observation.acquired)
        self.assertEqual(observation.quality, 0.0)
        self.assertGreater(geometry["horizontal_error_m"], 2.0)


if __name__ == "__main__":
    unittest.main()
