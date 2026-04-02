from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
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
else:
    from .mock_rpi import build_mock_camera_source, load_cv2_module


DEFAULT_MAVLINK_TARGET = os.environ.get("SKYLINK_MAVLINK_TARGET", "udp:127.0.0.1:14551")
DEFAULT_CAMERA_SOURCE = os.environ.get("SKYLINK_CAMERA_SOURCE", "0")
DEFAULT_OUTPUT_DIR = Path(os.environ.get("SKYLINK_VIDEO_LOGGER_OUTPUT", Path.cwd() / "companion_video_logger"))


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


class MockTelemetrySource:
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


class PymavlinkTelemetrySource:
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
            return self.camera
        if self.config.use_mock_camera or self.cv2_is_mock:
            return build_mock_camera_source(self.config.camera_source)
        source: Any = self.config.camera_source
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        capture = self.cv2.VideoCapture(source)
        if hasattr(capture, "set"):
            capture.set(getattr(self.cv2, "CAP_PROP_FRAME_WIDTH", 3), self.config.frame_width)
            capture.set(getattr(self.cv2, "CAP_PROP_FRAME_HEIGHT", 4), self.config.frame_height)
        return capture

    def _telemetry_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                sample = self.telemetry_source.read(self.config.telemetry_timeout_s)
            except Exception:
                sample = None
            if sample is not None:
                with self._telemetry_lock:
                    self._latest_sample = sample
                    self._telemetry_updates += 1

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

    def run(self) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.config.output_dir / "telemetry_log.csv"
        summary_path = self.config.output_dir / "summary.json"
        preview_path = self.config.output_dir / "latest_frame.jpg"
        camera = self._build_camera()
        self.telemetry_source.connect()
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
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for frame_index in range(self.config.max_frames):
                    ok, frame = camera.read()
                    if not ok or frame is None:
                        time.sleep(self.config.frame_interval_s)
                        continue
                    with self._telemetry_lock:
                        sample = self._latest_sample
                    annotated = self._overlay_lines(frame, sample)
                    self._write_csv_row(writer, frame_index, sample)
                    handle.flush()
                    self.cv2.imwrite(str(preview_path), annotated)
                    self._processed_frames += 1
                    time.sleep(self.config.frame_interval_s)
        finally:
            self._stop_event.set()
            telemetry_thread.join(timeout=2.0)
            if hasattr(camera, "release"):
                camera.release()
            self.telemetry_source.close()
            if hasattr(self.cv2, "destroyAllWindows"):
                self.cv2.destroyAllWindows()

        summary = {
            "config": {
                **asdict(self.config),
                "output_dir": str(self.config.output_dir),
            },
            "processed_frames": self._processed_frames,
            "telemetry_updates": self._telemetry_updates,
            "used_mock_camera": bool(self.config.use_mock_camera or self.cv2_is_mock),
            "used_mock_mavlink": isinstance(self.telemetry_source, MockTelemetrySource),
            "csv_path": str(csv_path),
            "preview_path": str(preview_path),
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
    )
    service = VideoLoggerService(config)
    summary = service.run()
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
