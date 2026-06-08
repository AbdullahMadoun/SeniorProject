# 🚁 SkyLink

![SkyLink Status](https://img.shields.io/badge/Status-Active-success)
![Drone Stack](https://img.shields.io/badge/Subsystem-Drone_Autonomy-blue)
![AI Stack](https://img.shields.io/badge/Subsystem-Road_Inspection-orange)

SkyLink is an integrated repository for two connected systems:
1. **Drone Autonomy Stack:** A PX4-targeted drone autonomy and simulation framework.
2. **Road Inspection Stack:** An AI application stack for road condition analysis.

> **Note:** The drone autonomy stack is currently the primary workstream.

---

## 🎯 Quick Start

Get started with the primary drone stack modules:

- 📖 [**Drone Platform Overview**](drone_platform/README.md)
- 📊 [**Drone Platform Evidence**](drone_platform/EVIDENCE.md)
- 🚀 [**Drone Platform Runbook**](drone_platform/RUNBOOK.md)
- 🌐 [**Latest Showcase HTML**](artifacts/showcase/latest/index.html)
- 🏁 [**Autonomy Milestones**](autonomy/docs/milestone_results.md)
- 🔄 [**Autonomy Reproducibility Runbook**](autonomy/docs/reproducibility_runbook.md)

---

## 🛸 Current Drone Stack

The repository contains a simulation-first flight software backbone designed to transition seamlessly from local validation to real PX4 hardware with minimal rewrite.

### Implemented Scope
- ✅ **PX4 SITL & Gazebo** simulation path
- ✅ **MAVSDK** mission upload and execution validation
- ✅ Safety logic including **geofence**, **wind-gate**, and **RTL** (Return to Launch)
- ✅ Landing-target streaming and receiver proof
- ✅ Dock approach validation with live telemetry
- ✅ Precision-landing controller with PX4 landing profile
- ✅ Judge-facing **Three.js** replay showcase generated from validated artifacts

### 📊 Latest Validated Snapshot
| Metric | Value |
|--------|-------|
| Mission Waypoints | `6` |
| Unified Flight Telemetry Frames | `13` |
| Landing-Target Receivers | `50` |
| Dock Proof | `consumed_from_live_telemetry_projection` |
| Final Dock Horizontal Distance | `0.075 m` |
| Full Regression Suite | `51 tests passing` |

---

## 📂 Repository Layout

```text
SkyLink/
├── drone_platform/          # GitHub-facing entry for the drone stack
├── autonomy/                # Drone autonomy code, docs, scripts, and tests
├── artifacts/               # Curated latest evidence and showcase outputs
├── app/                     # Road-inspection bridge and frontend
├── model_server/            # Hosted model-serving components
├── vendor/                  # Local upstream simulator checkout area
├── examples/                # Static example media
├── PROJECT_REPORT.md        # Older road-inspection MVP report
└── REPRODUCIBLE_SETUP.md    # Older bridge-stack setup notes
```

---

## 🚦 Main Subsystems

### 🚁 1. Drone Platform (Primary)
- [Overview](drone_platform/README.md)
- [Evidence](drone_platform/EVIDENCE.md)
- [Runbook](drone_platform/RUNBOOK.md)
- [Autonomy Source Tree](autonomy/README.md)
- [Latest Showcase](artifacts/showcase/latest/index.html)

### 🛣️ 2. Road Inspection Stack (Legacy/Secondary)
This subsystem remains in the repository but is no longer the main entry point.
- `app/`
- `model_server/`
- [PROJECT_REPORT.md](PROJECT_REPORT.md)
- [REPRODUCIBLE_SETUP.md](REPRODUCIBLE_SETUP.md)

---

## 🎬 Reproduce the Drone Showcase

You can run the drone showcase locally using the following commands:

```bash
# Run tests
python -m unittest discover -s autonomy/tests -p "test_*.py"

# Build replay bundle
python autonomy/scripts/build_latest_replay_bundle.py

# Build showcase HTML
python autonomy/scripts/build_showcase.py

# Serve the showcase locally
python -m http.server 8888 --directory artifacts/showcase/latest
```

Then open your browser to: [http://127.0.0.1:8888](http://127.0.0.1:8888)

---

## 📝 Notes
- `vendor/`: Intentionally kept as a local bootstrap area for upstream PX4, ArduPilot, and MAVSDK checkouts.
- `artifacts/`: The generated showcase and replay bundle are the current review-ready outputs for the drone stack.
