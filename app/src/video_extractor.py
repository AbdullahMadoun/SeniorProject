"""
SkyLink — Video-to-Frame Extractor
====================================
Converts a drone inspection video into a clean, non-overlapping set of frames
suitable for YOLO crack detection.

How it works (Kinematic Approach):
  The drone camera covers a ground strip whose width depends on the drone's
  altitude and the camera's horizontal Field of View (FOV).  The extractor
  calculates how many seconds the drone takes to travel exactly that width
  at its cruise speed, then samples the video at that interval.  The result
  is one frame per unique, non-overlapping ground patch.

Overlap control:
  An ``overlap_fraction`` parameter (0.0 – <1.0) lets you retain a small
  controlled overlap between consecutive frames so that cracks sitting exactly
  on a boundary are never missed.  The default of 0.10 (10 %) is recommended
  for judge demonstrations.

Usage (CLI):
  python src/video_extractor.py --video path/to/drone.mp4 \\
      --speed 5.0 --altitude 10.0 --fov 82.6

Usage (import):
  from src.video_extractor import extract_frames, DroneParams
"""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import cv2
import imagehash
from PIL import Image


# ---------------------------------------------------------------------------
# Default paths (relative to the app/ root, same convention as the rest of the
# SkyLink app stack)
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO_DIR = ROOT_DIR / "data" / "videos"
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DroneParams:
    """All physical parameters that govern the extraction interval.

    Attributes
    ----------
    speed_mps : float
        Drone horizontal cruise speed in **metres per second**.
        Typical SkyLink value: 3–7 m/s (from system_baseline.md).
    altitude_m : float
        Drone altitude above ground in **metres**.
        Typical inspection altitude: 8–15 m.
    hfov_deg : float
        Camera **horizontal** Field of View in **degrees**.
        Common drone cameras:
          • DJI Mini 3 Pro: 82.1°
          • GoPro Hero 12: 122°
          • Generic fisheye:  ~120°
          • Generic narrow:   60°
    overlap_fraction : float
        Fraction of the ground patch that *intentionally* overlaps with the
        next frame. Default 0.10 (10 %). Must be in [0.0, 0.9) — values at
        or above 0.9 would reduce the unique ground step to less than 10 % of
        the footprint, producing an excessive number of nearly-identical frames.
    """

    speed_mps: float = 5.0
    altitude_m: float = 10.0
    hfov_deg: float = 82.6
    overlap_fraction: float = 0.10

    # Maximum sensible overlap — enforced consistently in validation AND tests.
    _MAX_OVERLAP: float = 0.9  # class-level constant (not a field)

    def __post_init__(self) -> None:
        if self.speed_mps <= 0:
            raise ValueError(f"speed_mps must be > 0, got {self.speed_mps}")
        if self.altitude_m <= 0:
            raise ValueError(f"altitude_m must be > 0, got {self.altitude_m}")
        if not (0 < self.hfov_deg < 180):
            raise ValueError(f"hfov_deg must be in (0, 180), got {self.hfov_deg}")
        # Cap at 0.9 — consistent with docstring and test expectations.
        if not (0.0 <= self.overlap_fraction < 0.9):
            raise ValueError(
                f"overlap_fraction must be in [0.0, 0.9), got {self.overlap_fraction}. "
                "Values >= 0.9 produce excessive near-duplicate frames."
            )


# ---------------------------------------------------------------------------
# Core kinematics
# ---------------------------------------------------------------------------

def compute_ground_footprint_width(altitude_m: float, hfov_deg: float) -> float:
    """Calculate the horizontal ground-patch width (metres) visible to the camera.

    Uses the standard pinhole camera model:

        width = 2 * altitude * tan(hfov / 2)

    Parameters
    ----------
    altitude_m:
        Drone height above ground in metres.
    hfov_deg:
        Camera horizontal FOV in degrees.

    Returns
    -------
    float
        Width of the ground strip captured in a single frame, in metres.
    """
    half_angle_rad = math.radians(hfov_deg / 2.0)
    return 2.0 * altitude_m * math.tan(half_angle_rad)


def compute_capture_interval(params: DroneParams) -> float:
    """Return the time interval (seconds) between frame captures.

    The interval is chosen so that consecutive frames cover adjacent,
    non-overlapping ground patches (minus a controlled overlap margin).

    Formula
    -------
        footprint  = 2 × altitude × tan(hfov / 2)          [metres]
        step       = footprint × (1 − overlap_fraction)     [metres]
        interval   = step / speed                           [seconds]

    Parameters
    ----------
    params:
        Drone physical parameters.

    Returns
    -------
    float
        Capture interval in seconds.
    """
    footprint = compute_ground_footprint_width(params.altitude_m, params.hfov_deg)
    step_m = footprint * (1.0 - params.overlap_fraction)
    interval_s = step_m / params.speed_mps
    return interval_s


def _compute_frame_hash(frame: cv2.typing.MatLike, hash_size: int = 8) -> imagehash.ImageHash:
    """Compute the Difference Hash (dHash) for a frame.
    dHash is more robust for sequential motion than regular average hashing.
    """
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    return imagehash.dhash(pil_img, hash_size=hash_size)


def _compute_blur_variance(frame: cv2.typing.MatLike) -> float:
    """Compute the Laplacian variance to detect motion blur."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _hamming_distance(hash_a: imagehash.ImageHash, hash_b: imagehash.ImageHash) -> int:
    return int(hash_a - hash_b)


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------

def extract_frames(
    video_path: str | Path,
    output_dir: str | Path,
    params: DroneParams,
    *,
    image_format: str = "jpg",
    jpeg_quality: int = 95,
    max_frames: int | None = None,
    dedup_hamming_threshold: int | None = 8,
    blur_threshold: float | None = 80.0,
    verbose: bool = True,
) -> List[Path]:
    # Validate jpeg_quality early so the error is clear before we open the video.
    if not (1 <= jpeg_quality <= 100):
        raise ValueError(f"jpeg_quality must be 1–100, got {jpeg_quality}")
    """Extract non-overlapping frames from a drone video.

    Parameters
    ----------
    video_path:
        Path to the input video (mp4, avi, mov, mkv, …).
    output_dir:
        Directory where extracted frames will be saved.
        Will be created if it does not exist.
    params:
        Drone kinematic parameters (speed, altitude, FOV, overlap).
    image_format:
        Output image format. Supports ``"jpg"`` or ``"png"``.
    jpeg_quality:
        JPEG compression quality 1–100.  Only used when *image_format* is
        ``"jpg"``.
    max_frames:
        Hard limit on the number of frames to extract. ``None`` = no limit.
    verbose:
        Print progress information to stdout.

    Returns
    -------
    List[Path]
        Sorted list of paths to all saved frames.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Open the video and collect basic metadata
    # ------------------------------------------------------------------
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(
            f"OpenCV could not open the video file: {video_path}\n"
            "Make sure the file is a supported format (mp4, avi, mov, mkv)."
        )

    video_fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration_s: float = total_frames / video_fps

    # ------------------------------------------------------------------
    # Kinematic calculation
    # ------------------------------------------------------------------
    interval_s = compute_capture_interval(params)
    interval_frames = max(1, int(round(interval_s * video_fps)))
    footprint_m = compute_ground_footprint_width(params.altitude_m, params.hfov_deg)
    step_m = footprint_m * (1.0 - params.overlap_fraction)

    # Estimate how many unique frames we will produce
    estimated_count = max(1, int(math.ceil(video_duration_s / interval_s)))
    if max_frames is not None:
        estimated_count = min(estimated_count, max_frames)

    if verbose:
        _print_summary_header(
            video_path, params, video_fps, total_frames,
            video_duration_s, footprint_m, step_m,
            interval_s, interval_frames, estimated_count,
        )

    # ------------------------------------------------------------------
    # Extraction loop
    # ------------------------------------------------------------------
    saved_paths: List[Path] = []
    frame_idx = 0        # current frame position inside the video
    capture_count = 0    # number of frames we have saved
    accepted_hash: imagehash.ImageHash | None = None
    ext = image_format.lstrip(".")
    stem = video_path.stem

    encode_params: list = []
    if ext in ("jpg", "jpeg"):
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]

    t_start = time.perf_counter()

    # Wrap the loop in try/finally so cap.release() is ALWAYS called,
    # even if cv2.imwrite raises an OSError (e.g. disk full).
    try:
        while True:
            # Seek directly to the target frame (much faster than reading every frame)
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_idx))
            ret, frame = cap.read()

            if not ret:
                # End of video or read error — clean exit
                break

            # Stage 3: Laplacian Blur Filter (Optional)
            if blur_threshold is not None and blur_threshold >= 0:
                blur_var = _compute_blur_variance(frame)
                if blur_var < blur_threshold:
                    if verbose:
                        timestamp_s = frame_idx / video_fps
                        mm = int(timestamp_s // 60)
                        ss = timestamp_s % 60
                        print(f"  [SKIP] Blurry frame @{mm:02d}:{ss:05.2f} (variance {blur_var:.1f} < {blur_threshold})")

                    # Fallback: if this is the only potential frame (short video) and it's blurry,
                    # we keep it anyway if we have nothing else, OR we just let the loop continue
                    # but we'll add a final catch-all after the loop.
                    frame_idx += interval_frames
                    continue

            # Stage 2: Perceptual Hash Gating
            if dedup_hamming_threshold is not None and dedup_hamming_threshold >= 0:
                frame_hash = _compute_frame_hash(frame)
                if accepted_hash is not None:
                    dist = _hamming_distance(accepted_hash, frame_hash)
                    if dist < dedup_hamming_threshold:
                        if verbose:
                            timestamp_s = frame_idx / video_fps
                            mm = int(timestamp_s // 60)
                            ss = timestamp_s % 60
                            print(
                                f"  [SKIP] Near-duplicate frame @{mm:02d}:{ss:05.2f} "
                                f"(hash distance {dist} < {dedup_hamming_threshold})"
                            )
                        frame_idx += interval_frames
                        continue
            else:
                frame_hash = None

            filename = f"{stem}_frame{capture_count:05d}.{ext}"
            dest = output_dir / filename

            success = cv2.imwrite(str(dest), frame, encode_params)
            if not success:
                # imwrite returns False when it cannot write (bad path, wrong codec, etc.)
                raise RuntimeError(
                    f"cv2.imwrite failed for {dest}. "
                    "Check that the output directory is writable and the format is supported."
                )

            saved_paths.append(dest)
            capture_count += 1
            if frame_hash is not None:
                accepted_hash = frame_hash

            if verbose:
                timestamp_s = frame_idx / video_fps
                _print_frame_progress(capture_count, estimated_count, timestamp_s, dest.name)

            if max_frames is not None and capture_count >= max_frames:
                if verbose:
                    print(f"\n  [LIMIT] Reached max_frames={max_frames}, stopping early.")
                break

            frame_idx += interval_frames

    finally:
        # Final safety check: if we saved 0 frames (due to aggressive filtering or very short video),
        # take the FIRST frame regardless of blur/duplicates.
        if not saved_paths and total_frames > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0.0)
            ret, frame = cap.read()
            if ret:
                filename = f"{stem}_frame00000_fallback.{ext}"
                dest = output_dir / filename
                cv2.imwrite(str(dest), frame, encode_params)
                saved_paths.append(dest)
                if verbose:
                    print(f"\n  [FALLBACK] Saved first frame as safety (all filters were too strict).")

        # Always release the VideoCapture, regardless of exceptions.
        cap.release()

    elapsed = time.perf_counter() - t_start

    if verbose:
        _print_summary_footer(capture_count, output_dir, elapsed)

    return sorted(saved_paths)


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def _print_summary_header(
    video_path: Path,
    params: DroneParams,
    video_fps: float,
    total_frames: int,
    duration_s: float,
    footprint_m: float,
    step_m: float,
    interval_s: float,
    interval_frames: int,
    estimated_count: int,
) -> None:
    print("=" * 62)
    print("  SkyLink — Video Frame Extractor")
    print("=" * 62)
    print(f"  Input video   : {video_path.name}")
    print(f"  Video FPS     : {video_fps:.2f}")
    print(f"  Total frames  : {total_frames}")
    print(f"  Duration      : {duration_s:.1f} s  ({duration_s/60:.1f} min)")
    print("-" * 62)
    print("  DRONE KINEMATICS")
    print(f"  Cruise speed  : {params.speed_mps} m/s")
    print(f"  Altitude      : {params.altitude_m} m AGL")
    print(f"  Camera H-FOV  : {params.hfov_deg}°")
    print(f"  Ground patch  : {footprint_m:.2f} m  (per frame)")
    print(f"  Overlap       : {params.overlap_fraction * 100:.0f}%")
    print(f"  Step per frame: {step_m:.2f} m  (unique new ground)")
    print("-" * 62)
    print("  EXTRACTION PLAN")
    print(f"  Capture every : {interval_s:.2f} s  ({interval_frames} frames)")
    print(f"  Est. output   : ~{estimated_count} unique frames")
    print("=" * 62)


def _print_frame_progress(
    count: int,
    estimated: int,
    timestamp_s: float,
    filename: str,
) -> None:
    pct = min(100.0, count / max(estimated, 1) * 100)
    mm = int(timestamp_s // 60)
    ss = timestamp_s % 60
    print(f"  [{count:4d}/{estimated}] {pct:5.1f}%  @{mm:02d}:{ss:05.2f}  → {filename}")


def _print_summary_footer(count: int, output_dir: Path, elapsed: float) -> None:
    print("=" * 62)
    print(f"  Done! Extracted {count} frames in {elapsed:.2f} s")
    print(f"  Saved to: {output_dir}")
    print("  Next step: run the AI pipeline")
    print("    python src/main.py --conf-threshold 0.25")
    print("  Or open the dashboard:")
    print("    streamlit run src/dashboard.py")
    print("=" * 62)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SkyLink — Extract non-overlapping frames from a drone video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Drone flying at 5 m/s, 10 m altitude, 82.6° FOV (DJI-style), 10% overlap
  python src/video_extractor.py --video data/videos/road.mp4 \\
      --speed 5.0 --altitude 10.0 --fov 82.6

  # Slower drone (3 m/s), higher altitude (15 m), 0% overlap, save as PNG
  python src/video_extractor.py --video data/videos/road.mp4 \\
      --speed 3.0 --altitude 15.0 --fov 82.6 --overlap 0.0 --format png

  # Limit extraction to the first 50 frames (quick smoke test)
  python src/video_extractor.py --video data/videos/road.mp4 \\
      --speed 5.0 --altitude 10.0 --fov 82.6 --max-frames 50
        """,
    )

    parser.add_argument(
        "--video",
        type=Path,
        required=True,
        help="Path to the input drone video (mp4, avi, mov, mkv).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"Directory to save extracted frames. Default: {DEFAULT_RAW_DIR}",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=5.0,
        metavar="M/S",
        help="Drone horizontal cruise speed in m/s. Default: 5.0",
    )
    parser.add_argument(
        "--altitude",
        type=float,
        default=10.0,
        metavar="METRES",
        help="Drone altitude above ground in metres. Default: 10.0",
    )
    parser.add_argument(
        "--fov",
        type=float,
        default=82.6,
        metavar="DEGREES",
        help="Camera horizontal FOV in degrees. Default: 82.6 (DJI-style). "
             "GoPro wide ≈ 122°, narrow ≈ 60°.",
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=0.10,
        metavar="FRACTION",
        help="Intentional overlap fraction between consecutive frames [0.0, 0.9). "
             "Default: 0.10 (10%%).",
    )
    parser.add_argument(
        "--format",
        choices=["jpg", "png"],
        default="jpg",
        dest="image_format",
        help="Output image format. Default: jpg",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=95,
        metavar="1-100",
        help="JPEG quality (only used with --format jpg). Default: 95",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        metavar="N",
        help="Hard limit on extracted frames. Useful for quick tests.",
    )
    parser.add_argument(
        "--dedup-distance",
        type=int,
        default=4,
        metavar="HAMMING",
        help="Perceptual dedupe distance against the last accepted frame. Negative disables visual dedupe.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        params = DroneParams(
            speed_mps=args.speed,
            altitude_m=args.altitude,
            hfov_deg=args.fov,
            overlap_fraction=args.overlap,
        )
    except ValueError as exc:
        raise SystemExit(f"[ERROR] Invalid drone parameters: {exc}") from exc

    try:
        saved = extract_frames(
            video_path=args.video,
            output_dir=args.output_dir,
            params=params,
            image_format=args.image_format,
            jpeg_quality=args.quality,
            max_frames=args.max_frames,
            dedup_hamming_threshold=(None if args.dedup_distance < 0 else args.dedup_distance),
            verbose=not args.quiet,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc

    if not args.quiet:
        print(f"\n  {len(saved)} frame(s) ready in: {args.output_dir}")


if __name__ == "__main__":
    main()
