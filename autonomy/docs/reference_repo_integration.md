# 8OL-Robotics Integration Guide

This guide details exactly how the external `8OL-Robotics/precision-landing` reference codebase was conceptually unified with SkyLink's rigorous SITL pipeline, and how to verify correct calibration.

## Architectural Migrations

The reference codebase achieved landing via raw MAVSDK Offboard mode, forcefully injecting positional waypoints overriding PX4. Because SkyLink requires standardized deployment (HITL via UART / `pymavlink`), a translation layer was built:

1. **PID Controllers**: `NED_controllers.py` evolved into `drone_system/pid_controller.py`. The math remains unchanged (including the crucial Integral Windup guard), but it outputs standard SkyLink `command_right_velocity` data.
2. **Camera Robustness**: `estimators/aruco_reader.py` evolved into `companion/aruco_board_detector.py`. Standard grid board arrays guarantee pose estimations remain stable even when individual marker IDs are occluded by drone landing gear.

## Camera Calibration & Hardware Requirements

Before flight, it is essential that the local `SKYLINK_CAMERA_CALIBRATION` JSON accurately captures your Raspberry Pi camera intrinsics. Because the multi-marker system heavily leverages `rvec`/`tvec` outputs, lens distortion will cause horizontal drift during the ALIGN phase.
- An RMS error > 1.0 indicates poor radial correction.
- Ensure you run intrinsic calibration using a checkerboard capturing edge distortions.

### Mandatory Hardware LiDAR Check
To execute the absolute final Touchdown and precise angular offsets during the Flare stage without drifting laterally, your physical rig MUST include a downward-facing LiDAR/Rangefinder (e.g. TFmini Plus or LightWare). Barometric sensors alone will inevitably drift close to the ground due to pressure zones (the ground-effect cushion). PX4's internal Extended Kalman Filter strictly requires consistent, non-drifting altitude inputs to lock in the `LANDING_TARGET` angle equations. If altitude drifts, angular tracking collapses, and precision landing fails.

## Local PID Tuning Advice
Instead of relying purely on PX4's internal `PLD` gains, you can optionally dial the `PIDController` for your actual physical airframe's thrust-to-weight ratio:
- **Proportional (P)**: Raise `k_p` (e.g. `0.8`) for aggressive alignment when drone is off-center but sluggish. Lower if drone nervously oscillates left-to-right.
- **Windup Guard**: Set cautiously (e.g. `2.0`). This stops the drone from storing massive integral error if a gust of wind pins it against a wall during descent, preventing it from violently springing backward.

## Simulation Considerations
1. Ensure the simulation container (`nvidia/cuda` Vast.ai deployment) maintains real-time Gazebo metrics.
2. Verify that the simulation marker dimensions (0.2m) perfectly match the physical marker array size configuring the board.
