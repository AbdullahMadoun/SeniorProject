from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
from pymavlink import mavutil  # type: ignore

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from autonomy.companion.mock_rpi import MockCV2Module, build_mock_camera_source, load_cv2_module
else:
    from .mock_rpi import MockCV2Module, build_mock_camera_source, load_cv2_module


DEFAULT_OUTPUT_DIR = Path(os.environ.get("SKYLINK_ARUCO_OUTPUT", Path.cwd() / "companion_aruco"))

# Placeholder intrinsics for bench bring-up only.
# Replace these with calibrated intrinsics from the real downward-facing camera before flight.
CAMERA_MATRIX = np.array(
    [
        [615.0, 0.0, 320.0],
        [0.0, 615.0, 240.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float32,
)
DIST_COEFFS = np.zeros((5, 1), dtype=np.float32)


@dataclass(frozen=True)
class ArucoDetectorConfig:
    camera_source: str = os.environ.get("SKYLINK_ARUCO_CAMERA_SOURCE", "0")
    mavlink_target: str = os.environ.get("SKYLINK_ARUCO_MAVLINK_TARGET", "udpout:127.0.0.1:14550")
    mavlink_baud: int = 57600
    output_dir: Path = DEFAULT_OUTPUT_DIR
    marker_id: int = 0
    marker_size_m: float = 0.2
    max_frames: int = 25
    frame_interval_s: float = 0.1
    use_mock_camera: bool = False
    use_mock_mavlink: bool = False


@dataclass(frozen=True)
class LandingTargetObservation:
    timestamp_utc: float
    marker_id: int
    x_m: float
    y_m: float
    z_m: float
    source: str


class MockLandingTargetConnection:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []

    def landing_target_send(self, *args: Any) -> None:
        self.sent_messages.append(
            {
                "time_usec": args[0],
                "target_num": args[1],
                "frame": args[2],
                "angle_x_rad": args[3],
                "angle_y_rad": args[4],
                "distance_m": args[5],
                "size_x_rad": args[6],
                "size_y_rad": args[7],
                "x_m": args[8],
                "y_m": args[9],
                "z_m": args[10],
                "q": args[11],
                "target_type": args[12],
                "position_valid": args[13],
            }
        )


class LandingTargetSender:
    def __init__(self, target: str, *, baud: int = 57600, connection: Any | None = None) -> None:
        self._target = target
        self._baud = baud
        self._mock_connection = connection
        self._connection = connection
        if self._connection is None:
            self._connection = _open_mavlink_connection(target, baud)

    def send(self, observation: LandingTargetObservation) -> dict[str, Any]:
        payload = {
            "time_usec": int(observation.timestamp_utc * 1_000_000),
            "target_num": 0,
            "frame": mavutil.mavlink.MAV_FRAME_BODY_FRD,
            "angle_x_rad": 0.0,
            "angle_y_rad": 0.0,
            "distance_m": float(np.linalg.norm([observation.x_m, observation.y_m, observation.z_m])),
            "size_x_rad": 0.0,
            "size_y_rad": 0.0,
            "x_m": observation.x_m,
            "y_m": observation.y_m,
            "z_m": observation.z_m,
            "q": (1.0, 0.0, 0.0, 0.0),
            "target_type": mavutil.mavlink.LANDING_TARGET_TYPE_VISION_FIDUCIAL,
            "position_valid": 1,
        }
        self._connection.mav.landing_target_send(
            payload["time_usec"],
            payload["target_num"],
            payload["frame"],
            payload["angle_x_rad"],
            payload["angle_y_rad"],
            payload["distance_m"],
            payload["size_x_rad"],
            payload["size_y_rad"],
            payload["x_m"],
            payload["y_m"],
            payload["z_m"],
            payload["q"],
            payload["target_type"],
            payload["position_valid"],
        )
        return payload

    def close(self) -> None:
        if self._mock_connection is None and self._connection is not None and hasattr(self._connection, "close"):
            self._connection.close()


class OpenCVArucoBackend:
    def __init__(self, cv2_module: Any) -> None:
        self._cv2 = cv2_module
        self._aruco = cv2_module.aruco
        self._dictionary = self._aruco.getPredefinedDictionary(self._aruco.DICT_4X4_50)
        self._parameters = self._aruco.DetectorParameters()

    def detect(self, frame: Any, *, marker_size_m: float, marker_id: int) -> list[LandingTargetObservation]:
        corners, ids, _rejected = self._aruco.detectMarkers(
            frame,
            self._dictionary,
            parameters=self._parameters,
        )
        if ids is None or len(ids) == 0:
            return []
        rvecs, tvecs, _ = self._aruco.estimatePoseSingleMarkers(
            corners,
            marker_size_m,
            CAMERA_MATRIX,
            DIST_COEFFS,
        )
        observations: list[LandingTargetObservation] = []
        for index, raw_id in enumerate(ids.flatten().tolist()):
            if int(raw_id) != marker_id:
                continue
            tvec = tvecs[index][0]
            observations.append(
                LandingTargetObservation(
                    timestamp_utc=time.time(),
                    marker_id=int(raw_id),
                    x_m=float(tvec[0]),
                    y_m=float(tvec[1]),
                    z_m=float(tvec[2]),
                    source="cv2.aruco",
                )
            )
        return observations


class ArucoPrecisionLandingService:
    def __init__(
        self,
        config: ArucoDetectorConfig,
        *,
        cv2_module: Any | None = None,
        camera: Any | None = None,
        sender: LandingTargetSender | None = None,
        backend: OpenCVArucoBackend | None = None,
    ) -> None:
        resolved_cv2, cv2_is_mock = load_cv2_module() if cv2_module is None else (cv2_module, False)
        if not hasattr(resolved_cv2, "aruco"):
            resolved_cv2 = MockCV2Module()
            cv2_is_mock = True
        self.config = config
        self.cv2 = resolved_cv2
        self.cv2_is_mock = cv2_is_mock
        self.camera = camera
        self.backend = backend or OpenCVArucoBackend(self.cv2)
        self.sender = sender or self._build_sender(config)

    def _build_sender(self, config: ArucoDetectorConfig) -> LandingTargetSender:
        if config.use_mock_mavlink:
            return LandingTargetSender(config.mavlink_target, connection=SimpleMockConnection())
        return LandingTargetSender(config.mavlink_target, baud=config.mavlink_baud)

    def _build_camera(self) -> Any:
        if self.camera is not None:
            return self.camera
        if self.config.use_mock_camera or self.cv2_is_mock:
            return build_mock_camera_source(self.config.camera_source)
        source: Any = self.config.camera_source
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        return self.cv2.VideoCapture(source)

    def run(self) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        camera = self._build_camera()
        log_path = self.config.output_dir / "landing_target_log.json"
        preview_path = self.config.output_dir / "aruco_preview.jpg"
        sent_payloads: list[dict[str, Any]] = []
        try:
            for _ in range(self.config.max_frames):
                ok, frame = camera.read()
                if not ok or frame is None:
                    time.sleep(self.config.frame_interval_s)
                    continue
                observations = self.backend.detect(
                    frame,
                    marker_size_m=self.config.marker_size_m,
                    marker_id=self.config.marker_id,
                )
                for observation in observations:
                    payload = self.sender.send(observation)
                    sent_payloads.append(
                        {
                            **asdict(observation),
                            "landing_target_payload": payload,
                        }
                    )
                self.cv2.imwrite(str(preview_path), frame)
                if observations:
                    break
                time.sleep(self.config.frame_interval_s)
        finally:
            if hasattr(camera, "release"):
                camera.release()
            self.sender.close()

        result = {
            "config": {
                **asdict(self.config),
                "output_dir": str(self.config.output_dir),
            },
            "detections": sent_payloads,
            "detection_count": len(sent_payloads),
            "used_mock_camera": bool(self.config.use_mock_camera or self.cv2_is_mock),
            "used_mock_mavlink": bool(self.config.use_mock_mavlink),
            "preview_path": str(preview_path),
            "log_path": str(log_path),
        }
        log_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


class SimpleMockConnection:
    def __init__(self) -> None:
        self.mav = MockLandingTargetConnection()

    def close(self) -> None:
        return None


def _open_mavlink_connection(target: str, baud: int) -> Any:
    cleaned = target.strip()
    if cleaned.startswith("/") or cleaned.upper().startswith("COM"):
        return mavutil.mavlink_connection(cleaned, baud=baud, autoreconnect=True, source_system=251)
    if "://" in cleaned:
        cleaned = cleaned.replace("://", ":", 1)
    return mavutil.mavlink_connection(cleaned, autoreconnect=True, source_system=251)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ArUco precision landing companion sensor")
    parser.add_argument("--camera-source", default=os.environ.get("SKYLINK_ARUCO_CAMERA_SOURCE", "0"))
    parser.add_argument("--mavlink-target", default=os.environ.get("SKYLINK_ARUCO_MAVLINK_TARGET", "udpout:127.0.0.1:14550"))
    parser.add_argument("--mavlink-baud", type=int, default=57600)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--marker-id", type=int, default=0)
    parser.add_argument("--marker-size-m", type=float, default=0.2)
    parser.add_argument("--max-frames", type=int, default=25)
    parser.add_argument("--frame-interval", type=float, default=0.1)
    parser.add_argument("--mock-camera", action="store_true")
    parser.add_argument("--mock-mavlink", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ArucoDetectorConfig(
        camera_source=str(args.camera_source),
        mavlink_target=args.mavlink_target,
        mavlink_baud=args.mavlink_baud,
        output_dir=args.output_dir,
        marker_id=args.marker_id,
        marker_size_m=args.marker_size_m,
        max_frames=args.max_frames,
        frame_interval_s=args.frame_interval,
        use_mock_camera=args.mock_camera,
        use_mock_mavlink=args.mock_mavlink,
    )
    service = ArucoPrecisionLandingService(config)
    result = service.run()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
