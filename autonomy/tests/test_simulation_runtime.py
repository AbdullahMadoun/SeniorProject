from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.simulation_runtime import (
    resolve_runner_python,
    resolve_simulation_runtime_paths,
    should_bootstrap_linux,
)


class SimulationRuntimeTests(unittest.TestCase):
    def test_resolve_runner_python_prefers_linux_autonomy_venv(self) -> None:
        runtime_paths = resolve_simulation_runtime_paths(repo_root=Path("C:/repo"))
        linux_python = runtime_paths.autonomy_root / ".venv" / "bin" / "python"
        path_type = type(linux_python)

        with patch.object(path_type, "exists", autospec=True) as exists_mock:
            exists_mock.side_effect = lambda path: path == linux_python
            self.assertEqual(resolve_runner_python(runtime_paths), linux_python)

    def test_should_bootstrap_linux_when_px4_build_is_missing(self) -> None:
        runtime_paths = resolve_simulation_runtime_paths(repo_root=Path("C:/repo"))
        path_type = type(runtime_paths.px4_repo)

        with (
            patch.object(path_type, "is_dir", autospec=True) as is_dir_mock,
            patch.object(path_type, "exists", autospec=True) as exists_mock,
        ):
            is_dir_mock.side_effect = lambda path: path == runtime_paths.px4_repo
            exists_mock.side_effect = lambda path: False
            self.assertTrue(should_bootstrap_linux(runtime_paths))

    def test_should_not_bootstrap_linux_when_px4_build_is_ready(self) -> None:
        runtime_paths = resolve_simulation_runtime_paths(repo_root=Path("C:/repo"))
        path_type = type(runtime_paths.px4_repo)

        with (
            patch.object(path_type, "is_dir", autospec=True) as is_dir_mock,
            patch.object(path_type, "exists", autospec=True) as exists_mock,
        ):
            is_dir_mock.side_effect = lambda path: path == runtime_paths.px4_repo
            exists_mock.side_effect = lambda path: path in {runtime_paths.px4_binary, runtime_paths.gz_env_path}
            self.assertFalse(should_bootstrap_linux(runtime_paths))


if __name__ == "__main__":
    unittest.main()
