from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from autonomy.companion.mock_rpi import load_cv2_module
else:
    from .mock_rpi import load_cv2_module


def _write_pgm(path: Path, image: np.ndarray) -> None:
    data = np.asarray(image, dtype=np.uint8)
    header = f"P5\n{data.shape[1]} {data.shape[0]}\n255\n".encode("ascii")
    path.write_bytes(header + data.tobytes())


def _marker_array(cv2_module: Any, *, marker_id: int, side_pixels: int) -> tuple[np.ndarray, str]:
    if hasattr(cv2_module, "aruco"):
        aruco = cv2_module.aruco
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        if hasattr(aruco, "generateImageMarker"):
            marker = aruco.generateImageMarker(dictionary, marker_id, side_pixels)
        elif hasattr(aruco, "drawMarker"):
            marker = aruco.drawMarker(dictionary, marker_id, side_pixels)
        else:
            raise RuntimeError("cv2.aruco is present but marker generation is unavailable.")
        return np.asarray(marker, dtype=np.uint8), "opencv_aruco"
    raise RuntimeError("cv2.aruco is unavailable.")


def generate_aruco_marker(
    *,
    output_dir: Path,
    marker_id: int = 0,
    side_pixels: int = 400,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cv2_module, used_mock_cv2 = load_cv2_module()
    marker_path = output_dir / f"aruco_id_{marker_id}.pgm"
    metadata_path = output_dir / f"aruco_id_{marker_id}.json"
    marker, source = _marker_array(cv2_module, marker_id=marker_id, side_pixels=side_pixels)
    _write_pgm(marker_path, marker)
    metadata = {
        "marker_id": marker_id,
        "dictionary": "DICT_4X4_50",
        "side_pixels": int(side_pixels),
        "marker_path": str(marker_path),
        "generation_source": source,
        "used_mock_cv2": bool(used_mock_cv2),
        "flight_ready": not bool(used_mock_cv2),
        "note": (
            "Mock-generated marker is for local tooling validation only."
            if used_mock_cv2
            else "Generated with OpenCV aruco backend."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an ArUco marker for the landing target")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--marker-id", type=int, default=0)
    parser.add_argument("--side-pixels", type=int, default=400)
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = generate_aruco_marker(
        output_dir=args.output_dir,
        marker_id=args.marker_id,
        side_pixels=args.side_pixels,
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()

