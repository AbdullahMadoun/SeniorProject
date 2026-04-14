from __future__ import annotations

import argparse
import glob
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


RMS_FAIL_THRESHOLD = 2.0
RMS_WARN_THRESHOLD = 1.0


def _template_payload(
    *,
    image_glob: str,
    inner_corners_cols: int,
    inner_corners_rows: int,
    square_size_mm: float,
) -> dict[str, object]:
    return {
        "status": "template",
        "image_glob": image_glob,
        "inner_corners_cols": inner_corners_cols,
        "inner_corners_rows": inner_corners_rows,
        "square_size_mm": square_size_mm,
        "camera_matrix": [
            [615.0, 0.0, 320.0],
            [0.0, 615.0, 240.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "note": "Replace this template by running calibration on a machine with OpenCV chessboard support and real images.",
    }


def calibrate_camera(
    *,
    image_glob: str,
    output_path: Path,
    inner_corners_cols: int = 9,
    inner_corners_rows: int = 6,
    square_size_mm: float = 24.0,
    template_only: bool = False,
) -> dict[str, object]:
    if template_only:
        payload = _template_payload(
            image_glob=image_glob,
            inner_corners_cols=inner_corners_cols,
            inner_corners_rows=inner_corners_rows,
            square_size_mm=square_size_mm,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    cv2_module, used_mock_cv2 = load_cv2_module()
    if used_mock_cv2:
        raise RuntimeError("Real OpenCV is required for camera calibration. Use --template-only on development laptops.")

    image_paths = sorted(glob.glob(image_glob))
    if not image_paths:
        raise ValueError(f"No images matched: {image_glob}")

    board_size = (inner_corners_cols, inner_corners_rows)
    object_points: list[np.ndarray] = []
    image_points: list[np.ndarray] = []
    pattern = np.zeros((inner_corners_cols * inner_corners_rows, 3), np.float32)
    pattern[:, :2] = np.mgrid[0:inner_corners_cols, 0:inner_corners_rows].T.reshape(-1, 2)
    pattern *= float(square_size_mm)
    image_shape: tuple[int, int] | None = None

    for image_path in image_paths:
        image = cv2_module.imread(image_path)
        if image is None:
            continue
        gray = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY)
        found, corners = cv2_module.findChessboardCorners(gray, board_size)
        if not found:
            continue
        image_points.append(corners)
        object_points.append(pattern.copy())
        image_shape = gray.shape[::-1]

    if not image_points or image_shape is None:
        raise RuntimeError("No checkerboard detections were found in the provided images.")

    rms_error, camera_matrix, dist_coeffs, _rvecs, _tvecs = cv2_module.calibrateCamera(
        object_points,
        image_points,
        image_shape,
        None,
        None,
    )
    
    if rms_error > RMS_FAIL_THRESHOLD:
        raise ValueError(
            f"Camera calibration RMS error {rms_error:.2f} exceeds fail threshold {RMS_FAIL_THRESHOLD:.2f}. "
            f"Recalibrate with more images or adjust checkerboard setup."
        )
    if rms_error > RMS_WARN_THRESHOLD:
        import warnings
        warnings.warn(
            f"Camera calibration RMS error {rms_error:.2f} exceeds warn threshold {RMS_WARN_THRESHOLD:.2f}. "
            f"Physical flight requires RMS < 1.0 for precision landing.",
            stacklevel=2,
        )
    
    payload = {
        "status": "calibrated",
        "image_glob": image_glob,
        "images_used": len(image_points),
        "rms_error": float(rms_error),
        "inner_corners_cols": inner_corners_cols,
        "inner_corners_rows": inner_corners_rows,
        "square_size_mm": square_size_mm,
        "camera_matrix": camera_matrix.tolist(),
        "dist_coeffs": dist_coeffs.reshape(-1).tolist(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate the downward camera from checkerboard images")
    parser.add_argument("--image-glob", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cols", type=int, default=9)
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--square-size-mm", type=float, default=24.0)
    parser.add_argument("--template-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = calibrate_camera(
        image_glob=args.image_glob,
        output_path=args.output,
        inner_corners_cols=args.cols,
        inner_corners_rows=args.rows,
        square_size_mm=args.square_size_mm,
        template_only=args.template_only,
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
