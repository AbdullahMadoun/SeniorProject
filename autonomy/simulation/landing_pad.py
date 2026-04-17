from __future__ import annotations

import math
import random
from dataclasses import dataclass

import cv2
import numpy as np


ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
MARKER_LENGTH_M = 0.20
MARKER_SEPARATION_M = 0.05
BOARD_COLS = 2
BOARD_ROWS = 2
BOARD_MARGIN_M = 0.05

CAM_FX = 400.0
CAM_FY = 400.0
CAM_CX = 256.0
CAM_CY = 256.0
IMG_W = 512
IMG_H = 512

BOARD_SIDE_M = (
    (BOARD_COLS * MARKER_LENGTH_M)
    + ((BOARD_COLS - 1) * MARKER_SEPARATION_M)
    + (2.0 * BOARD_MARGIN_M)
)


@dataclass(frozen=True)
class PadRenderConfig:
    altitude_m: float = 5.0
    offset_x_m: float = 0.0
    offset_y_m: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    vel_xy_ms: float = 0.0
    drop_prob: float = 0.02
    noise_enabled: bool = True


_BOARD_IMG_CACHE: np.ndarray | None = None


def _build_board() -> object:
    try:
        return cv2.aruco.GridBoard(
            (BOARD_COLS, BOARD_ROWS),
            MARKER_LENGTH_M,
            MARKER_SEPARATION_M,
            ARUCO_DICT,
        )
    except AttributeError:
        return cv2.aruco.GridBoard_create(
            BOARD_COLS,
            BOARD_ROWS,
            MARKER_LENGTH_M,
            MARKER_SEPARATION_M,
            ARUCO_DICT,
            firstMarker=0,
        )


def _generate_board_image(size_px: int = 1024) -> np.ndarray:
    board = _build_board()
    if hasattr(board, "generateImage"):
        image = board.generateImage((size_px, size_px), marginSize=40, borderBits=1)
    else:
        image = board.draw((size_px, size_px), marginSize=40, borderBits=1)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


def _get_board_image() -> np.ndarray:
    global _BOARD_IMG_CACHE
    if _BOARD_IMG_CACHE is None:
        _BOARD_IMG_CACHE = _generate_board_image()
    return _BOARD_IMG_CACHE.copy()


def _destination_quad(cfg: PadRenderConfig) -> np.ndarray:
    altitude_m = max(cfg.altitude_m, 0.15)
    pixels_per_meter = CAM_FX / altitude_m
    board_px = float(np.clip(BOARD_SIDE_M * pixels_per_meter, 80.0, 460.0))
    half_side_px = board_px / 2.0

    center_x = CAM_CX - (cfg.offset_x_m * pixels_per_meter)
    center_y = CAM_CY - (cfg.offset_y_m * pixels_per_meter)

    pitch_shear_px = math.tan(cfg.pitch_rad) * board_px * 0.25
    roll_shear_px = math.tan(cfg.roll_rad) * board_px * 0.25

    return np.array(
        [
            [center_x - half_side_px - pitch_shear_px, center_y - half_side_px + roll_shear_px],
            [center_x + half_side_px + pitch_shear_px, center_y - half_side_px - roll_shear_px],
            [center_x + half_side_px + pitch_shear_px, center_y + half_side_px - roll_shear_px],
            [center_x - half_side_px - pitch_shear_px, center_y + half_side_px + roll_shear_px],
        ],
        dtype=np.float32,
    )


def _apply_motion_blur(frame: np.ndarray, velocity_mps: float) -> np.ndarray:
    blur_size = max(1, min(15, int(round(velocity_mps * 4.0))))
    if blur_size <= 1:
        return frame
    if blur_size % 2 == 0:
        blur_size += 1
    kernel = np.zeros((blur_size, blur_size), dtype=np.float32)
    kernel[blur_size // 2, :] = 1.0 / blur_size
    return cv2.filter2D(frame, -1, kernel)


def render_frame(cfg: PadRenderConfig) -> np.ndarray | None:
    if cfg.drop_prob > 0.0 and random.random() < cfg.drop_prob:
        return None

    board_img = _get_board_image()
    canvas = np.full((IMG_H, IMG_W, 3), 40, dtype=np.uint8)

    src_h, src_w = board_img.shape[:2]
    src_quad = np.array(
        [
            [0.0, 0.0],
            [src_w - 1.0, 0.0],
            [src_w - 1.0, src_h - 1.0],
            [0.0, src_h - 1.0],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(src_quad, _destination_quad(cfg))
    warped_board = cv2.warpPerspective(
        board_img,
        transform,
        (IMG_W, IMG_H),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_TRANSPARENT,
    )
    mask = cv2.cvtColor(warped_board, cv2.COLOR_BGR2GRAY) > 0
    canvas[mask] = warped_board[mask]

    if cfg.noise_enabled:
        if cfg.vel_xy_ms > 0.3:
            canvas = _apply_motion_blur(canvas, cfg.vel_xy_ms)
        if cfg.altitude_m < 1.5:
            density = 0.015 + (0.015 * (1.5 - max(cfg.altitude_m, 0.0)))
            count = int(density * IMG_W * IMG_H)
            ys = np.random.randint(0, IMG_H, count)
            xs = np.random.randint(0, IMG_W, count)
            canvas[ys, xs] = np.where(
                np.random.randint(0, 2, count)[:, None] == 0,
                0,
                255,
            )
        alpha = 0.9 + (random.random() * 0.2)
        canvas = np.clip(canvas.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    return canvas


def annotate_frame(
    frame: np.ndarray,
    cfg: PadRenderConfig,
    detection: dict[str, object] | None,
) -> np.ndarray:
    output = frame.copy()
    cv2.drawMarker(
        output,
        (IMG_W // 2, IMG_H // 2),
        (0, 255, 255),
        cv2.MARKER_CROSS,
        28,
        2,
    )

    if detection and detection.get("detected"):
        for corner in detection.get("corners", []):
            pts = np.asarray(corner, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(output, [pts], True, (0, 255, 0), 2)
        centroid_x_px = int(float(detection.get("centroid_x_px", IMG_W // 2)))
        centroid_y_px = int(float(detection.get("centroid_y_px", IMG_H // 2)))
        cv2.drawMarker(
            output,
            (centroid_x_px, centroid_y_px),
            (0, 0, 255),
            cv2.MARKER_CROSS,
            24,
            2,
        )
        cv2.line(
            output,
            (IMG_W // 2, IMG_H // 2),
            (centroid_x_px, centroid_y_px),
            (0, 165, 255),
            2,
        )

    confidence = float(detection.get("confidence", 0.0)) if detection else 0.0
    status = "DETECTED" if confidence > 0.0 else "SEARCHING"
    status_color = (0, 255, 0) if confidence > 0.0 else (0, 100, 255)
    cv2.putText(
        output,
        f"ALT: {cfg.altitude_m:.2f} m",
        (10, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
    )
    cv2.putText(
        output,
        f"OFF: ({cfg.offset_x_m:.2f}, {cfg.offset_y_m:.2f}) m",
        (10, 44),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
    )
    cv2.putText(
        output,
        f"{status} conf={confidence:.2f}",
        (10, 66),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        status_color,
        2,
    )
    return output
