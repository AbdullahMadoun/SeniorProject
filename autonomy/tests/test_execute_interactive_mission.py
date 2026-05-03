from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.scripts import execute_interactive_mission


class ExecuteInteractiveMissionTests(unittest.TestCase):
    def test_main_applies_execution_cpu_affinity_before_async_run(self) -> None:
        mission_spec = Path("D:/downloads/SeniorProject/Skylink2/artifacts/planner/job_cache/test/mission_request.json")
        captured: dict[str, object] = {}

        def _fake_run(coro) -> None:
            captured["coro"] = coro
            coro.close()

        with (
            patch.object(execute_interactive_mission, "enforce_cpu_affinity") as enforce_mock,
            patch.object(execute_interactive_mission.asyncio, "run", side_effect=_fake_run) as run_mock,
            patch.object(execute_interactive_mission, "main_async", return_value=object()) as main_async_mock,
        ):
            execute_interactive_mission.main(["--mission-spec", str(mission_spec), "--cpu-cores", "2,3"])

        enforce_mock.assert_called_once_with([2, 3], label="execute_interactive_mission")
        self.assertEqual(main_async_mock.call_args.args[0], mission_spec)
        run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
