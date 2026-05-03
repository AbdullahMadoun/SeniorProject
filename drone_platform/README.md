# SkyLink Drone Platform

This folder is the GitHub entrypoint for the real drone/autonomy workstream.

It exists to make the repo readable from the top level without forcing reviewers to discover the stack by digging through `autonomy/`, generated artifacts, and milestone notes manually.

## What This Covers

- PX4-targeted flight software backbone
- PX4 SITL + Gazebo simulation path
- MAVSDK mission upload and execution validation
- Safety policy:
  - geofence
  - battery RTL
  - wind gating
  - mission-area validation
- Dock return and precision-landing path
- Landing-target streaming and receiver proof
- Judge-facing Three.js replay showcase

## Start Here

- [Latest Evidence Summary](EVIDENCE.md)
- [Reproduction Runbook](RUNBOOK.md)
- [Autonomy Source Tree](../autonomy/README.md)
- [Autonomy Milestones](../autonomy/docs/milestone_results.md)
- [Autonomy Reproducibility Runbook](../autonomy/docs/reproducibility_runbook.md)
- [Latest Showcase HTML](../artifacts/showcase/latest/index.html)
- [Latest Showcase Data](../artifacts/showcase/latest/showcase_data.json)

## Current Validated State

- live PX4 SITL mission validation is working
- live dock-approach validation is working
- latest showcase payload contains unified full-flight telemetry
- latest showcase payload contains recorded roll/pitch/yaw from live telemetry
- latest showcase payload contains recorded mission waypoint local coordinates

Current evidence snapshot from the latest generated artifacts:

- mission waypoint count: `6`
- unified flight telemetry frames: `13`
- landing-target receiver count: `50`
- dock proof status: `consumed_from_live_telemetry_projection`
- final dock horizontal distance: `0.07548274437382324 m`
- full regression suite: `51` tests passing

## Main Paths

- [Drone Code](../autonomy/drone_system/)
- [Scripts](../autonomy/scripts/)
- [Tests](../autonomy/tests/)
- [Docs](../autonomy/docs/)
- [Replay Bundle](../artifacts/replay_bundle/latest/summary.md)
- [Showcase Output](../artifacts/showcase/latest/index.html)
- [Live PX4 Evidence](../artifacts/live_px4/)

## Review Order

1. Read [EVIDENCE.md](EVIDENCE.md)
2. Open [index.html](../artifacts/showcase/latest/index.html)
3. Read [milestone_results.md](../autonomy/docs/milestone_results.md)
4. Use [RUNBOOK.md](RUNBOOK.md) for local validation
