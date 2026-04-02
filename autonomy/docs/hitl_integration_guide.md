# HITL Integration Guide - Hardware Transition

**From:** Sprint 10 Protocol
**Date:** 2026-04-02
**Objective:** Transition from simulation to physical hardware deployment

This guide covers the complete transition from mock/simulation mode to real Raspberry Pi + Pixhawk hardware deployment.

---

## Overview

### What Changes

| Component | Simulation Mode | Hardware Mode |
|-----------|-----------------|---------------|
| **MAVLink** | `udp:127.0.0.1:14551` (mock) | `/dev/ttyAMA0` baud=57600 |
| **Camera** | `--mock-camera` or "0" | Real USB index or GStreamer |
| **GPIO** | `SKYLINK_FORCE_MOCK_GPIO=1` | Real RPi.GPIO |
| **ADC** | Mock ADS1115 | Real ADS1115 via I2C |

### What Stays the Same

- **Dashboard SSE streaming** - Already complete in `mission_api.py`, CPU-isolated to core 0
- **Three.js/Leaflet Mega-Dashboard** - DO NOT modify
- **Safety engine logic** - Same validation rules apply
- **PX4 SITL or PX4 Hardware** - Same MAVSDK interface

---

## Phase 1: Raspberry Pi Bootstrap

Run on the Raspberry Pi before any hardware testing:

```bash
cd /path/to/SeniorProject/Skylink2/autonomy/companion
bash ./bootstrap_rpi_companion.sh
```

### What the Bootstrap Does

1. Installs apt packages (python3, i2c-tools, libjpeg-dev, etc.)
2. Creates `.venv-pi` virtual environment
3. Installs requirements from `requirements-rpi.txt`
4. Installs `opencv-contrib-python-headless`
5. Enables I2C and hardware serial via `raspi-config`
6. Verifies imports for pymavlink, board, busio, adafruit_ads1x15, cv2

### Post-Bootstrap Verification

```bash
source "$SCRIPT_DIR/.venv-pi/bin/activate"
python -c "import RPi.GPIO; print('GPIO OK')"
python -c "import board; print('board OK')"
python -c "import cv2; print('OpenCV:', cv2.__version__)"
```

---

## Phase 2: Wiring

### Pixhawk TELEM2 Connection (MAVLink UART)

```
Raspberry Pi          Pixhawk 4
-----------           ---------
GPIO 14 (TX)  <---->  TELEM2 RX
GPIO 15 (RX)  <---->  TELEM2 TX
GND          <---->  TELEM2 GND
```

**Pixhawk Configuration:**
- Set `SER_TEL2_BAUD` = 57600
- Set `MAV_0_MODE` = "Onboard"
- Set `MAV_0_FW_DEF` = 1

### GPIO Pin Map

| Function | Pin | Description |
|----------|-----|-------------|
| Charging MOSFET Enable | BCM 17 | Output - drives charging relay |
| ADS1115 SCL | BCM 3 (SCL) | I2C clock |
| ADS1115 SDA | BCM 2 (SDA) | I2C data |
| Contact Voltage Sense | ADS1115 Channel 0 | Analog input |
| Battery Voltage Sense | ADS1115 Channel 1 | Analog input |

### Camera Connection

- USB camera: `/dev/video0` (or higher index)
- For multiple cameras, enumerate with `v4l2-ctl --list-devices`

---

## Phase 3: Camera Calibration

### Generate Calibration Target

On laptop (generate SVG for printing):

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\generate_checkerboard.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\calibration_target
```

Print the generated checkerboard at exact size (check square_mm parameter).

### Capture Calibration Images

On the Pi with real camera attached:

```bash
mkdir -p ~/calibration_captures
# Manually capture 20+ checkerboard images at different angles
# Save as ~/calibration_captures/frame_XX.png
```

### Run Calibration

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\calibrate_camera.py --image-glob "/home/pi/calibration_captures/*.png" --output /home/pi/calibration.json
```

### Update aruco_detector.py

Replace placeholder values in `aruco_detector.py`:

```python
# Before (placeholder):
CAMERA_MATRIX = np.array([[615.0, 0.0, 320.0], ...])
DIST_COEFFS = np.zeros((5, 1), dtype=np.float32)

# After (from calibration):
CAMERA_MATRIX = np.array([
    [fx, 0, cx],
    [0, fy, cy],
    [0, 0, 1]
], dtype=np.float32)
DIST_COEFFS = np.array([k1, k2, p1, p2, k3], dtype=np.float32)
```

---

## Phase 4: Generate ArUco Marker

For precision landing, generate and print an ArUco marker:

```bash
source .venv-pi/bin/activate
python generate_aruco_marker.py --output-dir ~/markers --marker-id 0 --marker-size 0.2
```

Print the generated PDF at exactly 20cm square.

---

## Phase 5: Hardware Deployment Scripts

### Unified Hardware Launcher

Create `run_companion_hardware.sh` on the Pi:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ===========================================
# SkyLink Hardware Deployment Launcher
# ===========================================

export SKYLINK_MAVLINK_TARGET="/dev/ttyAMA0"
export SKYLINK_MAVLINK_BAUD="57600"
export SKYLINK_CAMERA_SOURCE="0"
export SKYLINK_VIDEO_STREAM_ENABLED="1"
export SKYLINK_VIDEO_LOGGER_CPU_CORE="1"

# Optional: Unset mock flags to ensure real hardware
unset SKYLINK_FORCE_MOCK_GPIO
unset SKYLINK_FORCE_MOCK_CAMERA
unset SKYLINK_MOCK_ARUCO_DETECTION

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SKYLINK_COMPANION_OUTPUT:-$SCRIPT_DIR/output/hardware}"

mkdir -p "$OUTPUT_DIR"

echo "[hardware] Starting video logger..."
python "$SCRIPT_DIR/video_logger.py" \
    --mavlink-target "$SKYLINK_MAVLINK_TARGET" \
    --mavlink-baud 57600 \
    --camera-source "$SKYLINK_CAMERA_SOURCE" \
    --output-dir "$OUTPUT_DIR/video_logger" \
    --stream \
    --stream-port 5050 \
    --cpu-core 1 \
    &
VIDEO_PID=$!

echo "[hardware] Starting ArUco detector..."
python "$SCRIPT_DIR/aruco_detector.py" \
    --mavlink-target "$SKYLINK_ARUCO_MAVLINK_TARGET" \
    --camera-source "$SKYLINK_CAMERA_SOURCE" \
    --marker-id 0 \
    --marker-size-m 0.2 \
    --output-dir "$OUTPUT_DIR/aruco" \
    &
ARUCO_PID=$!

echo "[hardware] Starting GPIO charging controller..."
python "$SCRIPT_DIR/gpio_charging.py" \
    --output-dir "$OUTPUT_DIR/gpio" \
    --cycles 0 \
    &
GPIO_PID=$!

echo "[hardware] All services started."
echo "  Video PID: $VIDEO_PID"
echo "  ArUco PID: $ARUCO_PID"
echo "  GPIO PID: $GPIO_PID"
echo "  MJPEG stream: http://$(hostname -I):5050/stream"

# Wait for all processes
wait
```

Make executable:

```bash
chmod +x run_companion_hardware.sh
```

---

## Phase 6: Validation

### Test Individual Components

**Video Logger (hardware mode):**

```bash
python video_logger.py --mavlink-target /dev/ttyAMA0 --mavlink-baud 57600 --camera-source 0 --max-frames 30
```

**ArUco Detector (hardware mode):**

```bash
python aruco_detector.py --mavlink-target /dev/ttyAMA0 --camera-source 0 --marker-id 0 --marker-size-m 0.2 --max-frames 30
```

**GPIO Charging (hardware mode):**

```bash
python gpio_charging.py --cycles 10
```

Expected: Charging decision toggles based on contact and battery voltage.

### Full Integration Test

```bash
# With Pixhawk connected and powered:
python run_companion_hardware.sh

# In another terminal, verify MAVLink:
python -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection('/dev/ttyAMA0', 57600)
msg = m.wait_heartbeat(timeout=5)
print('Heartbeat received:', msg)
"
```

---

## Phase 7: Dashboard Integration

### Stream to Dashboard

The MJPEG stream from the Pi is proxied through `mission_api.py`:

```
Pi Camera → MJPEG → http://pi-hostname:5050/stream → mission_api.py → /api/fpv/stream → Dashboard
```

On the Pi, set the stream URL:

```bash
export SKYLINK_FPV_SOURCE_URL="http://192.168.1.100:5050/stream"
```

On the dashboard host, ensure `mission_api.py` has:

```bash
python mission_api.py --fpv-proxy http://192.168.1.100:5050/stream --cpu-core 0
```

### Dashboard SSE Endpoint

The dashboard connects to SSE for live telemetry:

```
Dashboard → http://dashboard-host:5000/api/telemetry/live → mission_api.py → MAVSDK → Pixhawk
```

Verify SSE is working by checking the dashboard status panel.

---

## Troubleshooting

### MAVLink Connection Issues

1. Verify Pixhawk TELEM2 baud rate is 57600
2. Check wiring: TX→RX, RX→TX, GND→GND
3. Test with MAVLink shell: `microcom -s 57600 /dev/ttyAMA0`

### Camera Not Found

```bash
# List available cameras
v4l2-ctl --list-devices

# Test camera capture
python -c "import cv2; cap = cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL')"
```

### GPIO Permission Denied

```bash
# Add user to gpio group
sudo usermod -a -G gpio pi

# Reload groups
newgrp gpio
```

### ADS1115 I2C Not Detected

```bash
# Check I2C devices
i2cdetect -y 1

# Should show 48 (0x30) for ADS1115
```

---

## Safety Checklist

Before any flight:

- [ ] GPIO MOSFET enable is OFF by default (charging disabled until dock contact confirmed)
- [ ] Battery voltage within 15.3V - 18.3V range
- [ ] Contact voltage > 0.5V detected before charging enables
- [ ] Pixhawk heartbeat confirmed
- [ ] GPS fix obtained
- [ ] EKF healthy (check QGC)
- [ ] ArUco marker visible to downward camera
- [ ] Dashboard SSE stream active

---

## Quick Reference: Environment Variables

| Variable | Mock Value | Hardware Value |
|----------|-----------|----------------|
| `SKYLINK_MAVLINK_TARGET` | `udp:127.0.0.1:14551` | `/dev/ttyAMA0` |
| `SKYLINK_CAMERA_SOURCE` | `0` | `0` (USB) |
| `SKYLINK_FORCE_MOCK_GPIO` | `1` | (unset) |
| `SKYLINK_FORCE_MOCK_CAMERA` | `1` | (unset) |
| `SKYLINK_VIDEO_STREAM_ENABLED` | `0` | `1` |
| `SKYLINK_VIDEO_LOGGER_CPU_CORE` | `1` | `1` |

---

## Support

For issues:
1. Check `artifacts/latest/` for output logs
2. Run companion smoke test: `python run_companion_smoke.py`
3. Verify all tests pass: `python -m unittest discover -s autonomy/companion/tests -p "test_*.py"`
