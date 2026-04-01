# Drone Platform Evidence

This page is the shortest path to the current drone-stack proof artifacts.

## Latest Judge-Facing Output

- [Three.js Showcase HTML](../artifacts/showcase/latest/index.html)
- [Showcase Data Payload](../artifacts/showcase/latest/showcase_data.json)

The current showcase includes:

- unified `flight_telemetry`
- dark-mode Three.js 3D scene
- waypoint markers
- quadcopter mesh with live attitude playback
- mode-colored flight path
- HUD, timeline, speed controls, and camera presets
- weather, mission, and precision-landing evidence sections

## Latest Replay Bundle

- [Replay Bundle Summary](../artifacts/replay_bundle/latest/summary.md)
- [Replay Bundle Manifest](../artifacts/replay_bundle/latest/manifest.json)
- [Dock Approach Timeline CSV](../artifacts/replay_bundle/latest/dock_approach_timeline.csv)

## Latest Live PX4 Evidence

- [Mission Validation](../artifacts/live_px4/latest_mission_validation.json)
- [Execution Validation](../artifacts/live_px4/latest_execution_validation.json)
- [Precision Landing Profile](../artifacts/live_px4/latest_precision_landing_profile.json)
- [Landing Target Consumption](../artifacts/live_px4/latest_landing_target_consumption.json)
- [Dock Approach Validation](../artifacts/live_px4/latest_dock_approach_validation.json)

## Supporting Scenario Evidence

- [Precision Landing Manifest](../artifacts/precision_landing/latest/manifest.json)
- [Precision Landing Summary](../artifacts/precision_landing/latest/summary.md)
- [Weather Scenario Manifest](../artifacts/weather_scenarios/latest/manifest.json)
- [Weather Scenario Summary](../artifacts/weather_scenarios/latest/summary.md)

## Current Verified Values

- mission waypoint count: `6`
- unified flight telemetry frames: `13`
- landing-target receiver count: `50`
- final dock horizontal distance: `0.07548274437382324 m`
- dock proof status: `consumed_from_live_telemetry_projection`
- full regression suite: `Ran 51 tests ... OK`
