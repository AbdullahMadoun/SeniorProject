from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import dump_json, load_pipeline_config, resolve_project_root
from train_model import load_yolo_class, resolve_model_entry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume an interrupted training run from run_dir/weights/last.pt.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--run-dir", required=True, help="Existing run directory containing args.yaml and weights/last.pt.")
    parser.add_argument("--device", default="")
    parser.add_argument("--workers", type=int, default=-1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    model_entry = resolve_model_entry(pipeline, args.model_id)
    run_dir = Path(args.run_dir).resolve()
    last_pt = run_dir / "weights" / "last.pt"
    args_yaml = run_dir / "args.yaml"

    if not run_dir.exists():
        raise FileNotFoundError(f"Missing run dir: {run_dir}")
    if not last_pt.exists():
        raise FileNotFoundError(f"Missing checkpoint for resume: {last_pt}")
    if not args_yaml.exists():
        raise FileNotFoundError(f"Missing args.yaml for resume: {args_yaml}")

    YOLO = load_yolo_class(model_entry, project_root, pipeline)
    model = YOLO(str(last_pt))

    train_kwargs: dict[str, Any] = {"resume": True}
    if args.device:
        train_kwargs["device"] = args.device
    if args.workers >= 0:
        train_kwargs["workers"] = args.workers

    try:
        results = model.train(**train_kwargs)
        status = "resumed"
        detail = ""
    except AssertionError as exc:
        message = str(exc)
        if "nothing to resume" not in message:
            raise
        results = None
        status = "already_complete"
        detail = message
    save_dir = Path(getattr(model.trainer, "save_dir", run_dir))

    record = {
        "mode": "resume",
        "status": status,
        "detail": detail,
        "model_id": args.model_id,
        "run_dir": str(run_dir),
        "checkpoint": str(last_pt),
        "train_kwargs": train_kwargs,
        "save_dir": str(save_dir),
        "results_type": type(results).__name__ if results is not None else "NoneType",
    }
    dump_json(project_root / "artifacts" / "training" / f"{run_dir.name}_resume.json", record)
    print(record)


if __name__ == "__main__":
    main()
