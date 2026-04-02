from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


AUTONOMY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.companion.run_companion_smoke import run_smoke


class CompanionSmokeRunnerTests(unittest.TestCase):
    def test_smoke_runner_builds_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            manifest = run_smoke(output_dir=output_dir)

            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "summary.md").exists())
            self.assertEqual(manifest["modules"]["video_logger"]["processed_frames"], 5)
            self.assertEqual(manifest["modules"]["aruco_detector"]["detection_count"], 1)
            self.assertTrue(manifest["modules"]["gpio_charging"]["decisions"][0]["charge_enabled"])
            self.assertEqual(manifest["modules"]["yolo_stub"]["detection_count"], 3)


if __name__ == "__main__":
    unittest.main()
