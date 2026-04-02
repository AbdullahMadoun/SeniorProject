# Companion Runbook

This runbook covers the new companion-computer layer only. It does not modify or depend on the dashboard runtime.

## Scope

Modules covered here:

- [mock_rpi.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/mock_rpi.py)
- [video_logger.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/video_logger.py)
- [aruco_detector.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/aruco_detector.py)
- [gpio_charging.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/gpio_charging.py)
- [yolo_pothole_detect.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/yolo_pothole_detect.py)
- [run_companion_smoke.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/run_companion_smoke.py)

## Laptop Mock Validation

One-command validation:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\run_companion_smoke.py
```

Expected output root:

- `D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\latest`

Expected proof files:

- [manifest.json](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/artifacts/latest/manifest.json)
- [summary.md](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/artifacts/latest/summary.md)

## Script-Level Validation

### Video Logger

Mock mode:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --max-frames 10
```

Real hardware mode examples:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mavlink-target /dev/ttyAMA0 --mavlink-baud 57600 --camera-source 0
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mavlink-target udp:127.0.0.1:14551 --camera-source "udpsrc port=5600 ! ..."
```

Outputs:

- `telemetry_log.csv`
- `summary.json`
- `latest_frame.jpg.npy` in mock mode

### ArUco Precision Landing

Mock mode:

```powershell
$env:SKYLINK_MOCK_ARUCO_DETECTION='1'
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\aruco_detector.py --mock-mavlink --mock-camera --max-frames 10
```

Real hardware mode example:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\aruco_detector.py --mavlink-target /dev/ttyAMA0 --camera-source 0 --marker-id 0 --marker-size-m 0.2
```

Important:

- `CAMERA_MATRIX` and `DIST_COEFFS` in [aruco_detector.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/aruco_detector.py) are placeholders
- replace them with real calibration values before any flight test

### GPIO Charging Safety

Mock mode:

```powershell
$env:SKYLINK_FORCE_MOCK_GPIO='1'
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\gpio_charging.py --cycles 1
```

Logic:

- contact voltage must be `> 0.5V`
- battery voltage must be `16.8V ± 1.5V`
- then `GPIO 17` is driven high

### YOLO Stub

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\yolo_pothole_detect.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\latest\yolo_manual
```

## Environment Controls

- `SKYLINK_FORCE_MOCK_GPIO=1`
- `SKYLINK_FORCE_MOCK_CAMERA=1`
- `SKYLINK_MOCK_CONTACT_VOLTAGE=1.2`
- `SKYLINK_MOCK_BATTERY_VOLTAGE=16.8`
- `SKYLINK_MOCK_ARUCO_DETECTION=1`

These variables let the same source files run on Windows without manual code edits.

## Test Commands

Companion-only:

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\companion\tests -p "test_*.py"
```

Global regression boundary:

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

## Hardware Bring-Up Notes

- Raspberry Pi serial target will usually be `/dev/ttyAMA0` or `/dev/serial0`
- camera source should stay configurable because Gazebo, USB cameras, and Pi camera pipelines differ
- the companion scripts are designed to run directly as standalone files, not only as imported modules
- if OpenCV is installed without `aruco`, the detector falls back safely to the mock backend on development laptops
