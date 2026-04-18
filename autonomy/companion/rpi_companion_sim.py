from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from autonomy.companion.aruco_board_detector import ArucoBoardDetectorBackend
from autonomy.companion.aruco_detector import LandingTargetSender
from autonomy.drone_system.landing_target_stream import connection_string_for_endpoint
from autonomy.simulation.landing_pad import IMG_H, IMG_W, PadRenderConfig, annotate_frame, render_frame


AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
SIM_CALIBRATION_PATH = AUTONOMY_ROOT / "fixtures" / "sim_calibration.json"
STATE_FILE = Path(
    os.environ.get(
        "SKYLINK_COMPANION_STATE_FILE",
        str(Path(tempfile.gettempdir()) / "skylink_drone_state.json"),
    )
)
MJPEG_PORT = int(os.environ.get("SKYLINK_COMPANION_MJPEG_PORT", "8765"))
CAMERA_HZ = float(os.environ.get("SKYLINK_COMPANION_CAMERA_HZ", "10.0"))

os.environ.setdefault("SKYLINK_CAMERA_CALIBRATION", str(SIM_CALIBRATION_PATH))

_latest_frame_lock = threading.Lock()
_latest_frame_jpg = b""


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_connection_string() -> str:
    configured = os.environ.get("LANDING_TARGET_CONNECTION_STRING")
    if configured:
        return configured
    endpoint = os.environ.get("LANDING_TARGET_ENDPOINT", "gcs")
    bridge_ip = os.environ.get("LANDING_TARGET_BRIDGE_IP", "127.0.0.1")
    return connection_string_for_endpoint(
        endpoint,
        bridge_ip=bridge_ip,
        direct_px4=_env_flag("LANDING_TARGET_DIRECT_PX4"),
    )


def _read_drone_state() -> PadRenderConfig:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return PadRenderConfig()

    return PadRenderConfig(
        altitude_m=float(payload.get("altitude_m", 5.0)),
        offset_x_m=float(payload.get("offset_x_m", 0.0)),
        offset_y_m=float(payload.get("offset_y_m", 0.0)),
        roll_rad=float(payload.get("roll_rad", 0.0)),
        pitch_rad=float(payload.get("pitch_rad", 0.0)),
        vel_xy_ms=float(payload.get("vel_xy_ms", 0.0)),
        drop_prob=float(payload.get("drop_prob", 0.0)),
        noise_enabled=bool(payload.get("noise_enabled", True)),
    )


def _build_detection_debug(
    detector: ArucoBoardDetectorBackend,
    frame,
    detection_count: int,
) -> dict[str, object]:
    corners, ids, _rejected = detector.detect_marker_geometry(frame)
    if ids is None or len(ids) == 0:
        return {"detected": False, "confidence": 0.0, "corners": []}

    all_points = []
    serialized_corners: list[list[list[float]]] = []
    for raw_corner in corners:
        points = raw_corner.reshape((-1, 2))
        serialized_corners.append(points.tolist())
        all_points.append(points)
    centroid = sum((points for points in all_points), start=all_points[0] * 0.0)
    centroid = centroid.sum(axis=0) / max(1, sum(len(points) for points in all_points))
    return {
        "detected": detection_count > 0,
        "confidence": 1.0 if detection_count > 0 else 0.0,
        "corners": serialized_corners,
        "centroid_x_px": float(centroid[0]),
        "centroid_y_px": float(centroid[1]),
    }


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *args) -> None:
        del args
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/camera":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        interval_s = 1.0 / max(CAMERA_HZ, 1.0)
        try:
            while True:
                with _latest_frame_lock:
                    jpg = _latest_frame_jpg
                if jpg:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
                time.sleep(interval_s)
        except (BrokenPipeError, ConnectionResetError):
            return


def _start_mjpeg_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", MJPEG_PORT), MJPEGHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[companion] MJPEG stream ready at http://0.0.0.0:{MJPEG_PORT}/camera", flush=True)
    return server


async def run_companion() -> None:
    global _latest_frame_jpg

    connection_string = _resolve_connection_string()
    print(f"[companion] LANDING_TARGET target: {connection_string}", flush=True)
    server = _start_mjpeg_server()
    sender = LandingTargetSender(connection_string)
    detector = ArucoBoardDetectorBackend(cv2, calibration_path=str(SIM_CALIBRATION_PATH))
    interval_s = 1.0 / max(CAMERA_HZ, 1.0)

    try:
        while True:
            loop_start_s = time.monotonic()
            config = _read_drone_state()
            frame = render_frame(config)
            if frame is None:
                frame = np.full((IMG_H, IMG_W, 3), 40, dtype=np.uint8)
                detection = {"detected": False, "confidence": 0.0, "corners": []}
            else:
                observations = detector.detect(frame)
                if observations:
                    sender.send(observations[0])
                detection = _build_detection_debug(detector, frame, len(observations))
            if frame is not None:
                annotated = annotate_frame(frame, config, detection)
                ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    with _latest_frame_lock:
                        _latest_frame_jpg = bytes(buffer)
            await asyncio.sleep(max(0.0, interval_s - (time.monotonic() - loop_start_s)))
    finally:
        sender.close()
        server.shutdown()
        server.server_close()


def main() -> None:
    asyncio.run(run_companion())


if __name__ == "__main__":
    main()
