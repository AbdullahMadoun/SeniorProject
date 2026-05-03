from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.precision_landing import (
    LandingTargetObservation,
    PrecisionLandingController,
    PrecisionLandingPhase,
    PrecisionLandingSimulator,
    estimate_relative_target,
    write_precision_landing_artifacts,
)


class PrecisionLandingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()

    def test_estimate_relative_target_converts_angles_to_offsets(self) -> None:
        observation = LandingTargetObservation(
            acquired=True,
            quality=1.0,
            forward_angle_rad=0.1,
            right_angle_rad=-0.2,
            range_m=5.0,
        )
        estimate = estimate_relative_target(observation)

        self.assertAlmostEqual(estimate.forward_error_m, 0.501673, places=5)
        self.assertAlmostEqual(estimate.right_error_m, -1.01355, places=5)
        self.assertGreater(estimate.horizontal_error_m, 1.0)

    def test_controller_aligns_when_horizontal_error_exceeds_target(self) -> None:
        controller = PrecisionLandingController(self.baseline)
        observation = LandingTargetObservation(
            acquired=True,
            quality=0.95,
            forward_angle_rad=0.2,
            right_angle_rad=0.0,
            range_m=4.0,
        )

        state = controller.step(observation, time_s=0.0)

        self.assertEqual(state.phase, PrecisionLandingPhase.ALIGN)
        self.assertLess(state.command.forward_velocity_mps, 0.0)
        self.assertEqual(state.command.descent_rate_mps, 0.0)

    def test_controller_descends_when_locked_inside_target_window(self) -> None:
        controller = PrecisionLandingController(self.baseline)
        observation = LandingTargetObservation(
            acquired=True,
            quality=0.95,
            forward_angle_rad=0.02,
            right_angle_rad=-0.01,
            range_m=3.0,
        )

        state = controller.step(observation, time_s=0.0)

        self.assertEqual(state.phase, PrecisionLandingPhase.DESCEND)
        self.assertGreater(state.command.descent_rate_mps, 0.0)

    def test_controller_aborts_after_sustained_target_loss(self) -> None:
        controller = PrecisionLandingController(self.baseline)
        locked = LandingTargetObservation(
            acquired=True,
            quality=0.95,
            forward_angle_rad=0.01,
            right_angle_rad=0.01,
            range_m=2.0,
        )
        controller.step(locked, time_s=0.0)

        lost = LandingTargetObservation(
            acquired=False,
            quality=0.0,
            forward_angle_rad=0.0,
            right_angle_rad=0.0,
            range_m=2.0,
        )
        search_state = controller.step(lost, time_s=1.0)
        abort_state = controller.step(lost, time_s=3.1)

        self.assertEqual(search_state.phase, PrecisionLandingPhase.SEARCH)
        self.assertEqual(abort_state.phase, PrecisionLandingPhase.ABORT)

    def test_precision_landing_simulator_runs_default_scenarios(self) -> None:
        simulator = PrecisionLandingSimulator(self.baseline)
        results, step_map = simulator.run_default_scenarios()
        result_by_name = {result.name: result for result in results}

        self.assertTrue(result_by_name["nominal_precision_touchdown"].passed)
        self.assertTrue(result_by_name["short_target_loss_reacquire"].passed)
        self.assertFalse(result_by_name["sustained_target_loss_abort"].passed)
        self.assertIn("nominal_precision_touchdown", step_map)

    def test_precision_landing_artifacts_are_written(self) -> None:
        simulator = PrecisionLandingSimulator(self.baseline)
        results, step_map = simulator.run_default_scenarios()

        with tempfile.TemporaryDirectory() as tmp_dir:
            destination = write_precision_landing_artifacts(tmp_dir, results, step_map)
            manifest = json.loads((Path(destination) / "manifest.json").read_text(encoding="utf-8"))
            summary = (Path(destination) / "summary.md").read_text(encoding="utf-8")

        self.assertEqual(manifest["scenario_count"], 3)
        self.assertEqual(manifest["passed_count"], 2)
        self.assertIn("nominal_precision_touchdown", summary)
        self.assertIn("sustained_target_loss_abort", summary)


if __name__ == "__main__":
    unittest.main()
