from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from http import server as http_server
import itertools
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

from pymavlink import mavutil  # type: ignore

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from autonomy.companion.mock_rpi import build_mock_camera_source, load_cv2_module
    from autonomy.drone_system.runtime_affinity import enforce_cpu_affinity
else:
    from .mock_rpi import build_mock_camera_source, load_cv2_module
    from ..drone_system.runtime_affinity import enforce_cpu_affinity


DEFAULT_MAVLINK_TARGET = os.environ.get("SKYLINK_MAVLINK_TARGET", "udp:127.0.0.1:14551")
DEFAULT_CAMERA_SOURCE = os.environ.get("SKYLINK_CAMERA_SOURCE", "0")
DEFAULT_OUTPUT_DIR = Path(os.environ.get("SKYLINK_VIDEO_LOGGER_OUTPUT", Path.cwd() / "companion_video_logger"))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class TelemetrySample:
    timestamp_utc: float
    lat_deg: float | None
    lon_deg: float | None
    altitude_m: float | None
    relative_altitude_m: float | None
    heading_deg: float | None
    source: str
    fix_type: str


@dataclass(frozen=True)
class VideoLoggerConfig:
    mavlink_target: str = DEFAULT_MAVLINK_TARGET
    mavlink_baud: int = 57600
    camera_source: str = DEFAULT_CAMERA_SOURCE
    output_dir: Path = DEFAULT_OUTPUT_DIR
    max_frames: int = 30
    frame_width: int = 640
    frame_height: int = 480
    frame_interval_s: float = 0.1
    telemetry_timeout_s: float = 0.5
    use_mock_mavlink: bool = False
    use_mock_camera: bool = False
    camera_backend: str = os.environ.get("SKYLINK_CAMERA_BACKEND", "auto")
    stream_enabled: bool = os.environ.get("SKYLINK_VIDEO_STREAM_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    stream_host: str = os.environ.get("SKYLINK_VIDEO_STREAM_HOST", "127.0.0.1")
    stream_port: int = _env_int("SKYLINK_VIDEO_STREAM_PORT", 5050)
    stream_path: str = os.environ.get("SKYLINK_VIDEO_STREAM_PATH", "/stream")
    cpu_core: int = _env_int("SKYLINK_VIDEO_LOGGER_CPU_CORE", 1)


class MjpegStreamServer:
    def __init__(self, *, host: str, port: int, path: str) -> None:
        self._host = host
        self._port = port
        self._path = path if path.startswith("/") else f"/{path}"
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._latest_frame: bytes | None = None
        self._frame_seq = 0
        self._server: http_server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        handler = self._build_handler()
        self._server = http_server.ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="mjpeg-stream", daemon=True)

    def _build_handler(self) -> type[http_server.BaseHTTPRequestHandler]:
        parent = self

        class Handler(http_server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path not in {parent._path, f"{parent._path}/"}:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                last_seq = -1
                try:
                    while not parent._stop_event.is_set():
                        frame, frame_seq = parent.wait_for_frame(last_seq, timeout_s=1.0)
                        if frame is None:
                            continue
                        last_seq = frame_seq
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return

            def log_message(self, _format: str, *_args: Any) -> None:
                return None

        return Handler

    def start(self) -> None:
        if self._thread is None:
            raise RuntimeError("MJPEG stream thread was not initialized.")
        self._thread.start()

    def publish_frame(self, frame_bytes: bytes) -> None:
        with self._condition:
            self._latest_frame = frame_bytes
            self._frame_seq += 1
            self._condition.notify_all()

    def wait_for_frame(self, last_seq: int, *, timeout_s: float) -> tuple[bytes | None, int]:
        with self._condition:
            if self._frame_seq <= last_seq and not self._stop_event.is_set():
                self._condition.wait(timeout=timeout_s)
            if self._frame_seq <= last_seq:
                return None, last_seq
            return self._latest_frame, self._frame_seq

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def stream_url(self) -> str:
        if self._server is None:
            raise RuntimeError("MJPEG server is not initialized.")
        address, port = self._server.server_address[:2]
        host = "127.0.0.1" if address in {"0.0.0.0", ""} else address
        return f"http://{host}:{port}{self._path}"


_TRACKED_MAVLINK_TYPES: list[str] = ["GLOBAL_POSITION_INT", "VFR_HUD", "ATTITUDE"]


class TelemetrySource:
    """Base class for telemetry producers; heartbeat_send and read_raw are no-ops by default."""

    def heartbeat_send(self) -> None:
        return None

    def read_raw(self, timeout_s: float) -> tuple[Any, float] | None:
        return None

    def supports_raw_read(self) -> bool:
        return False


class MockTelemetrySource(TelemetrySource):
    def __init__(self) -> None:
        self._index = 0

    def connect(self) -> None:
        return None

    def read(self, timeout_s: float) -> TelemetrySample | None:
        time.sleep(max(0.0, min(timeout_s, 0.05)))
        self._index += 1
        lat_deg = 47.397971 + (self._index * 0.000001)
        lon_deg = 8.546164 + (self._index * 0.0000015)
        return TelemetrySample(
            timestamp_utc=time.time(),
            lat_deg=lat_deg,
            lon_deg=lon_deg,
            altitude_m=488.0 + (self._index * 0.1),
            relative_altitude_m=12.0 + (self._index * 0.1),
            heading_deg=(90.0 + self._index) % 360.0,
            source="mock_mavlink",
            fix_type="mock_fix",
        )

    def close(self) -> None:
        return None


class PymavlinkTelemetrySource(TelemetrySource):
    def __init__(self, target: str, baud: int) -> None:
        self._target = target
        self._baud = baud
        self._connection: Any | None = None

    def connect(self) -> None:
        if self._connection is not None:
            return
        self._connection = _open_mavlink_connection(self._target, self._baud)

    def read(self, timeout_s: float) -> TelemetrySample | None:
        if self._connection is None:
            return None
        message = self._connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=timeout_s,
        )
        if message is None:
            return None
        return _gpi_msg_to_telemetry_sample(message)

    def read_raw(self, timeout_s: float) -> tuple[Any, float] | None:
        if self._connection is None:
            return None
        message = self._connection.recv_match(
            type=_TRACKED_MAVLINK_TYPES,
            blocking=True,
            timeout=timeout_s,
        )
        if message is None:
            return None
        return message, time.monotonic()

    def heartbeat_send(self) -> None:
        if self._connection is None:
            return
        self._connection.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0,
        )

    def supports_raw_read(self) -> bool:
        return True

    def close(self) -> None:
        if self._connection is not None and hasattr(self._connection, "close"):
            self._connection.close()
        self._connection = None


def _open_mavlink_connection(target: str, baud: int) -> Any:
    cleaned = target.strip()
    if cleaned.startswith("/") or cleaned.upper().startswith("COM"):
        return mavutil.mavlink_connection(cleaned, baud=baud, autoreconnect=True, source_system=250)
    if "://" in cleaned:
        cleaned = cleaned.replace("://", ":", 1)
    if ":" not in cleaned and cleaned.count(".") == 3:
        cleaned = f"udp:{cleaned}"
    return mavutil.mavlink_connection(cleaned, autoreconnect=True, source_system=250)


def _gpi_msg_to_telemetry_sample(message: Any) -> TelemetrySample:
    heading_cdeg = getattr(message, "hdg", None)
    return TelemetrySample(
        timestamp_utc=time.time(),
        lat_deg=getattr(message, "lat", None) / 1e7 if getattr(message, "lat", None) is not None else None,
        lon_deg=getattr(message, "lon", None) / 1e7 if getattr(message, "lon", None) is not None else None,
        altitude_m=getattr(message, "alt", None) / 1000.0 if getattr(message, "alt", None) is not None else None,
        relative_altitude_m=(
            getattr(message, "relative_alt", None) / 1000.0
            if getattr(message, "relative_alt", None) is not None
            else None
        ),
        heading_deg=(heading_cdeg / 100.0) if heading_cdeg not in {None, 65535} else None,
        source="pymavlink",
        fix_type="global_position_int",
    )


class Picamera2CameraSource:
    def __init__(self, width: int, height: int) -> None:
        from picamera2 import Picamera2  # type: ignore[import]
        self._cam = Picamera2()
        cfg = self._cam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"},
        )
        self._cam.configure(cfg)
        self._cam.start()

    def read(self) -> tuple[bool, Any]:
        try:
            frame = self._cam.capture_array()
            return True, frame[:, :, ::-1].copy()  # RGB → BGR for cv2 compatibility
        except Exception:
            return False, None

    def set(self, prop_id: int, value: float) -> bool:
        return True

    def release(self) -> None:
        try:
            self._cam.stop()
        except Exception:
            pass
        try:
            self._cam.close()
        except Exception:
            pass


class VideoLoggerService:
    def __init__(
        self,
        config: VideoLoggerConfig,
        *,
        telemetry_source: MockTelemetrySource | PymavlinkTelemetrySource | None = None,
        camera: Any | None = None,
        cv2_module: Any | None = None,
    ) -> None:
        resolved_cv2, cv2_is_mock = load_cv2_module() if cv2_module is None else (cv2_module, False)
        self.config = config
        self.cv2 = resolved_cv2
        self.cv2_is_mock = cv2_is_mock
        self.telemetry_source = telemetry_source or self._build_telemetry_source(config)
        self.camera = camera
        self._telemetry_lock = threading.Lock()
        self._latest_sample: TelemetrySample | None = None
        self._stop_event = threading.Event()
        self._telemetry_updates = 0
        self._processed_frames = 0
        self._camera_backend_used: str = "unknown"
        self._stream_server: MjpegStreamServer | None = None
        self._latest_mavlink: dict[str, tuple[Any, float]] = {}
        self._raw_mavlink_mode: bool = self.telemetry_source.supports_raw_read()
        self._last_telemetry_error: str | None = None
        self._telemetry_errors_count: int = 0

    def _build_telemetry_source(self, config: VideoLoggerConfig) -> MockTelemetrySource | PymavlinkTelemetrySource:
        if config.use_mock_mavlink:
            return MockTelemetrySource()
        try:
            source = PymavlinkTelemetrySource(config.mavlink_target, config.mavlink_baud)
            source.connect()
            return source
        except Exception:
            return MockTelemetrySource()

    def _build_camera(self) -> Any:
        if self.camera is not None:
            self._camera_backend_used = "injected"
            print(f"[video_logger] camera backend selected: {self._camera_backend_used}", file=sys.stderr, flush=True)
            return self.camera
        if self.config.use_mock_camera or self.cv2_is_mock:
            self._camera_backend_used = "mock"
            print(f"[video_logger] camera backend selected: {self._camera_backend_used}", file=sys.stderr, flush=True)
            return build_mock_camera_source(self.config.camera_source)
        backend = self.config.camera_backend
        if backend in ("picamera2", "auto"):
            try:
                cam = Picamera2CameraSource(self.config.frame_width, self.config.frame_height)
                self._camera_backend_used = "picamera2"
                print(f"[video_logger] camera backend selected: {self._camera_backend_used}", file=sys.stderr, flush=True)
                return cam
            except Exception:
                if backend == "picamera2":
                    raise
        source: Any = self.config.camera_source
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        capture = self.cv2.VideoCapture(source)
        if hasattr(capture, "set"):
            capture.set(getattr(self.cv2, "CAP_PROP_FRAME_WIDTH", 3), self.config.frame_width)
            capture.set(getattr(self.cv2, "CAP_PROP_FRAME_HEIGHT", 4), self.config.frame_height)
        self._camera_backend_used = "cv2"
        print(f"[video_logger] camera backend selected: {self._camera_backend_used}", file=sys.stderr, flush=True)
        return capture

    def _telemetry_loop(self) -> None:
        last_heartbeat: float = 0.0
        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                if now - last_heartbeat >= 1.0:
                    self.telemetry_source.heartbeat_send()
                    last_heartbeat = now
                if self._raw_mavlink_mode:
                    result = self.telemetry_source.read_raw(self.config.telemetry_timeout_s)
                    if result is not None:
                        msg, recv_ts = result
                        msg_type = msg.get_type()
                        with self._telemetry_lock:
                            self._latest_mavlink[msg_type] = (msg, recv_ts)
                            if msg_type == "GLOBAL_POSITION_INT":
                                self._latest_sample = _gpi_msg_to_telemetry_sample(msg)
                                self._telemetry_updates += 1
                else:
                    sample = self.telemetry_source.read(self.config.telemetry_timeout_s)
                    if sample is not None:
                        with self._telemetry_lock:
                            self._latest_sample = sample
                            self._telemetry_updates += 1
            except Exception as exc:
                self._last_telemetry_error = repr(exc)
                self._telemetry_errors_count += 1

    def _wait_for_initial_sample(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._telemetry_lock:
                if self._latest_sample is not None:
                    return
            time.sleep(0.01)

    def _overlay_lines(self, frame: Any, sample: TelemetrySample | None) -> Any:
        if sample is None:
            lines = ["GPS unavailable", "Using last-known or mock telemetry"]
        else:
            lines = [
                f"Lat: {sample.lat_deg:.6f}" if sample.lat_deg is not None else "Lat: n/a",
                f"Lon: {sample.lon_deg:.6f}" if sample.lon_deg is not None else "Lon: n/a",
                f"Alt: {sample.altitude_m:.2f} m" if sample.altitude_m is not None else "Alt: n/a",
                f"Heading: {sample.heading_deg:.1f} deg" if sample.heading_deg is not None else "Heading: n/a",
                f"Source: {sample.source}",
            ]
        y = 28
        for line in lines:
            self.cv2.putText(
                frame,
                line,
                (18, y),
                getattr(self.cv2, "FONT_HERSHEY_SIMPLEX", 0),
                0.6,
                (0, 255, 170),
                2,
                getattr(self.cv2, "LINE_AA", 16),
            )
            y += 26
        return frame

    def _encode_frame(self, frame: Any) -> bytes | None:
        if not hasattr(self.cv2, "imencode"):
            return None
        success, encoded = self.cv2.imencode(".jpg", frame)
        if not success:
            return None
        if hasattr(encoded, "tobytes"):
            return encoded.tobytes()
        return bytes(encoded)

    def _start_stream_server(self) -> None:
        if not self.config.stream_enabled:
            return
        self._stream_server = MjpegStreamServer(
            host=self.config.stream_host,
            port=self.config.stream_port,
            path=self.config.stream_path,
        )
        self._stream_server.start()

    def current_stream_url(self) -> str | None:
        if self._stream_server is None:
            return None
        return self._stream_server.stream_url

    def _write_csv_row(
        self,
        writer: csv.DictWriter[str],
        frame_index: int,
        sample: TelemetrySample | None,
    ) -> None:
        row = {
            "frame_index": frame_index,
            "timestamp_utc": time.time(),
            "lat_deg": sample.lat_deg if sample is not None else None,
            "lon_deg": sample.lon_deg if sample is not None else None,
            "altitude_m": sample.altitude_m if sample is not None else None,
            "relative_altitude_m": sample.relative_altitude_m if sample is not None else None,
            "heading_deg": sample.heading_deg if sample is not None else None,
            "fix_type": sample.fix_type if sample is not None else "unavailable",
            "telemetry_source": sample.source if sample is not None else "none",
        }
        writer.writerow(row)

    def _build_jsonl_entry(
        self,
        frame_index: int,
        frame_ts_unix: float,
        frame_ts_mono: float,
        mavlink_snap: dict[str, tuple[Any, float]],
    ) -> dict[str, Any]:
        def _age_ms(key: str) -> int | None:
            slot = mavlink_snap.get(key)
            if slot is None:
                return None
            return max(0, int((frame_ts_mono - slot[1]) * 1000))

        gpi_msg = mavlink_snap["GLOBAL_POSITION_INT"][0] if "GLOBAL_POSITION_INT" in mavlink_snap else None
        vfr_msg = mavlink_snap["VFR_HUD"][0] if "VFR_HUD" in mavlink_snap else None
        att_msg = mavlink_snap["ATTITUDE"][0] if "ATTITUDE" in mavlink_snap else None
        return {
            "frame_idx": frame_index,
            "frame_ts_unix": round(frame_ts_unix, 6),
            "lat_deg": round(gpi_msg.lat * 1e-7, 7) if gpi_msg is not None else None,
            "lon_deg": round(gpi_msg.lon * 1e-7, 7) if gpi_msg is not None else None,
            "alt_m_msl": round(gpi_msg.alt * 1e-3, 3) if gpi_msg is not None else None,
            "alt_m_rel": round(gpi_msg.relative_alt * 1e-3, 3) if gpi_msg is not None else None,
            "ground_speed_mps": round(float(vfr_msg.groundspeed), 3) if vfr_msg is not None else None,
            "airspeed_mps": round(float(vfr_msg.airspeed), 3) if vfr_msg is not None else None,
            "roll_deg": round(math.degrees(att_msg.roll), 4) if att_msg is not None else None,
            "pitch_deg": round(math.degrees(att_msg.pitch), 4) if att_msg is not None else None,
            "yaw_deg": round(math.degrees(att_msg.yaw), 4) if att_msg is not None else None,
            "gps_age_ms": _age_ms("GLOBAL_POSITION_INT"),
            "vfr_age_ms": _age_ms("VFR_HUD"),
            "att_age_ms": _age_ms("ATTITUDE"),
        }

    def run(self) -> dict[str, Any]:
        enforce_cpu_affinity(self.config.cpu_core, label="video_logger")
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.config.output_dir / "telemetry_log.csv"
        summary_path = self.config.output_dir / "summary.json"
        preview_path = self.config.output_dir / "latest_frame.jpg"
        jsonl_path = self.config.output_dir / "telemetry.jsonl"
        _frame_age_max_ms: int | None = None
        camera = self._build_camera()
        self.telemetry_source.connect()
        self._start_stream_server()
        telemetry_thread = threading.Thread(target=self._telemetry_loop, name="video-logger-telemetry", daemon=True)
        telemetry_thread.start()
        self._wait_for_initial_sample(timeout_s=max(0.1, self.config.telemetry_timeout_s))
        fieldnames = [
            "frame_index",
            "timestamp_utc",
            "lat_deg",
            "lon_deg",
            "altitude_m",
            "relative_altitude_m",
            "heading_deg",
            "fix_type",
            "telemetry_source",
        ]
        try:
            with csv_path.open("w", newline="", encoding="utf-8") as handle, \
                    jsonl_path.open("w", encoding="utf-8") as jsonl_handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                frame_indices = range(self.config.max_frames) if self.config.max_frames > 0 else itertools.count()
                for frame_index in frame_indices:
                    ok, frame = camera.read()
                    if not ok or frame is None:
                        time.sleep(self.config.frame_interval_s)
                        continue
                    with self._telemetry_lock:
                        sample = self._latest_sample
                        mavlink_snap = dict(self._latest_mavlink)
                    frame_ts_unix = time.time()
                    frame_ts_mono = time.monotonic()
                    annotated = self._overlay_lines(frame, sample)
                    self._write_csv_row(writer, frame_index, sample)
                    handle.flush()
                    entry = self._build_jsonl_entry(frame_index, frame_ts_unix, frame_ts_mono, mavlink_snap)
                    jsonl_handle.write(json.dumps(entry) + "\n")
                    jsonl_handle.flush()
                    row_max = max(
                        (a for a in [entry["gps_age_ms"], entry["vfr_age_ms"], entry["att_age_ms"]] if a is not None),
                        default=None,
                    )
                    if row_max is not None:
                        _frame_age_max_ms = max(_frame_age_max_ms or 0, row_max)
                    self.cv2.imwrite(str(preview_path), annotated)
                    frame_bytes = self._encode_frame(annotated)
                    if frame_bytes is not None and self._stream_server is not None:
                        self._stream_server.publish_frame(frame_bytes)
                    self._processed_frames += 1
                    time.sleep(self.config.frame_interval_s)
        finally:
            self._stop_event.set()
            telemetry_thread.join(timeout=2.0)
            if self._stream_server is not None:
                self._stream_server.stop()
            if hasattr(camera, "release"):
                camera.release()
            self.telemetry_source.close()
            if hasattr(self.cv2, "destroyAllWindows"):
                try:
                    self.cv2.destroyAllWindows()
                except self.cv2.error:
                    pass  # headless opencv raises; no windows to destroy on companion Pi

        summary = {
            "config": {
                **asdict(self.config),
                "output_dir": str(self.config.output_dir),
            },
            "processed_frames": self._processed_frames,
            "telemetry_updates": self._telemetry_updates,
            "used_mock_camera": bool(self.config.use_mock_camera or self.cv2_is_mock),
            "used_mock_mavlink": isinstance(self.telemetry_source, MockTelemetrySource),
            "camera_backend_used": self._camera_backend_used,
            "csv_path": str(csv_path),
            "preview_path": str(preview_path),
            "jsonl_path": str(jsonl_path),
            "frame_age_max_ms": _frame_age_max_ms,
            "telemetry_errors_count": self._telemetry_errors_count,
            "last_telemetry_error": self._last_telemetry_error,
            "stream": {
                "enabled": self.config.stream_enabled,
                "url": self.current_stream_url(),
                "path": self.config.stream_path,
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Threaded MAVLink + camera companion video logger")
    parser.add_argument("--mavlink-target", default=DEFAULT_MAVLINK_TARGET)
    parser.add_argument("--mavlink-baud", type=int, default=57600)
    parser.add_argument("--camera-source", default=DEFAULT_CAMERA_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-frames", type=int, default=30)
    parser.add_argument("--frame-width", type=int, default=640)
    parser.add_argument("--frame-height", type=int, default=480)
    parser.add_argument("--frame-interval", type=float, default=0.1)
    parser.add_argument("--mock-mavlink", action="store_true")
    parser.add_argument("--mock-camera", action="store_true")
    parser.add_argument("--camera-backend", default=os.environ.get("SKYLINK_CAMERA_BACKEND", "auto"), choices=["cv2", "picamera2", "auto"])
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--stream-host", default="127.0.0.1")
    parser.add_argument("--stream-port", type=int, default=5050)
    parser.add_argument("--stream-path", default="/stream")
    parser.add_argument("--cpu-core", type=int, default=_env_int("SKYLINK_VIDEO_LOGGER_CPU_CORE", 1))
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = VideoLoggerConfig(
        mavlink_target=args.mavlink_target,
        mavlink_baud=args.mavlink_baud,
        camera_source=str(args.camera_source),
        output_dir=args.output_dir,
        max_frames=args.max_frames,
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        frame_interval_s=args.frame_interval,
        use_mock_mavlink=args.mock_mavlink,
        use_mock_camera=args.mock_camera,
        camera_backend=args.camera_backend,
        stream_enabled=args.stream,
        stream_host=args.stream_host,
        stream_port=args.stream_port,
        stream_path=args.stream_path,
        cpu_core=args.cpu_core,
    )
    service = VideoLoggerService(config)
    summary = service.run()
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
