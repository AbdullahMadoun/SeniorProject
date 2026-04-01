from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.scripts.check_runtime_readiness import _normalize, _wsl_path


class RuntimeReadinessHelpersTests(unittest.TestCase):
    def test_normalize_compacts_whitespace_and_nulls(self) -> None:
        self.assertEqual(_normalize("Ubuntu\x00  Running \n 2 "), "Ubuntu  Running \n 2")

    def test_wsl_path_converts_drive_and_separators(self) -> None:
        path = Path(r"D:\downloads\SeniorProject\Skylink2\vendor\PX4-Autopilot")
        self.assertEqual(
            _wsl_path(path),
            "/mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot",
        )


if __name__ == "__main__":
    unittest.main()
