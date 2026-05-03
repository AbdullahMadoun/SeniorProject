# SkyLink Architecture Decisions

This document records the current implementation decisions for the full SkyLink software scope.

It exists to stop the project from drifting between multiple simulator paths and partially compatible control stacks.

## Decision 1: Mainline Flight Stack

Selected stack:

- `PX4 SITL`
- modern `Gazebo` (`sim_gazebo_gz`)
- `MAVSDK-Python`
- `QGroundControl`

Rationale:

- the real hardware target is PX4/Pixhawk
- MAVSDK-Python is the defensible Python control path for PX4
- QGroundControl is already the expected operator and validation tool
- modern Gazebo gives a cleaner path for wind worlds, camera plugins, and longer-term support than using ArduPilot as the primary integration stack

Primary upstream references:

- [sim_gazebo_gz/index.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/index.md)
- [mission.py](/D:/downloads/SeniorProject/Skylink2/vendor/MAVSDK-Python/examples/mission.py)
- [geofence.py](/D:/downloads/SeniorProject/Skylink2/vendor/MAVSDK-Python/examples/geofence.py)

## Decision 2: Simulation Priority

Selected priority:

1. local emulator
2. PX4 SITL
3. recorded 3D simulation output
4. real PX4 hardware

Rationale:

- emulator gives deterministic fast tests
- PX4 SITL proves the real autopilot interface
- recorded 3D outputs satisfy evidence and judging needs without requiring fragile live-demo dependencies
- real hardware should only be attached after software proof exists

## Decision 3: Weather and Wind Validation

Selected path:

- use the modern Gazebo `windy` world as the main upstream weather proof path

Primary upstream references:

- [sim_gazebo_gz/index.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/index.md)
- [worlds.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/worlds.md)

Applied rule:

- `7 m/s` is the operating wind limit
- any mission above that must be rejected or aborted by policy

## Decision 4: Precision Landing Strategy

Selected path:

- camera-marker precision landing with offboard `LANDING_TARGET` updates into PX4
- required precision landing mode during RTL
- range sensing remains part of the real system baseline for final descent support

Primary upstream references:

- [precland.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/advanced_features/precland.md)
- [vehicles.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/vehicles.md)
- [worlds.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/worlds.md)

Selected simulation variant:

- `gz_x500_mono_cam_down`
- `aruco` world
- companion-side visual detection publishes `LANDING_TARGET`
- PX4 `RTL_PLD_MD=2`

Current engineering gap:

- upstream modern Gazebo exposes camera-down and lidar-down as separate stock vehicle variants
- it does not currently provide a turnkey upstream combined camera-plus-range precision-landing multicopter model for this exact use case

Project implication:

- we will not fake the missing combined model
- we will either:
  - simulate the vision-based precision landing path in modern Gazebo and validate range-assisted final descent through the control/emulation layer, or
  - create a documented integration bridge for the combined-sensor simulation while keeping the control logic aligned with PX4 contracts

## Decision 5: Logging and Replay

Selected path:

- `ULog` on every run
- Flight Review for engineering analysis
- parsed ULog plus recorded video for judge-facing replay

Primary upstream references:

- [logging.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/dev_log/logging.md)
- [flight_review.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/log/flight_review.md)
- [system_wide_replay.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/debug/system_wide_replay.md)
- [ulog_file_format.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/dev_log/ulog_file_format.md)

Rule:

- a run that does not emit replayable artifacts is not accepted as proof

## Decision 6: Judge-Facing Simulation Output

Selected path:

- recordable simulation video using Gazebo GStreamer output
- telemetry replay built from ULog-derived data
- custom web replay layer for offline presentation

Primary upstream references:

- [plugins.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/docs/en/sim_gazebo_gz/plugins.md)
- [README.md](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/simulation/gz_plugins/gstreamer/README.md)

Rationale:

- this satisfies the requirement to prove the system visually without depending on a live cloud demo
- recorded outputs are easier to validate, version, and present than live simulator streaming

## Decision 7: Secondary Paths

Allowed but not mainline:

- ArduPilot SITL as a fallback test environment
- Gazebo Classic only if a specific feature is impossible to validate in the modern stack and the reason is documented

Rule:

- the project must not silently fork into two control architectures
- PX4 remains the source of truth for the actual deployed drone path
