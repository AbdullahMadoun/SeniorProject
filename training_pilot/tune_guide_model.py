from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from guide_utils import collect_runtime_context, dump_json, dump_yaml, load_yaml, resolve_workspace_path
from train_from_guide_config import (
    apply_cli_overrides,
    ensure_ultralytics_settings,
    resolve_config_path,
    resolve_training_kwargs,
    validate_dataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune a guide-defined model with Ultralytics hyperparameter search.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cache", choices=["inherit", "ram", "disk", "off"], default="inherit")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--batch-auto", action="store_true")
    parser.add_argument("--multi-scale", action="store_true")
    parser.add_argument("--enable-mlflow", action="store_true")
    parser.add_argument("--disable-mlflow", action="store_true")
    parser.add_argument("--enable-tensorboard", action="store_true")
    parser.add_argument("--disable-tensorboard", action="store_true")
    parser.add_argument("--run-tag", default="")
    parser.add_argument(
        "--search-space",
        default=str((Path(__file__).resolve().parent / "configs" / "tuning" / "small_dataset_search_space.yaml").resolve()),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_search_space(payload: dict[str, Any]) -> dict[str, tuple[float, float]]:
    space: dict[str, tuple[float, float]] = {}
    for key, value in payload.items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            space[key] = (float(value[0]), float(value[1]))
    if not space:
        raise ValueError("Search space is empty or invalid.")
    return space


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    config_path = resolve_config_path(args.config)
    config = load_yaml(config_path)
    kwargs = resolve_training_kwargs(config, workspace, args.device, args.workers)
    kwargs = apply_cli_overrides(kwargs, args)
    data_yaml = Path(kwargs["data"])
    validate_dataset(data_yaml)

    model_path = resolve_workspace_path(workspace, config["model"])
    if not model_path.exists():
        raise FileNotFoundError(f"Model checkpoint not found: {model_path}")

    ensure_ultralytics_settings(args)
    search_space = normalize_search_space(load_yaml(Path(args.search_space).resolve()))
    tune_name = f"{config['name']}_tune"
    project_root = workspace / "tuning"
    tune_dir = project_root / tune_name
    tune_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "workspace": str(workspace),
        "config_path": str(config_path),
        "model_path": str(model_path),
        "iterations": args.iterations,
        "epochs": args.epochs,
        "search_space": search_space,
        "runtime": collect_runtime_context({"requested_device": args.device, "run_tag": args.run_tag or None}),
    }
    shutil.copy2(config_path, tune_dir / "config_snapshot.yaml")
    dump_yaml(tune_dir / "search_space.yaml", {key: list(value) for key, value in search_space.items()})
    tune_kwargs = {
        "data": str(data_yaml),
        "epochs": args.epochs,
        "iterations": args.iterations,
        "space": search_space,
        "project": str(project_root),
        "name": tune_name,
        "device": args.device,
        "workers": args.workers,
        "plots": True,
        "save": True,
        "val": True,
        "resume": args.resume,
    }
    if "optimizer" in kwargs:
        tune_kwargs["optimizer"] = kwargs["optimizer"]
    if "imgsz" in kwargs:
        tune_kwargs["imgsz"] = kwargs["imgsz"]
    if "batch" in kwargs:
        tune_kwargs["batch"] = kwargs["batch"]
    if "fraction" in kwargs:
        tune_kwargs["fraction"] = kwargs["fraction"]
    if "cache" in kwargs:
        tune_kwargs["cache"] = kwargs["cache"]
    if "multi_scale" in kwargs:
        tune_kwargs["multi_scale"] = kwargs["multi_scale"]
    metadata["tune_kwargs"] = tune_kwargs
    dump_json(tune_dir / "tune_metadata.json", metadata)

    if args.dry_run:
        print(json.dumps({"tune_dir": str(tune_dir), "metadata": metadata}, indent=2))
        return

    from ultralytics import YOLO

    model = YOLO(str(model_path))

    model.tune(**tune_kwargs)

    print(json.dumps({"tune_dir": str(tune_dir), "metadata": metadata}, indent=2))


if __name__ == "__main__":
    main()
