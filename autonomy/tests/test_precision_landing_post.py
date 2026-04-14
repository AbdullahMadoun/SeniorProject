"""
Tests for precision landing guards.

These tests verify that:
1. Division by near-zero produces bounded velocity
2. NaN/Inf observations are rejected
3. Angles > 60 degrees are clamped
4. Negative range is rejected
"""

from __future__ import annotations

import math

import pytest


class TestDivisionGuard:
    """Tests for division-by-zero guard."""

    def test_horizontal_error_epsilon_defined(self):
        """Verify HORIZONTAL_ERROR_EPSILON is defined."""
        from autonomy.drone_system.precision_landing import HORIZONTAL_ERROR_EPSILON
        assert HORIZONTAL_ERROR_EPSILON >= 1e-6

    def test_max_velocity_ratio_defined(self):
        """Verify MAX_VELOCITY_RATIO is defined."""
        from autonomy.drone_system.precision_landing import MAX_VELOCITY_RATIO
        assert MAX_VELOCITY_RATIO == 10.0

    def test_near_zero_division_produces_bounded_velocity(self, baseline):
        """Near-zero division must NOT produce huge velocity."""
        from autonomy.drone_system.precision_landing import (
            PrecisionLandingController,
            PrecisionLandingTuning,
            LandingTargetObservation,
            RelativeLandingTarget,
            HORIZONTAL_ERROR_EPSILON,
            MAX_VELOCITY_RATIO,
        )

        observation = LandingTargetObservation(
            acquired=True,
            quality=0.95,
            forward_angle_rad=0.0001,
            right_angle_rad=0.0001,
            range_m=10.0,
        )

        target = RelativeLandingTarget(
            forward_error_m=0.001,
            right_error_m=0.001,
            down_error_m=10.0,
            horizontal_error_m=HORIZONTAL_ERROR_EPSILON / 2,
        )

        tuning = PrecisionLandingTuning()
        controller = PrecisionLandingController(baseline, tuning)

        state = controller.step(observation, time_s=0.0)

        max_possible_velocity = MAX_VELOCITY_RATIO * tuning.max_horizontal_speed_mps
        assert abs(state.command.forward_velocity_mps) <= max_possible_velocity + 0.1
        assert abs(state.command.right_velocity_mps) <= max_possible_velocity + 0.1


class TestObservationValidation:
    """Tests for observation validation."""

    def test_validate_observation_function_exists(self):
        """Verify validate_observation function exists."""
        from autonomy.drone_system.precision_landing import validate_observation
        assert callable(validate_observation)

    def test_nan_forward_angle_rejected(self, observation_nan):
        """NaN in forward_angle_rad must raise ValueError."""
        from autonomy.drone_system.precision_landing import validate_observation

        with pytest.raises(ValueError, match="not finite"):
            validate_observation(observation_nan)

    def test_inf_forward_angle_rejected(self, observation_inf):
        """Inf in forward_angle_rad must raise ValueError."""
        from autonomy.drone_system.precision_landing import validate_observation

        with pytest.raises(ValueError, match="not finite"):
            validate_observation(observation_inf)

    def test_negative_range_rejected(self, observation_negative_range):
        """Negative range must raise ValueError."""
        from autonomy.drone_system.precision_landing import validate_observation

        with pytest.raises(ValueError, match="range_m must be >"):
            validate_observation(observation_negative_range)

    def test_valid_observation_passes(self, observation_valid):
        """Valid observation passes validation."""
        from autonomy.drone_system.precision_landing import validate_observation

        result = validate_observation(observation_valid)
        assert result is observation_valid


class TestAngleClamping:
    """Tests for angle clamping."""

    def test_max_camera_angle_defined(self):
        """Verify MAX_CAMERA_ANGLE_RAD is defined."""
        from autonomy.drone_system.precision_landing import MAX_CAMERA_ANGLE_RAD
        assert MAX_CAMERA_ANGLE_RAD == math.radians(60.0)

    def test_clamp_angle_function_exists(self):
        """Verify clamp_angle function exists."""
        from autonomy.drone_system.precision_landing import clamp_angle
        assert callable(clamp_angle)

    def test_angle_over_60_clamped(self):
        """Angle > 60 degrees must be clamped."""
        from autonomy.drone_system.precision_landing import clamp_angle, MAX_CAMERA_ANGLE_RAD

        result = clamp_angle(math.radians(70.0))
        assert abs(result) <= MAX_CAMERA_ANGLE_RAD

    def test_angle_under_60_unchanged(self):
        """Angle < 60 degrees should be unchanged."""
        from autonomy.drone_system.precision_landing import clamp_angle, MAX_CAMERA_ANGLE_RAD

        angle = math.radians(45.0)
        result = clamp_angle(angle)
        assert result == angle


class TestQualityComputation:
    """Tests for quality computation from detection metrics."""

    def test_compute_detection_quality_function_exists(self):
        """Verify _compute_detection_quality function exists."""
        from autonomy.companion.aruco_detector import _compute_detection_quality
        assert callable(_compute_detection_quality)

    def test_min_corner_reject_ratio_defined(self):
        """Verify MIN_CORNER_REJECT_RATIO is defined."""
        from autonomy.companion.aruco_detector import MIN_CORNER_REJECT_RATIO
        assert MIN_CORNER_REJECT_RATIO == 0.5

    def test_quality_from_distance_defined(self):
        """Verify QUALITY_FROM_DISTANCE is defined."""
        from autonomy.companion.aruco_detector import QUALITY_FROM_DISTANCE
        assert isinstance(QUALITY_FROM_DISTANCE, dict)
        assert len(QUALITY_FROM_DISTANCE) > 0
