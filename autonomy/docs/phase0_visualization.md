# Phase 0 Visualization Strategy

## Objective

Give the team an operator-facing view of mission controls and mission results before any real flight.

## Visualization Layers

1. QGroundControl for operator control and parameter visibility
2. A local telemetry visualizer for:
   - mission footprint
   - path replay
   - altitude/speed/battery trends
   - 3D trajectory preview

## Device Recommendation

This laptop is suitable for:
- QGroundControl
- ArduPilot SITL
- MAVProxy
- synthetic telemetry replay
- lightweight 3D trajectory visualization in a browser

This laptop is not a strong baseline for:
- full PX4 SITL + Gazebo Classic as the primary workflow

Reason:
- 8 GB RAM
- Intel UHD 620 integrated graphics
- limited free memory during the current session

## Decision

We should build the lightweight telemetry visualizer first, and treat Gazebo 3D as an optional
follow-up experiment on this machine or a stronger Linux workstation.
