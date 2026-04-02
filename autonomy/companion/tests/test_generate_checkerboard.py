from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.generate_checkerboard import generate_checkerboard


class CheckerboardGenerationTests(unittest.TestCase):
    def test_checkerboard_generator_writes_svg_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            result = generate_checkerboard(output_dir=output_dir, inner_corners_cols=9, inner_corners_rows=6)

            self.assertTrue((output_dir / "checkerboard.svg").exists())
            self.assertTrue((output_dir / "checkerboard.json").exists())
            self.assertEqual(result["inner_corners_cols"], 9)
            self.assertEqual(result["inner_corners_rows"], 6)


if __name__ == "__main__":
    unittest.main()

