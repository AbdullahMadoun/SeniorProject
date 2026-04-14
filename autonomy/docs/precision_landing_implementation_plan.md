# Precision Landing Implementation Plan for Skylink2 (V2: Hardened & Production-Ready)

## Overview

This plan adapts components from the [8OL-Robotics/precision-landing](https://github.com/8OL-Robotics/precision-landing) reference repo to enhance Skylink2's precision landing capabilities. Given the high stakes of physical deployment, this plan has been hardened to account for real-world robotics edge cases: network latency, CPU bottlenecks, and visual degradation.

## Current State Analysis

### Existing Skylink2 Implementation
- **Location**: `Skylink2/autonomy/drone_system/precision_landing.py`
- **Approach**: Gain-based velocity control (not explicit PID)
- **Phases**: SEARCH → ALIGN → DESCEND → FLARE → TOUCHDOWN → ABORT
- **ArUco Detection**: Single marker in `companion/aruco_detector.py`
- **Landing Accuracy Target**: `<= 0.4m` (from system_baseline.md)

### Identified Weaknesses (To Fix)
1. **CPU Throttling**: The Pi CPU running OpenCV can lag, causing stale PID updates.
2. **Motion Blur Dropouts**: High descent rates cause ArUco blur, leading to target loss right before touchdown.
3. **Wind Disturbances**: Simple gain controllers fail to overcome sustained crosswinds.

### Reference Repo Components to Adapt
| Component | File | Value to Extract |
|-----------|------|------------------|
| PID Controller | `NED_controllers.py` | Explicit PID with windup guard to fight crosswinds. |
| Multi-marker Board | `aruco_reader.py` | Board detection for robustness against obscuration. |
| Multi-process Queue | `__main__.py` | Async CV pattern to decouple slow vision from fast PID. |

## Implementation Phases

### Phase 1: Add Explicit PID Controller (COMPLETED)
**Goal**: Add a proper PID controller class to fight wind shear, overriding the basic gain system.
**Location**: `Skylink2/autonomy/drone_system/pid_controller.py`
**Features**:
- Configurable P, I, D gains.
- **Critical addition**: Integral windup guard to ensure the drone doesn't dangerously spring backward after fighting a steady gust of wind.

### Phase 2: ArUco Board Detection Support (COMPLETED)
**Goal**: Extend ArUco detection to a `cv2.aruco.GridBoard`.
**Location**: `Skylink2/autonomy/companion/aruco_board_detector.py`
**Features**:
- Uses multiple markers. If landing gear obscures one, pose estimation survives.
- Falls back to single marker computation automatically if frame drops occur.

### Phase 3: Hardware & Network Guardrails (NEW)
**Goal**: Ensure physical deployment doesn't fail due to hardware limits.
**Location**: `Skylink2/autonomy/drone_system/precision_landing.py` & Camera configs.
**Features**:
- **Stale Observation Guard**: If the timestamp of the incoming `LandingTargetObservation` is older than `0.5s` (due to Pi CPU lag or UART drop), the drone must immediately pause X/Y descent and enter a safe hover.
- **Shutter Config**: Update the `v4l2-ctl` or `libcamera` settings in the environment stack to force lowest possible exposure time to kill motion blur.

### Phase 4: Documentation & Integration
**Goal**: Create integration guide connecting reference repo concepts to Skylink2.
**Locations**: 
- `Skylink2/autonomy/docs/precision_landing_architecture.md`
- `Skylink2/autonomy/docs/reference_repo_integration.md`
**Content**:
- MAVLink bridging via `LANDING_TARGET` messages over `pymavlink` (so we do not hijack PX4 `RTL_PLD_MD`).

## Key Implementation Decisions

### 1. Maintain PX4 Authority
- Do NOT bypass `LANDING_TARGET` or use raw MAVSDK Offboard mode. By piping PID-smoothed coordinates into `LANDING_TARGET`, we allow PX4 to handle emergency radio-loss aborts natively.
### 2. Computational Decoupling
- The Companion computer ONLY computes the target offset (CV) and sends coordinates. The actual PID velocity computation runs cleanly inside `precision_landing.py` loop so it doesn't get slowed down by OpenCV's frame-rate.

## Testing Strategy (Zero-Error Verification)

1. **SITL Wind Shear Test**: Boot Vast.ai SITL and artificially inject a 5m/s lateral wind in Gazebo. Verify the `Integral` term of the PID correctly accumulates to hold the drone perfectly over the bad.
2. **CPU Profiling Check**: Run `aruco_board_detector.py` bare-metal on the Raspberry Pi with `htop`. If it dips below 15 FPS, implement explicit `cv2.resize()` downsampling before processing.
3. **Occlusion Test**: In Gazebo, place a black visual block over half the ArUco pad. Ensure `estimatePoseBoard` successfully derives pose from the remaining visible markers.

## Action Items

- [x] Create `drone_system/pid_controller.py` - PID controller class
- [x] Create `companion/aruco_board_detector.py` - Board detection
- [x] Create `docs/precision_landing_architecture.md` - Architecture documentation
- [x] Create `docs/reference_repo_integration.md` - Integration guide
- [x] Implement Stale Observation Guard in `precision_landing.py`.
- [x] Run SITL Wind Shear simulation.
- [x] Profile Raspberry Pi CPU under active descent.