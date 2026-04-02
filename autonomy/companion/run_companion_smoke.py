from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from autonomy.companion.aruco_detector import ArucoDetectorConfig, ArucoPrecisionLandingService
    from autonomy.companion.gpio_charging import ChargingConfig, GPIOChargingController
    from autonomy.companion.video_logger import VideoLoggerConfig, VideoLoggerService
    from autonomy.companion.yolo_pothole_detect import DummyYoloPotholeDetector
else:
    from .aruco_detector import ArucoDetectorConfig, ArucoPrecisionLandingService
    from .gpio_charging import ChargingConfig, GPIOChargingController
    from .video_logger import VideoLoggerConfig, VideoLoggerService
    from .yolo_pothole_detect import DummyYoloPotholeDetector


DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts" / "latest"


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary(path: Path, manifest: dict[str, Any]) -> None:
    video = manifest["modules"]["video_logger"]
    aruco = manifest["modules"]["aruco_detector"]
    charging = manifest["modules"]["gpio_charging"]
    yolo = manifest["modules"]["yolo_stub"]
    lines = [
        "# Companion Smoke Summary",
        "",
        f"- generated_at_utc: `{manifest['generated_at_utc']}`",
        f"- artifact_root: `{manifest['artifact_root']}`",
        "",
        "## Video Logger",
        f"- processed_frames: `{video['processed_frames']}`",
        f"- telemetry_updates: `{video['telemetry_updates']}`",
        f"- used_mock_camera: `{video['used_mock_camera']}`",
        f"- used_mock_mavlink: `{video['used_mock_mavlink']}`",
        f"- csv_path: `{video['csv_path']}`",
        "",
        "## ArUco Detector",
        f"- detection_count: `{aruco['detection_count']}`",
        f"- used_mock_camera: `{aruco['used_mock_camera']}`",
        f"- used_mock_mavlink: `{aruco['used_mock_mavlink']}`",
        f"- log_path: `{aruco['log_path']}`",
        "",
        "## GPIO Charging",
        f"- charge_enabled: `{charging['decisions'][0]['charge_enabled'] if charging['decisions'] else False}`",
        f"- final_pin_state: `{charging['final_pin_state']}`",
        f"- output_path: `{charging['output_path']}`",
        "",
        "## YOLO Stub",
        f"- detection_count: `{yolo['detection_count']}`",
        f"- csv_path: `{yolo['csv_path']}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_smoke(*, output_dir: Path = DEFAULT_ARTIFACT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_env = {name: os.environ.get(name) for name in (
        "SKYLINK_FORCE_MOCK_GPIO",
        "SKYLINK_FORCE_MOCK_CAMERA",
        "SKYLINK_MOCK_ARUCO_DETECTION",
    )}
    os.environ["SKYLINK_FORCE_MOCK_GPIO"] = "1"
    os.environ["SKYLINK_FORCE_MOCK_CAMERA"] = "1"
    os.environ["SKYLINK_MOCK_ARUCO_DETECTION"] = "1"
    try:
        video_summary = VideoLoggerService(
            VideoLoggerConfig(
                output_dir=output_dir / "video_logger",
                max_frames=5,
                frame_interval_s=0.01,
                use_mock_mavlink=True,
                use_mock_camera=True,
            )
        ).run()
        aruco_summary = ArucoPrecisionLandingService(
            ArucoDetectorConfig(
                output_dir=output_dir / "aruco_detector",
                max_frames=5,
                frame_interval_s=0.01,
                use_mock_camera=True,
                use_mock_mavlink=True,
            )
        ).run()
        charging_summary = GPIOChargingController(
            ChargingConfig(
                output_dir=output_dir / "gpio_charging",
                cycles=1,
                poll_interval_s=0.0,
            )
        ).run()
        yolo_summary = DummyYoloPotholeDetector(output_dir=output_dir / "yolo_stub").run(
            ["frame-0001", "frame-0002", "frame-0003"]
        )
    finally:
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    manifest = {
        "generated_at_utc": _timestamp_utc(),
        "artifact_root": str(output_dir),
        "modules": {
            "video_logger": video_summary,
            "aruco_detector": aruco_summary,
            "gpio_charging": charging_summary,
            "yolo_stub": yolo_summary,
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    _write_summary(output_dir / "summary.md", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full companion hardware smoke suite")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    manifest = run_smoke(output_dir=args.output_dir)
    print(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    main()
