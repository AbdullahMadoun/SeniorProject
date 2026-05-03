from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.scenario_runner import run_scenarios_to_directory


class ScenarioRunnerTests(unittest.TestCase):
    def test_run_scenarios_writes_manifest_and_summary(self) -> None:
        baseline = load_system_baseline()
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = run_scenarios_to_directory(baseline, tmp_dir)
            manifest = json.loads((Path(output_dir) / "manifest.json").read_text(encoding="utf-8"))
            summary = (Path(output_dir) / "summary.md").read_text(encoding="utf-8")

            self.assertEqual(manifest["scenario_count"], 3)
            self.assertEqual(manifest["passed_count"], 3)
            self.assertIn("nominal_preflight_ready", summary)
            self.assertIn("low_battery_rtl", summary)


if __name__ == "__main__":
    unittest.main()
