---

## FILE 1 — CREATE: `autonomy/fixtures/sim_calibration.json`

This is the pinhole calibration for the synthetic 512×512 downward camera.
It must exist before any detector code is called. This also fixes the 2
failing companion tests.

```json
{
  "camera_matrix": [
    [400.0, 0.0, 256.0],
    [0.0, 400.0, 256.0],
    [0.0, 0.0, 1.0]
  ],
  "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
  "image_size": ,
  "note": "Synthetic sim calibration — not for real hardware"
}
```

---

## FILE 2 — CREATE: `autonomy/simulation/landing_pad.py`

This module is the heart of the visual realism. It renders what the
downward camera actually sees at any given altitude and lateral offset.
It must be importable with no side effects.

```python
"""
autonomy/simulation/landing_pad.py

Generates synthetic downward-camera framesr the precision landing sim.

Design decisions:
- Use cv2.aruco.GridBoard (3x3, DICT_5X5_100) — same as aruco_board_detector.py
- Perspective-project the board onto the camera plane given:
    altitude_m      : AGL, positive up
    offset_x_m      : drone lateral offset from pad center (NED East)
    offset_y_m      : drone lateral offset from pad center (NED North)
    attitude_roll   : radians
    attitude_pitch  : radians
- Apply realistic degradation:
    gaussian blur proportional to simulated motion (vel_xy_ms)
    random frame drop (returns None with probability drop_prob)
    salt-and-pepper noise at low altitude (dust simulation)
    brightness variation ±10%
- Return annotated frame with:
    green bounding box around each detected marker
    red crosshair at board centroid
    white text overlay: altitude, offset, confidence
"""

import cv2
import numpy as np
import random
from dataclasses import dataclass
from typing import Optional

ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
BOARD_PARAMS = cv2.aruco.DetectorParameters()

# Physical board dimensions (must match aruco_board_detector.py)
MARKER_LENGTH_M = 0.06
MARKER_SEP_M = 0.01
BOARD_COLS = 3
BOARD_ROWS = 3

# Camera intrinsics matching sim_calibration.json
CAM_FX = 400.0
CAM_FY = 400.0
CAM_CX = 256.0
CAM_CY = 256.0
IMG_W = 512
IMG_H = 512

K = np.array([[CAM_FX, 0, CAM_CX],
              [0, CAM_FY, CAM_CY],
              ], dtype=np.float64)[1]
DIST = np.zeros((5,), dtype=np.float64)


@dataclass
class PadRenderConfig:
    altitude_m: float = 5.0
    offset_x_m: float = 0.0   # east, positive = drone is east of pad
    offset_y_m: float = 0.0   # north
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    vel_xy_ms: float = 0.0
    drop_prob: float = 0.02    # 2% frame drop
    noise_enabled: bool = True


def _generate_board_image(size_px: int = 1024) -> np.ndarray:
    """Render a clean top-down image of the 3x3 ArUco board."""
    board = cv2.aruco.GridBoard(
        (BOARD_COLS, BOARD_ROWS),
        markerLength=MARKER_LENGTH_M,
        markerSeparation=MARKER_SEP_M,
        dictionary=ARUCO_DICT,
    )
    img = board.generateImage((size_px, size_px), marginSize=40, borderBits=1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


# Cache board image — expensive to regenerate each frame
_BOARD_IMG_CACHE: Optional[np.ndarray] = None


def _get_board_image() -> np.ndarray:
    global _BOARD_IMG_CACHE
    if _BOARD_IMG_CACHE is None:
        _BOARD_IMG_CACHE = _generate_board_image()
    return _BOARD_IMG_CACHE


def render_frame(cfg: PadRenderConfig) -> Optional[np.ndarray]:
    """
    Return a BGR camera frame (512x512) of what the downward camera sees.
    Returns None if this frame is dropped (simulated packet loss).
    """
    if cfg.drop_prob > 0 and random.random() < cfg.drop_prob:
        return None  # simulated frame drop

    board_img = _get_board_image().copy()
    h_src, w_src = board_img.shape[:2]

    # Physical board size in meters
    board_side_m = (BOARD_COLS * MARKER_LENGTH_M +
                    (BOARD_COLS - 1) * MARKER_SEP_M + 0.08)  # +margin

    # How many pixels of board fit in the camera view at this altitude
    # Using pin-hole: pixel_size = focal_length * physical_size / distance
    pixels_per_meter = CAM_FX / max(cfg.altitude_m, 0.05)
    board_px = int(board_side_m * pixels_per_meter)
    board_px = max(20, min(board_px, 1020))

    # Resize board to apparent size
    board_resized = cv2.resize(board_img, (board_px, board_px))

    # Canvas
    canvas = np.full((IMG_H, IMG_W, 3), 40, dtype=np.uint8)  # dark grey ground

    # Project lateral offset into pixel shift
    # offset_x_m > 0 means drone is east → pad appears to the LEFT in frame
    px_shift_x = int(-cfg.offset_x_m * pixels_per_meter)
    px_shift_y = int(-cfg.offset_y_m * pixels_per_meter)  # north = up in frame

    # Center pad on canvas with shift
    cx = IMG_W // 2 + px_shift_x - board_px // 2
    cy = IMG_H // 2 + px_shift_y - board_px // 2

    # Clip and paste
    src_x0 = max(0, -cx)
    src_y0 = max(0, -cy)
    dst_x0 = max(0, cx)
    dst_y0 = max(0, cy)
    src_x1 = min(board_px, IMG_W - cx)
    src_y1 = min(board_px, IMG_H - cy)
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)

    if src_x1 > src_x0 and src_y1 > src_y0:
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = board_resized[src_y0:src_y1, src_x0:src_x1]

    # Attitude tilt: apply small affine warp for roll/pitch
    if abs(cfg.roll_rad) > 0.01 or abs(cfg.pitch_rad) > 0.01:
        tilt_x = int(np.tan(cfg.pitch_rad) * CAM_FY)
        tilt_y = int(np.tan(cfg.roll_rad) * CAM_FX)
        M = np.float32([[1, 0, tilt_x], [0, 1, tilt_y]])
        canvas = cv2.warpAffine(canvas, M, (IMG_W, IMG_H))

    # Motion blur proportional to lateral velocity
    if cfg.noise_enabled and cfg.vel_xy_ms > 0.3:
        blur_k = min(15, int(cfg.vel_xy_ms * 3))
        blur_k = blur_k if blur_k % 2 == 1 else blur_k + 1
        kernel = np.zeros((blur_k, blur_k))
        kernel[blur_k // 2, :] = 1.0 / blur_k
        canvas = cv2.filter2D(canvas, -1, kernel)

    # Salt-and-pepper noise at low altitude (dust)
    if cfg.noise_enabled and cfg.altitude_m < 1.5:
        noise_density = 0.03 * (1.5 - cfg.altitude_m)
        num_px = int(noise_density * IMG_W * IMG_H)
        coords_y = np.random.randint(0, IMG_H, num_px)
        coords_x = np.random.randint(0, IMG_W, num_px)
        canvas[coords_y, coords_x] = 255

    # Brightness variation ±10%
    if cfg.noise_enabled:
        alpha = 0.9 + random.random() * 0.2
        canvas = np.clip(canvas.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    return canvas


def annotate_frame(frame: np.ndarray,
                   cfg: PadRenderConfig,
                   detection_result: dict) -> np.ndarray:
    """
    Draw visual overlays on the camera frame:
    - Green boxes around detected markers
    - Red crosshair at detected board centroid
    - Yellow dot at frame center (where drone wants to be)
    - White HUD text
    """
    out = frame.copy()

    # Yellow center reticle — where the drone needs to steer toward
    cv2.drawMarker(out, (IMG_W // 2, IMG_H // 2),
                   (0, 255, 255), cv2.MARKER_CROSS, 30, 2)

    if detection_result and detection_result.get("detected"):
        corners = detection_result.get("corners", [])
        for c in corners:
            pts = c.reshape((-1, 1, 2)).astype(np.int32)
            cv2.polylines(out, [pts], True, (0, 255, 0), 2)

        cx_det = detection_result.get("centroid_x_px", IMG_W // 2)
        cy_det = detection_result.get("centroid_y_px", IMG_H // 2)
        # Red crosshair on detected centroid
        cv2.drawMarker(out, (int(cx_det), int(cy_det)),
                       (0, 0, 255), cv2.MARKER_CROSS, 25, 3)
        # Line from center to detected centroid (shows offset magnitude)
        cv2.line(out, (IMG_W // 2, IMG_H // 2),
                 (int(cx_det), int(cy_det)), (0, 165, 255), 2)

    # HUD text block
    alt_str = f"ALT: {cfg.altitude_m:.2f} m"
    off_str = f"OFF: ({cfg.offset_x_m:.2f}, {cfg.offset_y_m:.2f}) m"
    det_str = ("DETECTED" if detection_result and detection_result.get("detected")
               else "SEARCHING...")
    det_color = (0, 255, 0) if det_str == "DETECTED" else (0, 100, 255)

    cv2.putText(out, alt_str, (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(out, off_str, (10, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(out, det_str, (10, 64),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, det_color, 2)

    return out
```

---

## FILE 3 — CREATE: `autonomy/companion/rpi_companion_sim.py`

This is the simulated Raspberry Pi process. It runs as a separate
`asyncio` program alongside SITL. It owns the camera loop, the detector,
the LANDING_TARGET publisher, and the MJPEG server.

```python
"""
autonomy/companion/rpi_companion_sim.py

Simulates the Raspberry Pi companion computer:
  - Reads drone altitude from shared state (updated by the recorder)
  - Generates synthetic camera frames via landing_pad.py
  - Runs ArucoBoardDetectorBackend on every frame
  - Publishes LANDING_TARGET MAVLink to PX4 at 10 Hz
  - Serves annotated MJPEG stream on http://0.0.0.0:8765/camera

Start with: python -m autonomy.companion.rpi_companion_sim

Shared state protocol:
  The recorder writes /tmp/drone_state.json at ~10 Hz:
  {
    "altitude_m": float,
    "offset_x_m": float,
    "offset_y_m": float,
    "roll_rad": float,
    "pitch_rad": float,
    "vel_xy_ms": float,
    "fsm_state": str
  }
  This avoids any IPC complexity — both processes just use the filesystem.
"""

import asyncio
import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import cv2
import numpy as np
from mavsdk import System
from mavsdk.telemetry import LandingTargetType

os.environ.setdefault(
    "SKYLINK_CAMERA_CALIBRATION",
    str(Path(__file__).parent.parent / "fixtures" / "sim_calibration.json")
)

from autonomy.companion.aruco_board_detector import ArucoBoardDetectorBackend
from autonomy.simulation.landing_pad import PadRenderConfig, render_frame, annotate_frame

STATE_FILE = Path("/tmp/drone_state.json")
COMPANION_MAVSDK_PORT = "udp://:14541"
MJPEG_PORT = 8765
CAMERA_HZ = 10

# Thread-safe latest annotated frame for MJPEG server
_latest_frame_lock = threading.Lock()
_latest_frame_jpg: bytes = b""


def _read_drone_state() -> PadRenderConfig:
    try:
        data = json.loads(STATE_FILE.read_text())
        return PadRenderConfig(
            altitude_m=float(data.get("altitude_m", 5.0)),
            offset_x_m=float(data.get("offset_x_m", 0.0)),
            offset_y_m=float(data.get("offset_y_m", 0.0)),
            roll_rad=float(data.get("roll_rad", 0.0)),
            pitch_rad=float(data.get("pitch_rad", 0.0)),
            vel_xy_ms=float(data.get("vel_xy_ms", 0.0)),
        )
    except Exception:
        return PadRenderConfig()


def _detection_to_landing_target(det: dict, cfg: PadRenderConfig):
    """
    Convert board detector output to LANDING_TARGET angle_x / angle_y.
    angle_x = arctan((centroid_x_px - CX) / FX)  in radians
    angle_y = arctan((centroid_y_px - CY) / FY)  in radians
    distance = altitude (rangefinder substitute)
    """
    import math
    FX, FY, CX, CY = 400.0, 400.0, 256.0, 256.0
    cx = det.get("centroid_x_px", CX)
    cy = det.get("centroid_y_px", CY)
    angle_x = math.atan2(cx - CX, FX)
    angle_y = math.atan2(cy - CY, FY)
    return angle_x, angle_y, cfg.altitude_m


# ── MJPEG HTTP server ────────────────────────────────────────────────────────

class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence access logs

    def do_GET(self):
        if self.path != "/camera":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with _latest_frame_lock:
                    jpg = _latest_frame_jpg
                if jpg:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
                time.sleep(1.0 / CAMERA_HZ)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _start_mjpeg_server():
    server = HTTPServer(("0.0.0.0", MJPEG_PORT), MJPEGHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[companion] MJPEG stream at http://localhost:{MJPEG_PORT}/camera")


# ── Main async loop ──────────────────────────────────────────────────────────

async def run_companion():
    global _latest_frame_jpg

    _start_mjpeg_server()

    drone = System()
    await drone.connect(system_address=COMPANION_MAVSDK_PORT)
    print("[companion] waiting for PX4 connection...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("[companion] connected to PX4")
            break

    detector = ArucoBoardDetectorBackend()
    interval = 1.0 / CAMERA_HZ

    print("[companion] camera loop running")
    while True:
        t0 = time.monotonic()
        cfg = _read_drone_state()

        # Render synthetic camera frame
        frame = render_frame(cfg)

        if frame is None:
            # Simulated frame drop — do not publish LANDING_TARGET
            await asyncio.sleep(interval)
            continue

        # Run board detector
        detection = detector.detect(frame)
        det_dict = {}
        if detection is not None:
            det_dict = {
                "detected": True,
                "centroid_x_px": detection.centroid_x_px,
                "centroid_y_px": detection.centroid_y_px,
                "corners": detection.corners,
            }
            # Send LANDING_TARGET to PX4
            angle_x, angle_y, dist = _detection_to_landing_target(det_dict, cfg)
            try:
                await drone.telemetry.set_rate_landing_target(CAMERA_HZ)
                # Use raw MAVLink send — MAVSDK wrapper for LANDING_TARGET
                from autonomy.drone_system.precision_landing_px4 import (
                    send_landing_target_mavlink,
                )
                await send_landing_target_mavlink(
                    drone, angle_x, angle_y, dist
                )
            except Exception as e:
                print(f"[companion] LANDING_TARGET send error: {e}")
        else:
            det_dict = {"detected": False}

        # Annotate frame and push to MJPEG buffer
        annotated = annotate_frame(frame, cfg, det_dict)
        _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with _latest_frame_lock:
            _latest_frame_jpg = buf.tobytes()

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0, interval - elapsed))


if __name__ == "__main__":
    asyncio.run(run_companion())
```

---

## FILE 4 — EDIT: `autonomy/drone_system/precision_landing_px4.py`

Find the existing `configure_px4_precision_landing()` function (or create it
if missing). Replace/extend it with the full parameter block below.
Also add `send_landing_target_mavlink()` if it does not already exist.

```python
# autonomy/drone_system/precision_landing_px4.py
# ADD/REPLACE these two functions — do not touch anything else in the file

PLD_PARAMS = {
    # Precision landing tuning
    "PLD_HACC_RAD":   0.3,    # horizontal acceptance radius [m]
    "PLD_FAPPR_ALT":  0.8,    # altitude to start precision landing [m AGL]
    "PLD_BTOUT":      5.0,    # target lost timeout before abort [s]
    "PLD_MAX_SRCH":   2,      # max search attempts before abort
    # RTL integration
    "RTL_PLD_MD":     2,      # 0=disabled 1=opportunistic 2=required
    "RTL_RETURN_ALT": 15.0,   # safe RTL climb altitude [m]
    "RTL_DESCEND_ALT": 5.0,   # loiter altitude before final descent [m]
    "RTL_LAND_DELAY":  0.0,   # no loiter hover before landing
    # Final descent speed
    "MPC_LAND_SPEED": 0.4,    # m/s — slow and controlled
    "MPC_LAND_ALT1":  5.0,    # start slowing at 5m
    "MPC_LAND_ALT2":  1.0,    # reach MPC_LAND_SPEED at 1m
    # EKF2 — accept landing target as position aid
    "EKF2_AID_MASK":  321,    # GPS + optical flow + landing target
}


async def configure_px4_precision_landing(drone) -> None:
    """
    Push all PLD/RTL/MPC params to PX4 at SITL connect.
    Call this once after connection is established.
    """
    for param, val in PLD_PARAMS.items():
        try:
            await drone.param.set_param_float(param, float(val))
            print(f"[px4_cfg] {param} = {val}")
        except Exception as e:
            print(f"[px4_cfg] WARNING: could not set {param}: {e}")


async def send_landing_target_mavlink(drone, angle_x: float,
                                       angle_y: float,
                                       distance: float) -> None:
    """
    Send a LANDING_TARGET MAVLink message to PX4.
    angle_x, angle_y: radians (from camera center)
    distance: AGL in meters (rangefinder substitute)

    PX4 interprets angle_x as lateral error, angle_y as longitudinal error.
    Sign convention: positive angle_x = target is to the right of camera center.
    """
    import time
    from mavsdk.mocap import Quaternion

    # MAVSDK does not expose LANDING_TARGET directly —
    # use the passthrough mavlink method
    msg = drone._system_address  # just to confirm connection

    # Build raw MAVLink LANDING_TARGET (#149)
    # Fields: time_usec, target_num, frame, angle_x, angle_y, distance,
    #         size_x, size_y, x, y, z, q, type, position_valid
    await drone.mavlink.send_mavlink_passthrough(
        component_id=1,
        message_id=149,
        payload=_pack_landing_target(angle_x, angle_y, distance),
    )


def _pack_landing_target(angle_x: float, angle_y: float,
                          distance: float) -> bytes:
    import struct, time
    time_usec = int(time.time() * 1e6)
    target_num = 0
    frame = 8          # MAV_FRAME_BODY_NED
    size_x = 0.0
    size_y = 0.0
    x = 0.0
    y = 0.0
    z = distance
    q = [1.0, 0.0, 0.0, 0.0]  # identity quaternion
    type_ = 1          # LANDING_TARGET_TYPE_LIGHT_BEACON
    position_valid = 0

    return struct.pack(
        "<QBBffffff4fBB",
        time_usec, target_num, frame,
        angle_x, angle_y, distance, size_x, size_y,
        x, y, z,
        *q,
        type_, position_valid,
    )
```

---

## FILE 5 — EDIT: `autonomy/scripts/record_px4_landing_demo.py`

This is the most invasive edit. Make these changes in order:

### 5a — Remove these imports/calls at the top:
```python
# DELETE: from autonomy.drone_system.landing_target_projection import build_visibility_observation
# DELETE: dock_north_m = 1.25
# DELETE: dock_east_m = -0.75
```

### 5b — Add these imports:
```python
import json
import pathlib
import time
from autonomy.drone_system.precision_landing_px4 import configure_px4_precision_landing
```

### 5c — After `await drone.connect(...)` and before takeoff, add:
```python
await configure_px4_precision_landing(drone)
print("[recorder] PX4 precision landing params set")
```

### 5d — Replace the entire `build_visibility_observation()` call and offboard
velocity loop with this shared-state writer:

```python
# ── Shared state writer for companion sim ────────────────────────────────
STATE_FILE = pathlib.Path("/tmp/drone_state.json")

async def write_drone_state(drone, fsm_state: str):
    """Write current drone state for rpi_companion_sim.py to read."""
    try:
        async for pos in drone.telemetry.position_velocity_ned():
            north = pos.position.north_m
            east = pos.position.east_m
            down = pos.position.down_m
            altitude_m = -down
            vn = pos.velocity.north_m_s
            ve = pos.velocity.east_m_s
            vel_xy = (vn**2 + ve**2) ** 0.5
            break
        async for att in drone.telemetry.attitude_euler():
            roll = att.roll_deg * 3.14159 / 180.0
            pitch = att.pitch_deg * 3.14159 / 180.0
            break
        # offset = drone position relative to dock (pad is at origin 0,0)
        offset_x_m = east   # dock is at local NED origin
        offset_y_m = north
        STATE_FILE.write_text(json.dumps({
            "altitude_m": altitude_m,
            "offset_x_m": offset_x_m,
            "offset_y_m": offset_y_m,
            "roll_rad": roll,
            "pitch_rad": pitch,
            "vel_xy_ms": vel_xy,
            "fsm_state": fsm_state,
        }))
    except Exception:
        pass
```

### 5e — In the main flight loop, replace the offboard velocity section:

Find where the code currently calls `set_velocity_ned()` or uses the FSM
output to compute velocity commands. Replace that entire block with:

```python
# Write state for companion sim (companion handles LANDING_TARGET publishing)
await write_drone_state(drone, fsm.state)

# Once FSM enters DESCEND, stop offboard and let PX4 precision land
if fsm.state in ("DESCEND", "FLARE"):
    # Switch out of offboard — PX4 now flies on LANDING_TARGET input
    try:
        await drone.offboard.stop()
    except Exception:
        pass
    # Do NOT call drone.action.land() here.
    # PX4 will land on its own via precision landing once it gets
    # LANDING_TARGET messages from rpi_companion_sim.py
    await asyncio.sleep(0.1)
    continue

if fsm.state == "TOUCHDOWN":
    print("[recorder] touchdown confirmed — stopping recording")
    break

if fsm.state == "ABORT":
    print("[recorder] FSM aborted — triggering RTL")
    await drone.action.return_to_launch()
    break
```

### 5f — Trajectory recording: extend the per-frame dict in
`landing_trajectory.json` to include:

```python
frame_record = {
    "t": time.time(),
    "x": east,
    "y": north,
    "z": altitude_m,
    "fsm_state": fsm.state,
    "detection_confidence": 0.0,   # companion will fill this in future
    "marker_offset_x": 0.0,
    "marker_offset_y": 0.0,
}
trajectory_frames.append(frame_record)
```

### 5g — After the flight loop ends, replace the existing sync block
(the one that only works if HTML already exists) with:

```python
# ── Write trajectory JSON ────────────────────────────────────────────────
output_dir = pathlib.Path("artifacts/demo")
output_dir.mkdir(parents=True, exist_ok=True)
traj_path = output_dir / "landing_trajectory.json"
traj_path.write_text(json.dumps({"frames": trajectory_frames}, indent=2))
print(f"[recorder] trajectory written: {traj_path}")

# ── Build 3D HTML demo ───────────────────────────────────────────────────
from autonomy.scripts.build_demo_html import build_demo_html
build_demo_html(traj_path, output_dir / "precision_landing_3d_demo.html")
print(f"[recorder] demo HTML written: {output_dir}/precision_landing_3d_demo.html")
```

---

## FILE 6 — CREATE: `autonomy/scripts/build_demo_html.py`

This script builds the self-contained Three.js 3D visualization.
It is called by the recorder and can also be run standalone:
  `python -m autonomy.scripts.build_demo_html`

```python
"""
autonomy/scripts/build_demo_html.py

Builds artifacts/demo/precision_landing_3d_demo.html from
artifacts/demo/landing_trajectory.json.

The HTML file is fully self-contained (no CDN dependency except Three.js
loaded from a reliable version-pinned URL). It runs offline after first load.

3D Scene contents:
  - Sky: hemisphere light (blue sky / grey ground ambient)
  - Ground plane: 20m x 20m, dark grey
  - Landing pad: 0.5m x 0.5m flat plane with ArUco board texture (embedded PNG)
  - Drone mesh: orange box 0.3m x 0.3m x 0.1m with 4 arm stubs
  - Flight path: tube geometry colored by FSM state
  - Camera frustum cone: green wireframe cone below drone, narrows with altitude
  - Target ray: red dashed line from cone tip to pad center when DESCEND/FLARE
  - Altitude indicator: vertical white line from drone to ground with label
  - HUD panel (HTML overlay): FSM state, altitude, offset, detection status
  - Timeline scrubber (HTML input range) to replay trajectory
  - Play/Pause button
"""

import json
import pathlib
import base64
import io
import numpy as np

# Embed a tiny ArUco board PNG into the HTML as base64
# so the texture works even when served from file://
def _generate_board_b64() -> str:
    try:
        import cv2
        ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
        board = cv2.aruco.GridBoard(
            (3, 3), markerLength=0.06, markerSeparation=0.01,
            dictionary=ARUCO_DICT
        )
        img = board.generateImage((256, 256), marginSize=20, borderBits=1)
        _, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return ""


FSM_COLORS = {
    "SEARCH":     "#4488ff",   # blue
    "ALIGN":      "#ffcc00",   # yellow
    "DESCEND":    "#ff8800",   # orange
    "FLARE":      "#ff3300",   # red-orange
    "TOUCHDOWN":  "#00ff88",   # green
    "ABORT":      "#ff0055",   # red
    "UNKNOWN":    "#aaaaaa",
}


def build_demo_html(traj_json_path: pathlib.Path,
                    output_html_path: pathlib.Path) -> None:
    traj = json.loads(traj_json_path.read_text())
    frames = traj.get("frames", [])
    board_b64 = _generate_board_b64()

    # Serialize trajectory for JS
    frames_js = json.dumps(frames)

    # FSM color map for JS
    fsm_colors_js = json.dumps(FSM_COLORS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Precision Landing 3D Demo</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a0f; font-family: 'Courier New', monospace; color:#eee; overflow:hidden; }}
  #canvas-container {{ position:absolute; width:100%; height:100%; }}
  #hud {{
    position:absolute; top:16px; left:16px;
    background:rgba(0,0,0,0.65); border:1px solid #333;
    border-radius:8px; padding:14px 18px; min-width:220px;
    font-size:13px; line-height:1.7;
  }}
  #hud .label {{ color:#888; font-size:11px; text-transform:uppercase; letter-spacing:1px; }}
  #hud .value {{ color:#fff; font-weight:bold; }}
  #hud .fsm   {{ font-size:16px; font-weight:bold; padding:4px 0; }}
  #camera-panel {{
    position:absolute; top:16px; right:16px;
    width:220px;
    background:rgba(0,0,0,0.7); border:1px solid #333;
    border-radius:8px; overflow:hidden;
  }}
  #camera-panel .cam-label {{
    padding:6px 10px; font-size:11px; color:#888;
    text-transform:uppercase; letter-spacing:1px;
    border-bottom:1px solid #222;
  }}
  #camera-canvas {{ width:220px; height:220px; display:block; }}
  #timeline-bar {{
    position:absolute; bottom:24px; left:50%; transform:translateX(-50%);
    width:60%; background:rgba(0,0,0,0.65); border:1px solid #333;
    border-radius:8px; padding:10px 18px;
    display:flex; align-items:center; gap:12px;
  }}
  #scrubber {{ flex:1; accent-color:#4488ff; }}
  #play-btn {{
    background:#4488ff; color:#fff; border:none;
    border-radius:5px; padding:5px 14px; cursor:pointer;
    font-family:inherit; font-size:13px;
  }}
  #legend {{
    position:absolute; bottom:24px; right:16px;
    background:rgba(0,0,0,0.65); border:1px solid #333;
    border-radius:8px; padding:10px 14px; font-size:12px;
  }}
  .leg-item {{ display:flex; align-items:center; gap:8px; margin:3px 0; }}
  .leg-dot {{ width:12px; height:12px; border-radius:50%; flex-shrink:0; }}
</style>
</head>
<body>
<div id="canvas-container"></div>

<div id="hud">
  <div class="label">FSM State</div>
  <div class="fsm" id="hud-fsm">—</div>
  <div class="label">Altitude</div>
  <div class="value" id="hud-alt">— m</div>
  <div class="label">Offset (E, N)</div>
  <div class="value" id="hud-offset">— m</div>
  <div class="label">Frame</div>
  <div class="value" id="hud-frame">0 / {len(frames)}</div>
</div>

<div id="camera-panel">
  <div class="cam-label">📷 Downward Camera</div>
  <canvas id="camera-canvas" width="220" height="220"></canvas>
</div>

<div id="timeline-bar">
  <button id="play-btn">▶ Play</button>
  <input id="scrubber" type="range" min="0" max="{max(len(frames)-1,1)}" value="0" step="1"/>
</div>

<div id="legend">
  {''.join(f'<div class="leg-item"><div class="leg-dot" style="background:{c}"></div>{s}</div>' for s,c in FSM_COLORS.items())}
</div>

<script type="importmap">
  {{"imports": {{"three": "https://cdn.jsdelivr.net/npm/three@0.163.0/build/three.module.js",
               "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.163.0/examples/jsm/"}}}}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

// ── Data ────────────────────────────────────────────────────────────────────
const FRAMES = {frames_js};
const FSM_COLORS = {fsm_colors_js};
const BOARD_B64 = "{board_b64}";

// ── Renderer ─────────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
document.getElementById('canvas-container').appendChild(renderer.domElement);

// ── Scene ────────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = new THREE.Fog(0x0d1117, 30, 80);

// ── Camera ───────────────────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(55, window.innerWidth/window.innerHeight, 0.1, 200);
camera.position.set(8, 6, 8);
camera.lookAt(0, 0, 0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;

// ── Lighting ─────────────────────────────────────────────────────────────────
scene.add(new THREE.HemisphereLight(0x87ceeb, 0x3a3a3a, 0.9));
const sun = new THREE.DirectionalLight(0xfff0e0, 1.2);
sun.position.set(10, 20, 10);
sun.castShadow = true;
scene.add(sun);

// ── Ground plane ─────────────────────────────────────────────────────────────
const groundGeo = new THREE.PlaneGeometry(40, 40, 20, 20);
const groundMat = new THREE.MeshLambertMaterial({{ color: 0x1a1a2e, wireframe: false }});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// Grid
const grid = new THREE.GridHelper(40, 40, 0x222244, 0x222244);
scene.add(grid);

// ── Landing pad (ArUco board texture) ─────────────────────────────────────────
const padGeo = new THREE.PlaneGeometry(0.7, 0.7);
let padMat;
if (BOARD_B64) {{
  const img = new Image();
  img.src = 'data:image/png;base64,' + BOARD_B64;
  const tex = new THREE.Texture(img);
  img.onload = () => {{ tex.needsUpdate = true; }};
  padMat = new THREE.MeshBasicMaterial({{ map: tex, side: THREE.DoubleSide }});
}} else {{
  padMat = new THREE.MeshBasicMaterial({{ color: 0xffffff }});
}}
const pad = new THREE.Mesh(padGeo, padMat);
pad.rotation.x = -Math.PI / 2;
pad.position.y = 0.01;
scene.add(pad);

// Pad glow ring
const ringGeo = new THREE.RingGeometry(0.4, 0.46, 32);
const ringMat = new THREE.MeshBasicMaterial({{ color: 0x00ff88, side: THREE.DoubleSide }});
const ring = new THREE.Mesh(ringGeo, ringMat);
ring.rotation.x = -Math.PI / 2;
ring.position.y = 0.015;
scene.add(ring);

// ── Drone mesh ────────────────────────────────────────────────────────────────
const droneGroup = new THREE.Group();

// Body
const bodyGeo = new THREE.BoxGeometry(0.28, 0.07, 0.28);
const bodyMat = new THREE.MeshPhongMaterial({{ color: 0xff6600, shininess: 80 }});
droneGroup.add(new THREE.Mesh(bodyGeo, bodyMat));

// Arms (4 motor stubs)
const armGeo = new THREE.CylinderGeometry(0.012, 0.012, 0.22);
const armMat = new THREE.MeshPhongMaterial({{ color: 0x333333 }});
[[-1,-1],[1,-1],[-1,1],].forEach(([sx,sz]) => {{[1]
  const arm = new THREE.Mesh(armGeo, armMat);
  arm.rotation.z = Math.PI / 2;
  arm.position.set(sx*0.17, 0, sz*0.17);
  arm.rotation.x = Math.PI/4;
  arm.rotation.z = Math.atan2(sx, sz);
  droneGroup.add(arm);
  // Motor disk
  const diskGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.01, 16);
  const diskMat = new THREE.MeshPhongMaterial({{ color: 0x111111 }});
  const disk = new THREE.Mesh(diskGeo, diskMat);
  disk.position.set(sx*0.20, 0, sz*0.20);
  droneGroup.add(disk);
}});
scene.add(droneGroup);

// ── Camera frustum cone ───────────────────────────────────────────────────────
const coneMat = new THREE.MeshBasicMaterial({{
  color: 0x00ff88, wireframe: true, transparent: true, opacity: 0.5
}});
let coneRadius = 0.3;
let coneMesh = null;

function updateCone(altitude) {{
  if (coneMesh) scene.remove(coneMesh);
  coneRadius = Math.min(0.8, altitude * 0.15);
  const coneGeo = new THREE.ConeGeometry(coneRadius, altitude, 16, 1, true);
  coneMesh = new THREE.Mesh(coneGeo, coneMat);
  coneMesh.position.copy(droneGroup.position);
  coneMesh.position.y -= altitude / 2;
  scene.add(coneMesh);
}}

// ── Target ray (red line when DESCEND/FLARE) ──────────────────────────────────
const rayMat = new THREE.LineBasicMaterial({{ color: 0xff2200, linewidth: 2 }});
let rayLine = null;

function updateRay(dronePos, fsmState) {{
  if (rayLine) scene.remove(rayLine);
  if (!['DESCEND','FLARE'].includes(fsmState)) return;
  const pts = [dronePos.clone(), new THREE.Vector3(0, 0.01, 0)];
  const rayGeo = new THREE.BufferGeometry().setFromPoints(pts);
  rayLine = new THREE.Line(rayGeo, rayMat);
  scene.add(rayLine);
}}

// ── Altitude vertical indicator ───────────────────────────────────────────────
const altLineMat = new THREE.LineBasicMaterial({{ color: 0xffffff, transparent: true, opacity: 0.3 }});
let altLine = null;

function updateAltLine(dronePos) {{
  if (altLine) scene.remove(altLine);
  const pts = [dronePos.clone(), new THREE.Vector3(dronePos.x, 0, dronePos.z)];
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  altLine = new THREE.Line(g, altLineMat);
  scene.add(altLine);
}}

// ── Flight path tube ──────────────────────────────────────────────────────────
// Build colored segments grouped by FSM state
function buildFlightPath(upToFrame) {{
  // Remove existing path objects tagged with userData.flightPath
  scene.children.filter(c => c.userData.flightPath).forEach(c => scene.remove(c));
  if (upToFrame < 2) return;

  let segStart = 0;
  for (let i = 1; i <= upToFrame; i++) {{
    const stateChanged = i === upToFrame ||
      FRAMES[i].fsm_state !== FRAMES[segStart].fsm_state;
    if (stateChanged) {{
      const pts = [];
      for (let j = segStart; j <= i; j++) {{
        const f = FRAMES[j];
        pts.push(new THREE.Vector3(f.x || 0, f.z || 0, -(f.y || 0)));
      }}
      const color = FSM_COLORS[FRAMES[segStart].fsm_state] || '#aaaaaa';
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.LineBasicMaterial({{ color }});
      const line = new THREE.Line(geo, mat);
      line.userData.flightPath = true;
      scene.add(line);
      segStart = i;
    }}
  }}
}}

// ── Camera canvas (simulated downward view) ───────────────────────────────────
const camCanvas = document.getElementById('camera-canvas');
const camCtx = camCanvas.getContext('2d');

function drawCameraView(frame, detected) {{
  const W = 220, H = 220;
  camCtx.fillStyle = '#262626';
  camCtx.fillRect(0, 0, W, H);

  const alt = frame.z || 1;
  const scale = Math.min(1.0, 6.0 / Math.max(alt, 0.1));
  const padSize = Math.floor(scale * 180);
  const ox = Math.round(-(frame.x || 0) * 400 / Math.max(alt, 0.1));
  const oy = Math.round(-(frame.y || 0) * 400 / Math.max(alt, 0.1));

  // Draw pad square
  camCtx.fillStyle = '#ffffff';
  const px = W/2 - padSize/2 + ox;
  const py = H/2 - padSize/2 + oy;
  camCtx.fillRect(px, py, padSize, padSize);

  // Draw ArUco grid lines
  if (padSize > 30) {{
    camCtx.strokeStyle = '#000000';
    camCtx.lineWidth = 1;
    for (let i = 1; i < 3; i++) {{
      const x = px + (padSize/3)*i;
      const y = py + (padSize/3)*i;
      camCtx.beginPath(); camCtx.moveTo(x,py); camCtx.lineTo(x,py+padSize); camCtx.stroke();
      camCtx.beginPath(); camCtx.moveTo(px,y); camCtx.lineTo(px+padSize,y); camCtx.stroke();
    }}
    // Inner black squares (simplified ArUco look)
    for (let r=0;r<3;r++) for (let c=0;c<3;c++) {{
      if ((r+c)%2===0) {{
        camCtx.fillStyle='#000';
        const cx2 = px + c*(padSize/3) + padSize/12;
        const cy2 = py + r*(padSize/3) + padSize/12;
        camCtx.fillRect(cx2, cy2, padSize/6, padSize/6);
      }}
    }}
  }}

  // Center reticle (yellow cross — where drone wants to be)
  camCtx.strokeStyle = '#ffff00';
  camCtx.lineWidth = 2;
  camCtx.beginPath(); camCtx.moveTo(W/2-15,H/2); camCtx.lineTo(W/2+15,H/2); camCtx.stroke();
  camCtx.beginPath(); camCtx.moveTo(W/2,H/2-15); camCtx.lineTo(W/2,H/2+15); camCtx.stroke();

  // Detected centroid (red cross)
  if (detected) {{
    const cx2 = W/2 + ox, cy2 = H/2 + oy;
    camCtx.strokeStyle = '#ff2200';
    camCtx.lineWidth = 3;
    camCtx.beginPath(); camCtx.moveTo(cx2-12,cy2); camCtx.lineTo(cx2+12,cy2); camCtx.stroke();
    camCtx.beginPath(); camCtx.moveTo(cx2,cy2-12); camCtx.lineTo(cx2,cy2+12); camCtx.stroke();
    // Line from center to detected
    camCtx.strokeStyle = '#ff8800';
    camCtx.lineWidth = 1.5;
    camCtx.beginPath(); camCtx.moveTo(W/2,H/2); camCtx.lineTo(cx2,cy2); camCtx.stroke();
  }}

  // HUD text
  camCtx.fillStyle = 'rgba(0,0,0,0.5)';
  camCtx.fillRect(0, H-42, W, 42);
  camCtx.fillStyle = detected ? '#00ff88' : '#ff8844';
  camCtx.font = 'bold 12px Courier New';
  camCtx.fillText(detected ? '● DETECTED' : '○ SEARCHING', 8, H-24);
  camCtx.fillStyle = '#aaa';
  camCtx.font = '11px Courier New';
  camCtx.fillText(`ALT: ${{alt.toFixed(2)}}m  OFF: (${{(frame.x||0).toFixed(2)}}, ${{(frame.y||0).toFixed(2)}})`, 8, H-8);
}}

// ── Animation state ───────────────────────────────────────────────────────────
let currentFrame = 0;
let playing = false;
let lastFrameTime = 0;
const FPS = 10;

const scrubber = document.getElementById('scrubber');
const playBtn = document.getElementById('play-btn');

playBtn.addEventListener('click', () => {{
  playing = !playing;
  playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing && currentFrame >= FRAMES.length - 1) currentFrame = 0;
}});

scrubber.addEventListener('input', () => {{
  currentFrame = parseInt(scrubber.value);
  renderFrame(currentFrame);
}});

function renderFrame(idx) {{
  if (!FRAMES.length) return;
  const f = FRAMES[Math.min(idx, FRAMES.length-1)];

  // Drone position (Three.js: Y=up, X=east, Z=-north)
  const x = f.x || 0;
  const y = f.z || 0;
  const z = -(f.y || 0);
  droneGroup.position.set(x, y, z);

  const fsm = f.fsm_state || 'UNKNOWN';
  const alt = f.z || 0;
  const detected = ['ALIGN','DESCEND','FLARE','TOUCHDOWN'].includes(fsm);

  updateCone(alt);
  updateRay(droneGroup.position, fsm);
  updateAltLine(droneGroup.position);
  buildFlightPath(idx);

  // HUD
  const color = FSM_COLORS[fsm] || '#aaa';
  const hudFsm = document.getElementById('hud-fsm');
  hudFsm.textContent = fsm;
  hudFsm.style.color = color;
  document.getElementById('hud-alt').textContent = alt.toFixed(2) + ' m';
  document.getElementById('hud-offset').textContent =
    `(${{(f.x||0).toFixed(2)}}, ${{(f.y||0).toFixed(2)}}) m`;
  document.getElementById('hud-frame').textContent =
    `${{idx+1}} / ${{FRAMES.length}}`;

  // Camera canvas
  drawCameraView(f, detected);
  scrubber.value = idx;
}}

// ── Render loop ───────────────────────────────────────────────────────────────
function animate(ts) {{
  requestAnimationFrame(animate);
  controls.update();

  if (playing && ts - lastFrameTime > 1000/FPS) {{
    lastFrameTime = ts;
    if (currentFrame < FRAMES.length - 1) {{
      currentFrame++;
      renderFrame(currentFrame);
    }} else {{
      playing = false;
      playBtn.textContent = '▶ Play';
    }}
  }}

  renderer.render(scene, camera);
}}

// Init
if (FRAMES.length) renderFrame(0);
animate(0);

window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
</body>
</html>"""

    output_html_path.write_text(html)


if __name__ == "__main__":
    traj = pathlib.Path("artifacts/demo/landing_trajectory.json")
    out = pathlib.Path("artifacts/demo/precision_landing_3d_demo.html")
    build_demo_html(traj, out)
    print(f"Written: {out}")
```

---

## FILE 7 — CREATE: `dashboard/app.py`

```python
"""
dashboard/app.py

Operator dashboard:
  - 3D map with clickable GPS waypoint dropper
  - Mission upload to PX4 SITL
  - Live telemetry stream
  - RTL button
  - Live camera feed from rpi_companion_sim (MJPEG proxy)

Run: python dashboard/app.py
Open: http://localhost:5000
"""

import asyncio
import threading
import json
import requests
from flask import Flask, render_template, Response, stream_with_context
from flask_socketio import SocketIO
from mavsdk import System
from mavsdk.mission_raw import MissionItem, MissionRawError

app = Flask(__name__, template_folder="templates")
sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

drone = System()
_loop = asyncio.new_event_loop()
_drone_connected = False


def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

threading.Thread(target=_run_loop, daemon=True).start()


def run_async(coro):
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=15)


@app.before_first_request
def connect_drone():
    global _drone_connected
    async def _connect():
        await drone.connect(system_address="udp://:14540")
        async for state in drone.core.connection_state():
            if state.is_connected:
                return
    run_async(_connect())
    _drone_connected = True
    threading.Thread(target=_telemetry_loop, daemon=True).start()


def _telemetry_loop():
    async def _stream():
        async for pos in drone.telemetry.position():
            sio.emit("telemetry", {
                "lat": pos.latitude_deg,
                "lon": pos.longitude_deg,
                "alt": pos.absolute_altitude_m,
                "rel_alt": pos.relative_altitude_m,
            })
            await asyncio.sleep(0.2)
    asyncio.run_coroutine_threadsafe(_stream(), _loop)


@sio.on("upload_mission")
def handle_upload_mission(data):
    """data = {"waypoints": [{lat, lon, alt}, ...]}"""
    wps = data.get("waypoints", [])
    if not wps:
        sio.emit("mission_status", {"ok": False, "msg": "No waypoints"})
        return

    async def _upload():
        items = []
        # Home (current position)
        items.append(MissionItem(
            seq=0, frame=6, command=16,
            current=1, autocontinue=1,
            param1=0, param2=0, param3=0, param4=float('nan'),
            x=int(wps['lat'] * 1e7),
            y=int(wps['lon'] * 1e7),
            z=float(wps.get('alt', 15)),
            mission_type=0
        ))
        for i, wp in enumerate(wps):
            items.append(MissionItem(
                seq=i+1, frame=3, command=16,
                current=0, autocontinue=1,
                param1=0, param2=0, param3=0, param4=float('nan'),
                x=int(wp['lat'] * 1e7),
                y=int(wp['lon'] * 1e7),
                z=float(wp.get('alt', 15)),
                mission_type=0
            ))
        # Final: RTL
        items.append(MissionItem(
            seq=len(wps)+1, frame=2, command=20,
            current=0, autocontinue=1,
            param1=0, param2=0, param3=0, param4=0,
            x=0, y=0, z=0, mission_type=0
        ))
        try:
            await drone.mission_raw.upload_mission(items)
            await drone.action.arm()
            await drone.mission_raw.start_mission()
            return {"ok": True, "msg": f"Mission uploaded: {len(wps)} waypoints"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    result = run_async(_upload())
    sio.emit("mission_status", result)


@sio.on("rtl")
def handle_rtl():
    async def _rtl():
        await drone.action.return_to_launch()
    run_async(_rtl())
    sio.emit("mission_status", {"ok": True, "msg": "RTL commanded"})


@app.route("/camera_feed")
def camera_feed():
    """Proxy the MJPEG stream from rpi_companion_sim."""
    def generate():
        try:
            r = requests.get("http://localhost:8765/camera", stream=True, timeout=5)
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk
        except Exception:
            yield b""
    return Response(stream_with_context(generate()),
                    content_type="multipart/x-mixed-replace; boundary=frame")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    sio.run(app, host="0.0.0.0", port=5000, debug=False)
```

---

## FILE 8 — CREATE: `dashboard/templates/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Drone Mission Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0d1117; color:#eee; font-family:'Courier New',monospace;
         display:flex; height:100vh; }
  #sidebar {
    width:300px; flex-shrink:0;
    background:#161b22; border-right:1px solid #30363d;
    display:flex; flex-direction:column; padding:16px; gap:14px;
    overflow-y:auto;
  }
  #sidebar h2 { color:#58a6ff; font-size:15px; letter-spacing:1px; }
  .card {
    background:#0d1117; border:1px solid #30363d;
    border-radius:6px; padding:12px;
  }
  .card h3 { color:#8b949e; font-size:11px; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:8px; }
  .btn {
    width:100%; padding:8px; border-radius:5px; border:none;
    cursor:pointer; font-family:inherit; font-size:13px; font-weight:bold;
    margin-bottom:6px;
  }
  .btn-primary { background:#238636; color:#fff; }
  .btn-danger  { background:#da3633; color:#fff; }
  .btn-warn    { background:#9e6a03; color:#fff; }
  .btn:hover { filter:brightness(1.2); }
  #wp-list { list-style:none; font-size:12px; }
  #wp-list li {
    padding:4px 6px; border-bottom:1px solid #21262d;
    display:flex; justify-content:space-between;
  }
  #wp-list li button {
    background:none; border:none; color:#f85149;
    cursor:pointer; font-size:11px;
  }
  .telem-row { display:flex; justify-content:space-between;
               font-size:12px; padding:2px 0; }
  .telem-val { color:#58a6ff; font-weight:bold; }
  #status-msg {
    font-size:12px; padding:6px; border-radius:4px;
    background:#21262d; color:#8b949e; min-height:32px;
  }
  #map-area { flex:1; display:flex; flex-direction:column; }
  #map { flex:1; }
  #camera-strip {
    height:180px; background:#000;
    display:flex; align-items:center; justify-content:center;
    border-top:1px solid #30363d;
  }
  #camera-strip img {
    height:100%; object-fit:contain;
  }
  #camera-strip .cam-label {
    color:#555; font-size:12px; position:absolute;
  }
</style>
</head>
<body>

<div id="sidebar">
  <h2>🚁 MISSION CONTROL</h2>

  <div class="card">
    <h3>📡 Telemetry</h3>
    <div class="telem-row"><span>Altitude</span><span class="telem-val" id="t-alt">—</span></div>
    <div class="telem-row"><span>Lat</span><span class="telem-val" id="t-lat">—</span></div>
    <div class="telem-row"><span>Lon</span><span class="telem-val" id="t-lon">—</span></div>
  </div>

  <div class="card">
    <h3>📍 Waypoints</h3>
    <p style="font-size:11px;color:#555;margin-bottom:8px">Click map to add waypoints</p>
    <ul id="wp-list"></ul>
  </div>

  <div class="card">
    <h3>⚡ Actions</h3>
    <button class="btn btn-primary" id="btn-upload">▲ Upload & Start Mission</button>
    <button class="btn btn-warn"    id="btn-rtl">↩ Return to Launch (RTL)</button>
    <button class="btn btn-danger"  id="btn-clear">✕ Clear Waypoints</button>
  </div>

  <div class="card">
    <h3>💬 Status</h3>
    <div id="status-msg">Ready</div>
  </div>
</div>

<div id="map-area">
  <div id="map"></div>
  <div id="camera-strip">
    <span class="cam-label">📷 Downward Camera Feed</span>
    <img src="/camera_feed" alt="camera" id="cam-img"
         onerror="this.style.display='none'"/>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
// ── Map ───────────────────────────────────────────────────────────────────────
const map = L.map('map').setView([24.6877, 46.7219], 17);  // Riyadh default
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap'
}).addTo(map);

const waypoints = [];
const markers = [];
const polyline = L.polyline([], {color:'#4488ff', weight:2, dashArray:'6,4'}).addTo(map);
let droneMarker = null;

map.on('click', (e) => {
  const {lat, lng} = e.latlng;
  const idx = waypoints.length + 1;
  waypoints.push({lat, lon: lng, alt: 15});

  const m = L.circleMarker([lat, lng], {
    radius: 8, color: '#4488ff', fillColor: '#4488ff', fillOpacity: 0.8
  }).bindTooltip(`WP${idx}: ${lat.toFixed(5)}, ${lng.toFixed(5)}`).addTo(map);
  markers.push(m);

  polyline.setLatLngs(waypoints.map(w => [w.lat, w.lon]));
  renderWPList();
});

function renderWPList() {
  const ul = document.getElementById('wp-list');
  ul.innerHTML = '';
  waypoints.forEach((wp, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<span>WP${i+1}: ${wp.lat.toFixed(4)}, ${wp.lon.toFixed(4)}</span>
      <button onclick="removeWP(${i})">✕</button>`;
    ul.appendChild(li);
  });
}

function removeWP(i) {
  waypoints.splice(i, 1);
  map.removeLayer(markers.splice(i, 1));
  polyline.setLatLngs(waypoints.map(w => [w.lat, w.lon]));
  renderWPList();
}

// ── Socket.IO ────────────────────────────────────────────────────────────────
const socket = io();

socket.on('telemetry', (d) => {
  document.getElementById('t-alt').textContent = d.rel_alt.toFixed(1) + ' m';
  document.getElementById('t-lat').textContent = d.lat.toFixed(5);
  document.getElementById('t-lon').textContent = d.lon.toFixed(5);
  const pos = [d.lat, d.lon];
  if (!droneMarker) {
    droneMarker = L.marker(pos, {
      icon: L.divIcon({
        html: '<div style="font-size:22px">🚁</div>',
        iconSize:, iconAnchor:
      })
    }).addTo(map);
  } else {
    droneMarker.setLatLng(pos);
  }
});

socket.on('mission_status', (d) => {
  const el = document.getElementById('status-msg');
  el.textContent = d.msg;
  el.style.color = d.ok ? '#3fb950' : '#f85149';
});

// ── Buttons ───────────────────────────────────────────────────────────────────
document.getElementById('btn-upload').addEventListener('click', () => {
  if (!waypoints.length) {
    document.getElementById('status-msg').textContent = 'Add at least one waypoint first';
    return;
  }
  socket.emit('upload_mission', {waypoints});
  document.getElementById('status-msg').textContent = 'Uploading mission...';
});

document.getElementById('btn-rtl').addEventListener('click', () => {
  socket.emit('rtl');
  document.getElementById('status-msg').textContent = 'RTL commanded...';
});

document.getElementById('btn-clear').addEventListener('click', () => {
  waypoints.length = 0;
  markers.forEach(m => map.removeLayer(m));
  markers.length = 0;
  polyline.setLatLngs([]);
  renderWPList();
});
</script>
</body>
</html>
```

---

## FILE 9 — EDIT: `deploy/simulation/onstart_px4_landing_demo.sh`

Replace the entire launch section with:

```bash
#!/usr/bin/env bash
# deploy/simulation/onstart_px4_landing_demo.sh
# Starts the full precision landing demo stack.
# Usage: bash deploy/simulation/onstart_px4_landing_demo.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

export SKYLINK_CAMERA_CALIBRATION="$REPO_ROOT/autonomy/fixtures/sim_calibration.json"
export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

echo "=== [1/4] Starting PX4 SITL ==="
# Assumes PX4 SITL is already running on udp://:14540 and udp://:14541
# If not, start it: make -C vendor/PX4-Autopilot px4_sitl_default gazebo

echo "=== [2/4] Starting RPi companion simulator ==="
python -m autonomy.companion.rpi_companion_sim &
COMPANION_PID=$!
echo "companion PID: $COMPANION_PID"

sleep 2  # let companion connect first

echo "=== [3/4] Starting flight recorder ==="
python autonomy/scripts/record_px4_landing_demo.py &
RECORDER_PID=$!
echo "recorder PID: $RECORDER_PID"

echo "=== [4/4] Starting dashboard ==="
python dashboard/app.py &
DASH_PID=$!
echo "dashboard PID: $DASH_PID"

echo ""
echo ">>> Dashboard:    http://localhost:5000"
echo ">>> Camera feed:  http://localhost:8765/camera"
echo ""
echo "Press Ctrl+C to stop all processes"

cleanup() {
  echo "Stopping..."
  kill $COMPANION_PID $RECORDER_PID $DASH_PID 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM
wait
```

---

## FILE 10 — EDIT: `tests/test_aruco_detector.py` and `tests/test_run_companion_smoke.py`

Add these two lines at the very top of each file, before any other import:

```python
import os
os.environ.setdefault(
    "SKYLINK_CAMERA_CALIBRATION",
    str(__import__("pathlib").Path(__file__).parent.parent /
        "autonomy" / "fixtures" / "sim_calibration.json")
)
```

---

## EXECUTION CHECKLIST FOR CODEX

Run these in order after applying all edits:

```bash
# 1. Verify calibration fixture exists
python -c "import json; print(json.load(open('autonomy/fixtures/sim_calibration.json')))"

# 2. Verify landing pad renderer works
python -c "
from autonomy.simulation.landing_pad import render_frame, PadRenderConfig
import cv2
f = render_frame(PadRenderConfig(altitude_m=4.0, offset_x_m=0.3))
assert f is not None and f.shape == (512,512,3)
print('landing_pad OK')
"

# 3. Verify board detector works with sim calibration
python -c "
import os; os.environ['SKYLINK_CAMERA_CALIBRATION']='autonomy/fixtures/sim_calibration.json'
from autonomy.companion.aruco_board_detector import ArucoBoardDetectorBackend
from autonomy.simulation.landing_pad import render_frame, PadRenderConfig
det = ArucoBoardDetectorBackend()
frame = render_frame(PadRenderConfig(altitude_m=3.0))
result = det.detect(frame)
print('detect result:', result)
print('board_detector OK')
"

# 4. Run all tests — expect green
python -m pytest tests/ -x -v

# 5. Run a quick trajectory and build the HTML
python autonomy/scripts/record_px4_landing_demo.py
# Should write:
#   artifacts/demo/landing_trajectory.json
#   artifacts/demo/precision_landing_3d_demo.html

# 6. Open the demo
open artifacts/demo/precision_landing_3d_demo.html   # macOS
# or: xdg-open artifacts/demo/precision_landing_3d_demo.html

# 7. Start the full stack
bash deploy/simulation/onstart_px4_landing_demo.sh
# Then open: http://localhost:5000
```

---

## WHAT WILL BE VISUALLY CLEAR WHEN THIS IS DONE

| What you see | Where |
|---|---|
| 3D drone flying GPS waypoints on a live Leaflet map | Dashboard at :5000 |
| Live helicopter marker on map moving in real-time | Dashboard |
| RTL / mission upload buttons | Dashboard sidebar |
| Downward camera stream with green detection boxes, red centroid crosshair, yellow reticle, HUD text | Dashboard bottom strip + camera panel |
| 3D Three.js scene: drone mesh, ground grid, ArUco pad texture, camera cone, flight path colored by FSM state | Demo HTML at artifacts/demo/ |
| Timeline scrubber to replay flight frame by frame | Demo HTML |
| Color-coded FSM state (SEARCH=blue, ALIGN=yellow, DESCEND=orange, FLARE=red, TOUCHDOWN=green) | Demo HTML HUD + path |
| Red target ray from drone to pad during DESCEND/FLARE | Demo HTML |
| Companion sim MJPEG stream showing frame drops, blur, noise at low altitude | :8765/camera |

---

## INTEGRATION CONTRACT (how pieces talk to each other)