from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from guide_utils import (
    SCRIPT_ROOT,
    collect_runtime_context,
    dump_json,
    load_json,
    load_yaml,
    resolve_workspace_path,
    summarize_manifest,
    upsert_manifest_run,
)


RESERVED_KEYS = {
    "trainer",
    "optional",
    "notes",
    "display_name",
    "command",
    "workdir",
    "required_paths",
    "_config_path",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a single guide-defined model config.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--data-override", default="", help="Optional dataset YAML override, absolute or workspace-relative.")
    parser.add_argument("--project-override", default="", help="Optional run project override, absolute or workspace-relative.")
    parser.add_argument("--name-suffix", default="", help="Optional suffix appended to the configured run name.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-missing-optional", action="store_true")
    parser.add_argument("--cache", choices=["inherit", "ram", "disk", "off"], default="inherit")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--batch-auto", action="store_true")
    parser.add_argument("--multi-scale", action="store_true")
    parser.add_argument("--enable-mlflow", action="store_true")
    parser.add_argument("--disable-mlflow", action="store_true")
    parser.add_argument("--enable-tensorboard", action="store_true")
    parser.add_argument("--disable-tensorboard", action="store_true")
    parser.add_argument("--run-tag", default="", help="Optional label to record in run metadata.")
    return parser.parse_args()


def resolve_config_path(config_arg: str) -> Path:
    config_path = Path(config_arg)
    if config_path.is_absolute():
        return config_path.resolve()
    return (SCRIPT_ROOT / config_path).resolve()


def resolve_training_kwargs(config: dict[str, Any], workspace: Path, device: str, workers: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key, value in config.items():
        if key in RESERVED_KEYS:
            continue
        kwargs[key] = value
    kwargs["data"] = str(resolve_workspace_path(workspace, kwargs.get("data", "configs/dataset.yaml")))
    kwargs["project"] = str(resolve_workspace_path(workspace, kwargs.get("project", "runs")))
    kwargs["device"] = kwargs.get("device", device)
    kwargs["workers"] = kwargs.get("workers", workers)
    kwargs.setdefault("save", True)
    kwargs.setdefault("val", True)
    kwargs.setdefault("plots", True)
    kwargs.setdefault("exist_ok", False)
    kwargs.setdefault("deterministic", True)
    kwargs.setdefault("single_cls", True)
    kwargs.setdefault("close_mosaic", 10)
    return kwargs


def apply_cli_overrides(kwargs: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.cache != "inherit":
        kwargs["cache"] = {"ram": True, "disk": "disk", "off": False}[args.cache]
    if args.fraction <= 0.0 or args.fraction > 1.0:
        raise ValueError("--fraction must be within (0, 1].")
    if args.fraction < 1.0:
        kwargs["fraction"] = args.fraction
    if args.batch_auto:
        kwargs["batch"] = -1
    if args.multi_scale:
        kwargs["multi_scale"] = 0.25
    return kwargs


def ensure_ultralytics_settings(args: argparse.Namespace) -> None:
    if not any(
        [
            args.enable_mlflow,
            args.disable_mlflow,
            args.enable_tensorboard,
            args.disable_tensorboard,
        ]
    ):
        return
    from ultralytics import settings

    updates: dict[str, Any] = {}
    if args.enable_mlflow and args.disable_mlflow:
        raise ValueError("Choose either --enable-mlflow or --disable-mlflow, not both.")
    if args.enable_tensorboard and args.disable_tensorboard:
        raise ValueError("Choose either --enable-tensorboard or --disable-tensorboard, not both.")
    if args.enable_mlflow:
        updates["mlflow"] = True
    if args.disable_mlflow:
        updates["mlflow"] = False
    if args.enable_tensorboard:
        updates["tensorboard"] = True
    if args.disable_tensorboard:
        updates["tensorboard"] = False
    if updates:
        settings.update(updates)


def validate_dataset(data_yaml: Path) -> dict[str, Any]:
    payload = load_yaml(data_yaml)
    if not payload:
        raise FileNotFoundError(f"Dataset YAML not found or empty: {data_yaml}")
    if int(payload.get("nc", 1)) != 1:
        raise ValueError(f"Dataset YAML must declare exactly one class. Found nc={payload.get('nc')}.")
    names = payload.get("names", {})
    if isinstance(names, dict):
        normalized_names = [str(names[key]).strip().lower() for key in sorted(names)]
    elif isinstance(names, list):
        normalized_names = [str(value).strip().lower() for value in names]
    else:
        normalized_names = []
    if normalized_names and normalized_names != ["damage"]:
        raise ValueError(f"Dataset YAML must use a single class named 'damage'. Found names={normalized_names}.")
    base = Path(payload["path"]).resolve() if payload.get("path") else data_yaml.parent.resolve()
    for key in ("train", "val", "test"):
        raw = payload.get(key)
        if raw is None:
            continue
        target = Path(raw)
        if not target.is_absolute():
            target = (base / target).resolve()
        if not target.exists():
            raise FileNotFoundError(f"Dataset split '{key}' is missing: {target}")
    return payload


def dataset_fingerprint(workspace: Path) -> str | None:
    stats_path = workspace / "artifacts" / "prep" / "dataset_stats.json"
    if not stats_path.exists():
        return None
    payload = load_json(stats_path)
    return str(payload.get("dataset_fingerprint_sha256") or "")


def write_run_metadata(
    run_dir: Path,
    config_path: Path,
    train_kwargs: dict[str, Any],
    workspace: Path,
    args: argparse.Namespace,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, run_dir / "config_snapshot.yaml")
    metadata = {
        "run_tag": args.run_tag or None,
        "workspace": str(workspace),
        "config_path": str(config_path),
        "train_kwargs": train_kwargs,
        "dataset_fingerprint_sha256": dataset_fingerprint(workspace),
        "runtime": collect_runtime_context({"requested_device": args.device}),
    }
    dump_json(run_dir / "run_metadata.json", metadata)


def apply_config_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    updated = dict(config)
    if args.data_override:
        updated["data"] = args.data_override
    if args.project_override:
        updated["project"] = args.project_override
    if args.name_suffix:
        updated["name"] = f"{updated['name']}{args.name_suffix}"
    return updated


def check_required_paths(config: dict[str, Any], workspace: Path) -> list[str]:
    missing: list[str] = []
    for raw_path in config.get("required_paths", []):
        if not resolve_workspace_path(workspace, raw_path).exists():
            missing.append(str(resolve_workspace_path(workspace, raw_path)))
    return missing


def run_ultralytics(
    config: dict[str, Any],
    workspace: Path,
    device: str,
    workers: int,
    dry_run: bool,
    args: argparse.Namespace,
) -> dict[str, Any]:
    kwargs = resolve_training_kwargs(config, workspace, device, workers)
    kwargs = apply_cli_overrides(kwargs, args)
    model_path = resolve_workspace_path(workspace, config["model"])
    if not model_path.exists():
        raise FileNotFoundError(f"Model checkpoint not found: {model_path}")
    validate_dataset(Path(kwargs["data"]))
    run_dir = Path(kwargs["project"]) / str(kwargs["name"])
    train_kwargs = dict(kwargs)
    train_kwargs.pop("model", None)
    write_run_metadata(run_dir, Path(config["_config_path"]), train_kwargs, workspace, args)

    run_info = {
        "name": config["name"],
        "trainer": "ultralytics",
        "config": str(config["_config_path"]),
        "model": str(model_path),
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
        "status": "dry_run" if dry_run else "completed",
    }
    if dry_run:
        run_info["resolved_kwargs"] = train_kwargs
        return run_info

    ensure_ultralytics_settings(args)
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    model.train(**train_kwargs)
    save_dir = Path(getattr(model.trainer, "save_dir", run_dir))
    run_info["run_dir"] = str(save_dir)
    run_info["best"] = str(save_dir / "weights" / "best.pt")
    run_info["last"] = str(save_dir / "weights" / "last.pt")
    run_info["results_csv"] = str(save_dir / "results.csv")
    write_run_metadata(save_dir, Path(config["_config_path"]), train_kwargs, workspace, args)
    return run_info


def format_command(tokens: list[str], mapping: dict[str, Any]) -> list[str]:
    return [token.format(**mapping) for token in tokens]


def run_external(
    config: dict[str, Any],
    workspace: Path,
    device: str,
    dry_run: bool,
    allow_missing_optional: bool,
    args: argparse.Namespace,
) -> dict[str, Any]:
    workdir = resolve_workspace_path(workspace, config["workdir"])
    missing = check_required_paths(config, workspace)
    run_dir = resolve_workspace_path(workspace, config.get("project", "runs")) / str(config["name"])
    if (not workdir.exists() or missing) and config.get("optional") and allow_missing_optional:
        status = "skipped_optional_missing_dependency"
        details = []
        if not workdir.exists():
            details.append(f"missing workdir: {workdir}")
        if missing:
            details.append("missing required paths: " + ", ".join(missing))
        return {
            "name": config["name"],
            "trainer": "external_command",
            "config": str(config["_config_path"]),
            "run_dir": str(run_dir),
            "status": status,
            "details": "; ".join(details),
        }
    if not workdir.exists():
        raise FileNotFoundError(f"Missing external trainer workdir: {workdir}")
    if missing:
        raise FileNotFoundError("Missing external trainer dependency paths: " + ", ".join(missing))

    mapping = {key: value for key, value in config.items() if isinstance(value, (str, int, float, bool))}
    mapping.update(
        {
            "workspace": str(workspace),
            "data": str(resolve_workspace_path(workspace, config.get("data", "configs/dataset.yaml"))),
            "project": str(resolve_workspace_path(workspace, config.get("project", "runs"))),
            "device": str(device),
            "weights": str(resolve_workspace_path(workspace, config["weights"])),
            "name": config["name"],
        }
    )
    command = format_command(config["command"], mapping)
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_json(
        run_dir / "external_run_metadata.json",
        {
            "workspace": str(workspace),
            "config_path": str(config["_config_path"]),
            "command": command,
            "runtime": collect_runtime_context({"requested_device": device, "run_tag": args.run_tag or None}),
        },
    )
    run_info = {
        "name": config["name"],
        "trainer": "external_command",
        "config": str(config["_config_path"]),
        "run_dir": str(run_dir),
        "command": command,
        "status": "dry_run" if dry_run else "completed",
    }
    if dry_run:
        return run_info
    subprocess.run(command, cwd=workdir, check=True)
    run_info["best"] = str(run_dir / "weights" / "best.pt")
    run_info["last"] = str(run_dir / "weights" / "last.pt")
    run_info["results_csv"] = str(run_dir / "results.csv")
    return run_info


def run_training_config(
    workspace: Path,
    config_path: Path,
    device: str,
    workers: int,
    dry_run: bool,
    allow_missing_optional: bool,
    args: argparse.Namespace,
) -> dict[str, Any]:
    config = load_yaml(config_path)
    config = apply_config_overrides(config, args)
    config["_config_path"] = str(config_path)
    trainer = config.get("trainer", "ultralytics")
    if trainer == "ultralytics":
        return run_ultralytics(config, workspace, device, workers, dry_run, args)
    if trainer == "external_command":
        return run_external(config, workspace, device, dry_run, allow_missing_optional, args)
    raise ValueError(f"Unsupported trainer '{trainer}' in {config_path}")


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    config_path = resolve_config_path(args.config)
    run_info = run_training_config(
        workspace=workspace,
        config_path=config_path,
        device=args.device,
        workers=args.workers,
        dry_run=args.dry_run,
        allow_missing_optional=args.allow_missing_optional,
        args=args,
    )
    manifest_path = workspace / "artifacts" / "training_manifest.json"
    upsert_manifest_run(manifest_path, workspace, run_info)
    print(json.dumps(run_info, indent=2))
    if manifest_path.exists():
        print(json.dumps(summarize_manifest(manifest_path), indent=2))


if __name__ == "__main__":
    main()
