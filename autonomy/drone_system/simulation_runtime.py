from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

PX4_REF = "v1.14.3"
PX4_REPO_URL = "https://github.com/PX4/PX4-Autopilot.git"


@dataclass(frozen=True)
class SimulationRuntimePaths:
    repo_root: Path
    autonomy_root: Path
    px4_repo: Path
    px4_binary: Path
    gz_env_path: Path
    wind_template_path: Path
    bootstrap_script: Path


def resolve_simulation_runtime_paths(*, repo_root: Path | None = None) -> SimulationRuntimePaths:
    resolved_repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    autonomy_root = resolved_repo_root / "autonomy"
    px4_repo = resolved_repo_root / "vendor" / "PX4-Autopilot"
    return SimulationRuntimePaths(
        repo_root=resolved_repo_root,
        autonomy_root=autonomy_root,
        px4_repo=px4_repo,
        px4_binary=px4_repo / "build" / "px4_sitl_default" / "bin" / "px4",
        gz_env_path=px4_repo / "build" / "px4_sitl_default" / "rootfs" / "gz_env.sh",
        wind_template_path=px4_repo / "Tools" / "simulation" / "gz" / "worlds" / "default.sdf",
        bootstrap_script=resolved_repo_root / "deploy" / "simulation" / "bootstrap_remote.sh",
    )


def resolve_runner_python(
    runtime_paths: SimulationRuntimePaths,
    *,
    fallback: str | Path | None = None,
) -> Path:
    candidates = (
        runtime_paths.autonomy_root / ".venv" / "Scripts" / "python.exe",
        runtime_paths.autonomy_root / ".venv" / "bin" / "python",
        runtime_paths.repo_root / ".venv" / "Scripts" / "python.exe",
        runtime_paths.repo_root / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if fallback is not None:
        return Path(fallback)
    return Path(sys.executable)


def runtime_host_mode() -> str:
    return "windows_wsl" if os.name == "nt" else "linux"


def should_bootstrap_linux(runtime_paths: SimulationRuntimePaths) -> bool:
    return not (
        runtime_paths.px4_repo.is_dir()
        and runtime_paths.px4_binary.exists()
        and runtime_paths.gz_env_path.exists()
    )
