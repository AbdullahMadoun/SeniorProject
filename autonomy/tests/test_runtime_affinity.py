from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system import runtime_affinity


class _FakeProcess:
    def __init__(self, pid: int = 1234) -> None:
        self.pid = pid
        self.calls: list[list[int]] = []

    def cpu_affinity(self, cores: list[int]) -> None:
        self.calls.append(list(cores))


class RuntimeAffinityTests(unittest.TestCase):
    def test_parse_cpu_cores_normalizes_comma_separated_values(self) -> None:
        self.assertEqual(runtime_affinity.parse_cpu_cores("2, 3,3,-1,abc"), [2, 3])

    def test_enforce_cpu_affinity_applies_allowed_cores(self) -> None:
        fake_process = _FakeProcess(pid=987)
        fake_psutil = type("FakePsutil", (), {"Process": lambda self, pid: fake_process})()
        with patch.object(runtime_affinity, "psutil", fake_psutil), patch.object(runtime_affinity.os, "cpu_count", return_value=8):
            result = runtime_affinity.enforce_cpu_affinity([2, 3], pid=987, label="validator")

        self.assertTrue(result["applied"])
        self.assertEqual(fake_process.calls, [[2, 3]])
        self.assertEqual(result["pid"], 987)

    def test_enforce_cpu_affinity_gracefully_falls_back_when_psutil_is_unavailable(self) -> None:
        with patch.object(runtime_affinity, "psutil", None):
            result = runtime_affinity.enforce_cpu_affinity([0], label="mission_api")

        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "psutil_unavailable")


if __name__ == "__main__":
    unittest.main()
