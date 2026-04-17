from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
if str(AUTONOMY_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_ROOT))

from drone_system.models import Waypoint
from drone_system.synthetic_telemetry import generate_synthetic_telemetry_csv, resolve_frames_and_fps


def _load_config() -> dict:
    config_path = AUTONOMY_ROOT / "config" / "system.toml"
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic telemetry CSV for Phase 0 replay.")
    parser.add_argument("--video", type=Path, default=None, help="Optional input video path.")
    parser.add_argument("--frames", type=int, default=None, help="Frame count when no video is provided.")
    parser.add_argument("--fps", type=float, default=None, help="Frame rate when no video is provided.")
    parser.add_argument(
        "--output",
        type=Path,
        default=AUTONOMY_ROOT.parent / "artifacts" / "synthetic_telemetry_log.csv",
        help="Output CSV path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = _load_config()
    frames, fps = resolve_frames_and_fps(args.video, args.frames, args.fps)
    home = Waypoint(
        lat=config["home"]["lat"],
        lon=config["home"]["lon"],
        alt_m=config["survey"]["altitude_agl_m"],
    )
    output = generate_synthetic_telemetry_csv(
        output_csv=args.output,
        home=home,
        width_m=config["survey"]["width_m"],
        height_m=config["survey"]["height_m"],
        row_spacing_m=config["survey"]["row_spacing_m"],
        altitude_m=config["survey"]["altitude_agl_m"],
        frames=frames,
        fps=fps,
    )
    print(output)


if __name__ == "__main__":
    main()
