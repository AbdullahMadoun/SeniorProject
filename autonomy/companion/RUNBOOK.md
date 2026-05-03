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
- [bootstrap_rpi_companion.sh](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/bootstrap_rpi_companion.sh)
- [requirements-rpi.txt](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/requirements-rpi.txt)
- [generate_checkerboard.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/generate_checkerboard.py)
- [generate_aruco_marker.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/generate_aruco_marker.py)
- [calibrate_camera.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/calibrate_camera.py)

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

## Raspberry Pi Bootstrap

Run on the Pi:

```bash
cd /path/to/SeniorProject/Skylink2/autonomy/companion
bash ./bootstrap_rpi_companion.sh
```

What it does:

- installs Pi-side apt packages
- creates `.venv-pi`
- installs [requirements-rpi.txt](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/requirements-rpi.txt)
- installs `opencv-contrib-python-headless`
- attempts non-interactive `raspi-config` enablement for `I2C` and hardware serial
- verifies imports for:
  - `pymavlink`
  - `board`
  - `busio`
  - `adafruit_ads1x15`
  - `cv2`

## Calibration Targets

Generate a printable checkerboard:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\generate_checkerboard.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\calibration_target
```

Generate an ArUco marker:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\generate_aruco_marker.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\marker_target --marker-id 0
```

Important:

- when [generate_aruco_marker.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/generate_aruco_marker.py) runs under the mock backend, metadata will mark the asset as `flight_ready = false`
- only markers generated from real OpenCV `aruco` support should be printed for real landing tests

## Camera Calibration Workflow

Template mode on a development laptop:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\calibrate_camera.py --image-glob "D:\captures\checkerboard\*.png" --output D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\camera_calibration.json --template-only
```

Real calibration mode on a machine with OpenCV chessboard support:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\calibrate_camera.py --image-glob "D:\captures\checkerboard\*.png" --output D:\downloads\SeniorProject\Skylink2\autonomy\companion\artifacts\camera_calibration.json
```

Then replace the placeholder intrinsics in [aruco_detector.py](/D:/downloads/SeniorProject/Skylink2/autonomy/companion/aruco_detector.py).

## Script-Level Validation

### Video Logger

Mock mode:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --max-frames 10
```

Core isolation example:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --cpu-core 1 --max-frames 10
```

If `psutil` or host CPU affinity support is unavailable, the logger prints an `[AFFINITY] warning ...` line and continues normally without pinning.

Real hardware mode (production path on the Pi):

The Pixhawk 4 connects over USB-CDC at `/dev/ttyACM0`. The MAVProxy
systemd service `mavproxy-skylink` (see
[deploy/companion/README.md](/deploy/companion/README.md)) owns that
serial port and forwards MAVLink to `udp:127.0.0.1:14551`, which is
already the default `--mavlink-target` for `video_logger.py`. So in
production you do not pass `--mavlink-target` at all — the default is
correct:

```bash
~/SeniorProject/autonomy/companion/.venv-pi/bin/python \
    ~/SeniorProject/autonomy/companion/video_logger.py \
    --camera-source 0
```

Alternative: direct UART (not currently used).

The pipeline is target-agnostic, so the older direct-UART path via
TELEM2 still works if `mavproxy-skylink` is disabled and
`/dev/ttyAMA0` is wired up:

```bash
python ~/SeniorProject/autonomy/companion/video_logger.py \
    --mavlink-target /dev/ttyAMA0 --mavlink-baud 57600 --camera-source 0
```

This path is preserved here for completeness; the production deployment
on this hardware is the USB-CDC + MAVProxy bridge above.

Outputs:

- `telemetry_log.csv`
- `summary.json`
- `latest_frame.jpg.npy` in mock mode

MJPEG stream mode for the Mega-Dashboard:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --stream --stream-host 127.0.0.1 --stream-port 5050 --stream-path /stream --max-frames 60
```

Expected dashboard source:

- `http://127.0.0.1:5050/stream`
- proxied through [mission_api.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/mission_api.py) at `/api/fpv/stream`

### ArUco Precision Landing

Mock mode:

```powershell
$env:SKYLINK_MOCK_ARUCO_DETECTION='1'
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\aruco_detector.py --mock-mavlink --mock-camera --max-frames 10
```

Real hardware mode example (production path: MAVProxy bridge on
`udp:127.0.0.1:14551`):

```bash
~/SeniorProject/autonomy/companion/.venv-pi/bin/python \
    ~/SeniorProject/autonomy/companion/aruco_detector.py \
    --mavlink-target udp:127.0.0.1:14551 --camera-source 0 \
    --marker-id 0 --marker-size-m 0.2
```

Alternative: direct UART (not currently used) — if `mavproxy-skylink`
is disabled and TELEM2 is wired:

```bash
python ~/SeniorProject/autonomy/companion/aruco_detector.py \
    --mavlink-target /dev/ttyAMA0 --camera-source 0 \
    --marker-id 0 --marker-size-m 0.2
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

Pi bootstrap syntax check from WSL:

```powershell
wsl bash -n /mnt/d/downloads/SeniorProject/Skylink2/autonomy/companion/bootstrap_rpi_companion.sh
```

Global regression boundary:

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

## Hardware Bring-Up Notes

- Production MAVLink target on the Pi is the MAVProxy systemd bridge:
  `mavproxy-skylink.service` reads `/dev/ttyACM0` (Pixhawk USB-CDC) and
  forwards to `udp:127.0.0.1:14551`, which is the default
  `--mavlink-target` for `video_logger.py`. See
  [deploy/companion/README.md](/deploy/companion/README.md) for setup.
  The older `/dev/ttyAMA0` / `/dev/serial0` (TELEM2 direct UART) path
  is preserved as an alternative but is not currently used.
- camera source should stay configurable because Gazebo, USB cameras, and Pi camera pipelines differ
- the companion scripts are designed to run directly as standalone files, not only as imported modules
- if OpenCV is installed without `aruco`, the detector falls back safely to the mock backend on development laptops
