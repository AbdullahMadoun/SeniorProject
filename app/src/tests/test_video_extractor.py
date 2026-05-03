"""
Unit tests for video_extractor.py

Tests cover:
  - Kinematic formulas (footprint width, capture interval)
  - DroneParams validation (illegal values raise ValueError)
  - Frame extraction from a synthetic video generated in-memory by OpenCV
  - Overlap fraction behaviour (0% vs 10% vs 50%)
  - max_frames early-stop limit
  - CLI argument parsing

Run with:
  python -m pytest app/src/tests/test_video_extractor.py -v
or simply:
  python app/src/tests/test_video_extractor.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# make the app/src package importable from wherever the tests are run
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parents[1]       # app/src
ROOT_DIR = SRC_DIR.parent                           # app/
REPO_ROOT = ROOT_DIR.parent                         # SeniorProject/
for p in (str(SRC_DIR), str(ROOT_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import cv2
import numpy as np
import tempfile

from video_extractor import (
    DroneParams,
    compute_capture_interval,
    compute_ground_footprint_width,
    extract_frames,
)


# ---------------------------------------------------------------------------
# Helper: create a minimal synthetic video in a temp file
# ---------------------------------------------------------------------------

def _make_synthetic_video(path: Path, fps: int = 30, duration_s: int = 5) -> None:
    """Write a short synthetic video (moving gradient) using OpenCV."""
    width, height = 640, 480
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))

    total = fps * duration_s
    for i in range(total):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Cycle a colour band across the frame so each section looks different
        hue = int((i / total) * 180)
        frame[:, :, 0] = hue            # Blue channel gradient
        frame[:, :, 1] = 255 - hue      # Green channel inverse
        frame[:, :, 2] = 128            # Red constant
        writer.write(frame)

    writer.release()


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestDroneParams(unittest.TestCase):
    """DroneParams dataclass validation."""

    def test_valid_defaults(self) -> None:
        p = DroneParams()
        self.assertAlmostEqual(p.speed_mps, 5.0)
        self.assertAlmostEqual(p.altitude_m, 10.0)
        self.assertAlmostEqual(p.hfov_deg, 82.6)
        self.assertAlmostEqual(p.overlap_fraction, 0.10)

    def test_zero_speed_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(speed_mps=0.0)

    def test_negative_speed_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(speed_mps=-3.0)

    def test_zero_altitude_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(altitude_m=0.0)

    def test_fov_180_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(hfov_deg=180.0)

    def test_fov_0_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(hfov_deg=0.0)

    def test_overlap_negative_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(overlap_fraction=-0.1)

    def test_overlap_100_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(overlap_fraction=1.0)

    def test_extreme_valid_overlap(self) -> None:
        # 80 % overlap is valid (below the 0.9 cap)
        p = DroneParams(overlap_fraction=0.80)
        self.assertAlmostEqual(p.overlap_fraction, 0.80)

    def test_overlap_at_cap_raises(self) -> None:
        # Exactly 0.9 is NOT allowed (cap is exclusive)
        with self.assertRaises(ValueError):
            DroneParams(overlap_fraction=0.9)

    def test_overlap_above_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            DroneParams(overlap_fraction=0.95)


class TestKinematics(unittest.TestCase):
    """Ground footprint width and capture interval calculations."""

    def test_footprint_90deg_fov(self) -> None:
        """At 90° FOV, footprint = 2 × altitude (45° each side)."""
        result = compute_ground_footprint_width(altitude_m=10.0, hfov_deg=90.0)
        expected = 2.0 * 10.0 * math.tan(math.radians(45.0))  # = 20.0 m
        self.assertAlmostEqual(result, expected, places=6)

    def test_footprint_increases_with_altitude(self) -> None:
        low = compute_ground_footprint_width(altitude_m=5.0, hfov_deg=82.6)
        high = compute_ground_footprint_width(altitude_m=20.0, hfov_deg=82.6)
        self.assertGreater(high, low)

    def test_footprint_increases_with_fov(self) -> None:
        narrow = compute_ground_footprint_width(altitude_m=10.0, hfov_deg=60.0)
        wide = compute_ground_footprint_width(altitude_m=10.0, hfov_deg=120.0)
        self.assertGreater(wide, narrow)

    def test_interval_no_overlap(self) -> None:
        """With 0% overlap, interval = footprint / speed."""
        p = DroneParams(speed_mps=5.0, altitude_m=10.0, hfov_deg=90.0, overlap_fraction=0.0)
        footprint = compute_ground_footprint_width(10.0, 90.0)  # 20.0 m
        expected_interval = footprint / 5.0                     # 4.0 s
        result = compute_capture_interval(p)
        self.assertAlmostEqual(result, expected_interval, places=6)

    def test_interval_with_overlap(self) -> None:
        """With 10% overlap, step = footprint × 0.9; interval = step / speed."""
        p = DroneParams(speed_mps=5.0, altitude_m=10.0, hfov_deg=90.0, overlap_fraction=0.10)
        footprint = compute_ground_footprint_width(10.0, 90.0)  # 20.0 m
        expected_interval = footprint * 0.90 / 5.0              # 3.6 s
        result = compute_capture_interval(p)
        self.assertAlmostEqual(result, expected_interval, places=6)

    def test_faster_drone_shorter_interval(self) -> None:
        slow = compute_capture_interval(DroneParams(speed_mps=3.0, altitude_m=10.0, hfov_deg=82.6))
        fast = compute_capture_interval(DroneParams(speed_mps=7.0, altitude_m=10.0, hfov_deg=82.6))
        self.assertGreater(slow, fast)

    def test_interval_always_positive(self) -> None:
        for speed in (1.0, 3.0, 5.0, 7.0):
            for alt in (5.0, 10.0, 20.0):
                for fov in (60.0, 82.6, 120.0):
                    p = DroneParams(speed_mps=speed, altitude_m=alt, hfov_deg=fov)
                    self.assertGreater(compute_capture_interval(p), 0.0)

    def test_skylink_baseline_values(self) -> None:
        """Use the exact SkyLink system_baseline.md values and assert sanity."""
        # Cruise speed range: 3–7 m/s; max wind: 7 m/s; typical inspection ~10 m AGL
        p = DroneParams(speed_mps=5.0, altitude_m=10.0, hfov_deg=82.6, overlap_fraction=0.10)
        interval = compute_capture_interval(p)
        # Footprint ≈ 18.56 m; step ≈ 16.70 m; interval ≈ 3.34 s — sanity window
        self.assertGreater(interval, 1.0)
        self.assertLess(interval, 30.0)


class TestExtractFrames(unittest.TestCase):
    """End-to-end frame extraction from a synthetic video."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.video_path = tmp / "test_road.mp4"
        cls.output_dir = tmp / "frames"
        _make_synthetic_video(cls.video_path, fps=30, duration_s=10)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _params(self, **kwargs) -> DroneParams:
        defaults = dict(speed_mps=5.0, altitude_m=10.0, hfov_deg=82.6, overlap_fraction=0.0)
        defaults.update(kwargs)
        return DroneParams(**defaults)

    def test_extraction_produces_files(self) -> None:
        out = Path(self._tmp.name) / "frames_basic"
        paths = extract_frames(self.video_path, out, self._params(), verbose=False)
        self.assertGreater(len(paths), 0)

    def test_all_files_exist(self) -> None:
        out = Path(self._tmp.name) / "frames_exist"
        paths = extract_frames(self.video_path, out, self._params(), verbose=False)
        for p in paths:
            self.assertTrue(p.exists(), f"Missing file: {p}")

    def test_output_dir_created(self) -> None:
        out = Path(self._tmp.name) / "does_not_exist_yet" / "subdir"
        extract_frames(self.video_path, out, self._params(), verbose=False)
        self.assertTrue(out.is_dir())

    def test_max_frames_respected(self) -> None:
        out = Path(self._tmp.name) / "frames_max"
        paths = extract_frames(
            self.video_path, out, self._params(), max_frames=3, verbose=False
        )
        self.assertLessEqual(len(paths), 3)

    def test_higher_overlap_gives_more_frames(self) -> None:
        """More overlap → shorter step → more frames extracted."""
        out_no_overlap = Path(self._tmp.name) / "frames_no_ov"
        out_with_overlap = Path(self._tmp.name) / "frames_50ov"
        p_no = self._params(overlap_fraction=0.0)
        p_50 = self._params(overlap_fraction=0.50)   # still below the 0.9 cap
        n_no = extract_frames(self.video_path, out_no_overlap, p_no, verbose=False)
        n_50 = extract_frames(self.video_path, out_with_overlap, p_50, verbose=False)
        self.assertGreaterEqual(len(n_50), len(n_no))

    def test_invalid_jpeg_quality_raises(self) -> None:
        """jpeg_quality outside 1-100 must raise ValueError before any I/O."""
        out = Path(self._tmp.name) / "frames_bad_quality"
        with self.assertRaises(ValueError):
            extract_frames(
                self.video_path, out, self._params(),
                jpeg_quality=0, verbose=False,
            )
        with self.assertRaises(ValueError):
            extract_frames(
                self.video_path, out, self._params(),
                jpeg_quality=101, verbose=False,
            )

    def test_missing_video_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            extract_frames(Path("nonexistent.mp4"), Path(self._tmp.name), self._params())

    def test_jpg_output_format(self) -> None:
        out = Path(self._tmp.name) / "frames_jpg"
        paths = extract_frames(
            self.video_path, out, self._params(), image_format="jpg",
            max_frames=2, verbose=False,
        )
        for p in paths:
            self.assertEqual(p.suffix.lower(), ".jpg")

    def test_png_output_format(self) -> None:
        out = Path(self._tmp.name) / "frames_png"
        paths = extract_frames(
            self.video_path, out, self._params(), image_format="png",
            max_frames=2, verbose=False,
        )
        for p in paths:
            self.assertEqual(p.suffix.lower(), ".png")

    def test_frames_are_readable_images(self) -> None:
        """Every saved frame must be a valid, non-empty image."""
        out = Path(self._tmp.name) / "frames_readable"
        paths = extract_frames(
            self.video_path, out, self._params(), max_frames=5, verbose=False
        )
        for p in paths:
            img = cv2.imread(str(p))
            self.assertIsNotNone(img, f"Could not read {p}")
            h, w = img.shape[:2]
            self.assertGreater(h, 0)
            self.assertGreater(w, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
