# SkyLink

SkyLink is now an integrated repository for two connected systems:

1. a PX4-targeted drone autonomy and simulation stack
2. a road-inspection AI application stack

The drone/autonomy stack is the current primary workstream.

## Start Here

- [Drone Platform Overview](drone_platform/README.md)
- [Drone Platform Evidence](drone_platform/EVIDENCE.md)
- [Drone Platform Runbook](drone_platform/RUNBOOK.md)
- [Latest Showcase HTML](artifacts/showcase/latest/index.html)
- [Autonomy Milestones](autonomy/docs/milestone_results.md)
- [Autonomy Reproducibility Runbook](autonomy/docs/reproducibility_runbook.md)

## Current Drone Stack

The repo now contains a simulation-first flight software backbone that is intended to move from local validation to real PX4 hardware with minimal rewrite.

Current implemented scope includes:

- PX4 SITL plus Gazebo simulation path
- MAVSDK mission upload and execution validation
- geofence, wind-gate, and RTL safety logic
- landing-target streaming and receiver proof
- dock approach validation with live telemetry
- precision-landing controller and PX4 landing profile
- judge-facing Three.js replay showcase generated from validated artifacts

Latest validated snapshot:

- mission waypoint count: `6`
- unified flight telemetry frames: `13`
- landing-target receiver count: `50`
- dock proof: `consumed_from_live_telemetry_projection`
- final dock horizontal distance: `0.07548274437382324 m`
- full regression suite: `51` tests passing

## Repository Layout

```text
Skylink2/
├── drone_platform/          GitHub-facing entry for the drone stack
├── autonomy/                Drone autonomy code, docs, scripts, and tests
├── artifacts/               Curated latest evidence and showcase outputs
├── app/                     Road-inspection bridge and frontend
├── model_server/            Hosted model-serving components
├── vendor/                  Local upstream simulator checkout area
├── examples/                Static example media
├── PROJECT_REPORT.md        Older road-inspection MVP report
└── REPRODUCIBLE_SETUP.md    Older bridge-stack setup notes
```

## Main Paths

### Drone Platform

- [Overview](drone_platform/README.md)
- [Evidence](drone_platform/EVIDENCE.md)
- [Runbook](drone_platform/RUNBOOK.md)
- [Autonomy Source Tree](autonomy/README.md)
- [Latest Showcase](artifacts/showcase/latest/index.html)

### Road Inspection Stack

This subsystem remains in the repo, but it is no longer the main entrypoint.

Primary paths:

- `app/`
- `model_server/`
- [PROJECT_REPORT.md](PROJECT_REPORT.md)
- [REPRODUCIBLE_SETUP.md](REPRODUCIBLE_SETUP.md)

## Reproduce The Drone Showcase

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
python -m http.server 8888 --directory D:\downloads\SeniorProject\Skylink2\artifacts\showcase\latest
```

Then open:

- `http://127.0.0.1:8888`

## Notes

- `vendor/` is intentionally a local bootstrap area for upstream PX4, ArduPilot, and MAVSDK checkouts.
- The generated showcase and replay bundle in `artifacts/` are the current review-ready outputs for the drone stack.
