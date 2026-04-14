from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SCRIPT_ROOT = Path(__file__).resolve().parent


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError(f"Expected YAML object at {path}, got {type(payload).__name__}")
    return payload


def dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resolve_workspace_path(workspace: Path, value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw.resolve()
    return (workspace / raw).resolve()


def ensure_manifest(manifest_path: Path, workspace: Path) -> dict[str, Any]:
    if manifest_path.exists():
        payload = load_json(manifest_path)
    else:
        payload = {"workspace": str(workspace), "runs": []}
    payload.setdefault("workspace", str(workspace))
    payload.setdefault("runs", [])
    return payload


def upsert_manifest_run(manifest_path: Path, workspace: Path, run_info: dict[str, Any]) -> None:
    manifest = ensure_manifest(manifest_path, workspace)
    runs = [run for run in manifest.get("runs", []) if run.get("name") != run_info.get("name")]
    runs.append(run_info)
    manifest["runs"] = runs
    dump_json(manifest_path, manifest)


def summarize_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = load_json(manifest_path)
    runs = payload.get("runs", [])
    completed = [run for run in runs if run.get("status") == "completed"]
    skipped = [run for run in runs if run.get("status", "").startswith("skipped")]
    failed = [run for run in runs if run.get("status") == "failed"]
    return {
        "workspace": payload.get("workspace"),
        "run_count": len(runs),
        "completed": len(completed),
        "skipped": len(skipped),
        "failed": len(failed),
        "runs": runs,
    }


def repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def git_head(root: Path | None) -> str | None:
    if root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def git_status_short(root: Path | None) -> list[str]:
    if root is None:
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def collect_runtime_context(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }

    try:
        import torch

        context["torch_version"] = getattr(torch, "__version__", None)
        context["cuda_available"] = bool(torch.cuda.is_available())
        context["cuda_device_count"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
        if torch.cuda.is_available():
            context["cuda_devices"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except Exception:
        context["torch_version"] = None
        context["cuda_available"] = None
        context["cuda_device_count"] = None

    try:
        import ultralytics
        from ultralytics import settings

        context["ultralytics_version"] = getattr(ultralytics, "__version__", None)
        context["ultralytics_settings"] = {
            "tensorboard": settings.get("tensorboard"),
            "mlflow": settings.get("mlflow"),
        }
    except Exception:
        context["ultralytics_version"] = None
        context["ultralytics_settings"] = {}

    root = repo_root(SCRIPT_ROOT)
    context["repo_root"] = str(root) if root else None
    context["git_head"] = git_head(root)
    context["git_status_short"] = git_status_short(root)

    if extra:
        context.update(extra)
    return context
