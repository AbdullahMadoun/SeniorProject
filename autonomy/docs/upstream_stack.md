# Upstream Stack Map

This project will preferentially use official upstream components and examples.

## Source of Truth by Layer

### Flight Controller and Hardware Parameters

- Upstream: `vendor/PX4-Autopilot`
- Why: real hardware target is PX4
- Use for:
  - firmware and parameter references
  - PX4 SITL
  - Gazebo simulation path
  - QGroundControl compatibility

### Mission API and Telemetry

- Upstream: `vendor/MAVSDK-Python`
- Why: official PX4-compatible Python control path
- Use for:
  - mission upload
  - telemetry subscriptions
  - geofence upload
  - action / RTL / health checks

### Alternative Simulation Path

- Upstream: `vendor/ardupilot`
- Why: required to support Phase 0 Option A from the reference
- Use for:
  - ArduPilot SITL
  - MAVProxy routing
  - cross-checking mission behavior in a second simulator

### Operator Visualization

- Upstream runtime: QGroundControl binary
- Why: existing mature operator UI for missions, parameters, geofence, telemetry

### Project-Specific Glue We Still Need

- Mission footprint generation for the inspection pattern
- Synthetic telemetry generator for no-flight/no-camera testing
- Local control-unit emulator
- Safety policy enforcement wrapper
- Lightweight replay visualizer for telemetry and result inspection

These are the only places where custom code is justified.
