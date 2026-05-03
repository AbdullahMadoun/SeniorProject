# Companion Hardware Layer

This package is the hardware-facing companion-computer layer for the drone system.

It is intentionally isolated from the dashboard and mission API. The goal is for the
same Python modules to run:

- on a Raspberry Pi with real GPIO, ADS1115, MAVLink UART, and USB cameras
- on a Windows laptop with mock GPIO, mock ADC readings, mock MAVLink, and mock camera frames

## Modules

- `mock_rpi.py`
  - automatic fallback for `RPi.GPIO`, `board`, `busio`, `adafruit_ads1x15`, and `cv2`
- `run_companion_smoke.py`
  - one-command validation harness that runs the full companion stack in mock mode and writes a reproducible artifact bundle
- `bootstrap_rpi_companion.sh`
  - Raspberry Pi bootstrap for apt packages, Python venv, UART/I2C enablement, and import verification
- `requirements-rpi.txt`
  - companion-specific Pi dependency set
- `generate_checkerboard.py`
  - printable SVG checkerboard target generator for camera calibration
- `generate_aruco_marker.py`
  - ArUco marker generator with explicit metadata about whether output came from real OpenCV or the mock fallback
- `calibrate_camera.py`
  - template-mode and real-image camera calibration utility
- `video_logger.py`
  - threaded MAVLink `GLOBAL_POSITION_INT` polling plus camera overlay, CSV logging, optional MJPEG FPV streaming for the dashboard, and default CPU isolation on Core `1`
- `aruco_detector.py`
  - ArUco marker detection and `LANDING_TARGET` MAVLink publishing
- `gpio_charging.py`
  - dock contact and battery voltage safety gate for charging MOSFET enable
- `yolo_pothole_detect.py`
  - deterministic stub to keep downstream pothole CSV consumers alive

## Mock Control Environment Variables

- `SKYLINK_FORCE_MOCK_GPIO=1`
- `SKYLINK_FORCE_MOCK_CAMERA=1`
- `SKYLINK_MOCK_CONTACT_VOLTAGE=1.2`
- `SKYLINK_MOCK_BATTERY_VOLTAGE=16.8`
- `SKYLINK_MOCK_ARUCO_DETECTION=1`

## Output Bundle

The companion smoke harness writes to:

- `autonomy/companion/artifacts/latest`

Expected files:

- `manifest.json`
- `summary.md`
- `video_logger/telemetry_log.csv`
- `aruco_detector/landing_target_log.json`
- `gpio_charging/charging_decisions.json`
- `yolo_stub/pothole_detections.csv`

## Example Commands

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\run_companion_smoke.py
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\generate_checkerboard.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\calibration_target
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\generate_aruco_marker.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\marker_target
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\calibrate_camera.py --image-glob "D:\captures\checkerboard\*.png" --output D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\camera_calibration.json --template-only
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --max-frames 5
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --stream --cpu-core 1 --max-frames 30
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --stream --stream-port 5050 --max-frames 30
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\aruco_detector.py --mock-mavlink --mock-camera --max-frames 5
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\gpio_charging.py --cycles 1
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\yolo_pothole_detect.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\outputs\yolo
```

## Deployment Modes

- Mock / laptop mode:
  - use the smoke runner or pass `--mock-camera` / `--mock-mavlink`
  - GPIO and ADS hardware fall back automatically on Windows
- Raspberry Pi mode (production):
  - keep the same scripts
  - MAVLink reaches the autopilot via the MAVProxy systemd bridge:
    Pixhawk 4 → `/dev/ttyACM0` (USB-CDC) → `mavproxy-skylink.service` →
    `udp:127.0.0.1:14551`. `video_logger.py` defaults its
    `--mavlink-target` to that UDP endpoint, so no flag is needed in
    production. See [deploy/companion/README.md](/deploy/companion/README.md)
    for service install / verify / disable.
  - point cameras at the real USB index or GStreamer string
  - replace the placeholder intrinsics in `aruco_detector.py` with real calibration data
  - run `bootstrap_rpi_companion.sh` first to create the Pi-side environment
  - alternative: direct UART via `/dev/ttyAMA0` / `/dev/serial0` (TELEM2)
    is supported by the pipeline but not currently used; switch to it
    only when `mavproxy-skylink` is intentionally disabled.

Detailed procedures are in [RUNBOOK.md](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/RUNBOOK.md).
