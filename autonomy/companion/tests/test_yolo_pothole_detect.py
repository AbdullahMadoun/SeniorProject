from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.yolo_pothole_detect import DummyYoloPotholeDetector


class DummyYoloTests(unittest.TestCase):
    def test_dummy_detector_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            detector = DummyYoloPotholeDetector(output_dir=Path(tmp))
            result = detector.run(["frame-a", "frame-b"])

            csv_path = Path(result["csv_path"])
            self.assertTrue(csv_path.exists())
            with csv_path.open("r", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["label"], "pothole")


if __name__ == "__main__":
    unittest.main()
