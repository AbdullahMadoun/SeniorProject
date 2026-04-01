# Companion Hardware Layer

This package is the hardware-facing companion-computer layer for the drone system.

It is intentionally isolated from the dashboard and mission API. The goal is for the
same Python modules to run:

- on a Raspberry Pi with real GPIO, ADS1115, MAVLink UART, and USB cameras
- on a Windows laptop with mock GPIO, mock ADC readings, mock MAVLink, and mock camera frames

## Modules

- `mock_rpi.py`
  - automatic fallback for `RPi.GPIO`, `board`, `busio`, `adafruit_ads1x15`, and `cv2`
- `video_logger.py`
  - threaded MAVLink `GLOBAL_POSITION_INT` polling plus camera overlay and CSV logging
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

## Example Commands

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --max-frames 5
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\aruco_detector.py --mock-mavlink --mock-camera --max-frames 5
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\gpio_charging.py --cycles 1
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\yolo_pothole_detect.py --output-dir D:\downloads\SeniorProject\Skylink2\autonomy\companion\outputs\yolo
```
