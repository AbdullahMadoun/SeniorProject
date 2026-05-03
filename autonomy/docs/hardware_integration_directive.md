# Codex Directive: Hardware & Computer Vision Integration

**From:** Project Manager  
**To:** Codex  
**Priority:** CRITICAL  
**Date:** 2026-04-01

---

## Problem Statement

We have successfully built the simulation backend, autonomy engine, safety parameters, and the web-based showcase dashboards. 
However, to fully satisfy the system requirements from the `Full Build Guide`, we must write the actual on-board Companion Computer code. These Python scripts must be hardware-ready (capable of running on a Raspberry Pi over UART and real USB cameras) while keeping fallback logic to run inside our SITL emulator.

Your task is to implement the Computer Vision pipeline, the Companion Logger, and the GPIO charging safety controller inside a new directory: `autonomy/companion/`.

---

## Strict Boundaries & Guiding Principles

1. **DO NOT REWRITE EXISTING SYSTEMS:** The current `mission_api.py`, Mega-Dashboard, and autonomy execution engine are working perfectly. Do NOT modify them or reconsider their implementations. This directive is strictly about adding the missing physical integration layer on top.
2. **PLUG-AND-PLAY EMULATION:** We must achieve true "plug-and-play" architecture. The code deployed to the Raspberry Pi must be identically executed on Windows laptops. This means you must build a robust Hardware Abstraction Layer / Emulation fallback so that tests NEVER fail due to missing physical GPIO or physical Cameras.

---

## Phase 1: Companion Video Logger (`autonomy/companion/video_logger.py`)

A multi-threaded script connecting to the MAVLink stream and Camera feed.
- **Hardware/Sim Toggle:** It must accept environment variables or flags to toggle MAVLink connection (`127.0.0.1:14551` vs `/dev/ttyAMA0`) and Camera connection (`0` for USB vs `GStreamer string` for Gazebo).
- **Core Loop:**
  - One thread polls the MAVLink `GLOBAL_POSITION_INT` to get the latest Lat/Lon/Alt.
  - Another thread reads the OpenCV camera frame, burns the latest GPS coordinate onto the frame using `cv2.putText`, and appends the bounding data to `telemetry_log.csv`.
- Must handle mock/lost GPS gracefully.

---

## Phase 2: ArUco Precision Landing (`autonomy/companion/aruco_detector.py`)

The on-board precision landing vision sensor block.
- **Logic:** Reads a downward-facing camera feed. Uses `cv2.aruco.detectMarkers(..., aruco.DICT_4X4_50)`. 
- **Calibration:** Hardcode a standard `CAMERA_MATRIX` and `DIST_COEFFS` placeholder array, but leave clear comments for the user on how to calibrate it.
- **Action:** If a marker (ID=0) is found, estimate pose with `aruco.estimatePoseSingleMarkers`. Take the `tvec` [x,y,z] relative pose and explicitly craft a `LANDING_TARGET` MAVLink message. Send it to the Pixhawk.

---

## Phase 3: YOLOv8 Pipeline Stub (Deprioritized)

- **IGNORE full YOLO integration for now.**
- Create a basic placeholder class `yolo_pothole_detect.py` that mocks inference.
- It should just output a dummy `pothole_detections.csv` so the downstream Flask dashboard doesn't break, allowing us to focus purely on the hardware integration code.

---

## Phase 4: GPIO Charging Safety Logic (`autonomy/companion/gpio_charging.py`)

The physical docking station controller.
- Write the interface using `RPi.GPIO` and `adafruit_ads1x15`.
- **Logic:** If `voltage_channel > 0.5V` (contact confirmed) AND `battery_channel == 16.8V ± 1.5V`, then pull the `CHARGE_ENABLE_PIN` (GPIO 17) to `HIGH` to engage the charging MOSFET.

---

## Phase 5: Raspberry Pi Emulation Layer (CRITICAL FOR PLUG-AND-PLAY)

The user requires that these scripts run **entirely unmodified** on both their Windows SITL laptop and the physical Raspberry Pi. No manual commenting out of libraries is allowed.
- Build a hardware abstraction module (e.g. `mock_rpi.py`). 
- When `import RPi.GPIO` or `import board` fails, the scripts MUST automatically fall back to mock GPIO and Mock I2C properties that simulate 16.8V battery contact and simulate camera inputs.
- You must ensure the environment dynamically emulates the Raspberry Pi so the integration is 100% plug-and-play.

---

## Acceptance Criteria

- [ ] New `autonomy/companion/` module created with all 4 python scripts inside.
- [ ] Requirements/Imports dynamically handled so running them on Windows/Test environments doesn't immediately crash due to missing Raspberry Pi hardware.
- [ ] Companion `video_logger.py` correctly overlays text from real/mock MAVLink GPS sources onto OpenCV frames.
- [ ] No regression or breakage to existing `mission_api.py` or dashboard infrastructure.
