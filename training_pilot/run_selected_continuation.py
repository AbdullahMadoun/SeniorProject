from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continue selected benchmark models from their saved last.pt checkpoints into new run names."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--epochs-additional", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--variant",
        action="append",
        required=True,
        choices=[
            "yolo12s_custom_benchmark",
            "yolov8l_custom_benchmark",
            "yolov8m_custom_benchmark",
            "yolov8s_diverse",
        ],
        help="Repeat for each variant to continue.",
    )
    return parser.parse_args()


def config_for_variant(variant: str) -> dict:
    configs = {
        "yolo12s_custom_benchmark": {
            "batch": 16,
            "optimizer": "AdamW",
            "lr0": 5e-5,
            "freeze": 10,
            "mosaic": 0.8,
            "mixup": 0.1,
            "copy_paste": 0.2,
            "degrees": 10.0,
            "scale": 0.5,
            "hsv_v": 0.4,
            "fliplr": 0.5,
            "seed": 42,
        },
        "yolov8l_custom_benchmark": {
            "batch": 16,
            "optimizer": "AdamW",
            "lr0": 5e-4,
            "freeze": 15,
            "mosaic": 1.0,
            "mixup": 0.15,
            "copy_paste": 0.3,
            "degrees": 15.0,
            "scale": 0.5,
            "erasing": 0.4,
            "seed": 42,
        },
        "yolov8m_custom_benchmark": {
            "batch": 24,
            "optimizer": "AdamW",
            "lr0": 8e-4,
            "freeze": 10,
            "mosaic": 1.0,
            "mixup": 0.2,
            "copy_paste": 0.3,
            "degrees": 15.0,
            "scale": 0.5,
            "erasing": 0.4,
            "seed": 42,
        },
        "yolov8s_diverse": {
            "batch": 32,
            "optimizer": "SGD",
            "lr0": 1e-3,
            "momentum": 0.937,
            "weight_decay": 5e-4,
            "freeze": 5,
            "mosaic": 1.0,
            "mixup": 0.3,
            "copy_paste": 0.4,
            "hsv_h": 0.05,
            "hsv_s": 0.9,
            "hsv_v": 0.5,
            "fliplr": 0.5,
            "degrees": 20.0,
            "scale": 0.7,
            "shear": 5.0,
            "perspective": 0.001,
            "erasing": 0.5,
            "seed": 123,
        },
    }
    return configs[variant]


def continue_variant(args: argparse.Namespace, workspace: Path, variant: str) -> dict:
    run_root = workspace / "runs_benchmark"
    source_run = run_root / variant
    source_last = source_run / "weights" / "last.pt"
    if not source_last.exists():
        raise FileNotFoundError(f"Missing continuation checkpoint: {source_last}")

    config = config_for_variant(variant)
    new_name = f"{variant}_plus{args.epochs_additional}"
    model = YOLO(str(source_last))
    model.train(
        data=args.data,
        epochs=args.epochs_additional,
        imgsz=args.imgsz,
        batch=config["batch"],
        device=args.device,
        workers=args.workers,
        project=str(run_root),
        name=new_name,
        exist_ok=True,
        patience=max(4, args.epochs_additional),
        optimizer=config["optimizer"],
        lr0=config["lr0"],
        lrf=0.01,
        weight_decay=config.get("weight_decay", 0.001),
        momentum=config.get("momentum", 0.937),
        freeze=config["freeze"],
        cls=1.0,
        cos_lr=True,
        amp=True,
        mosaic=config["mosaic"],
        mixup=config["mixup"],
        copy_paste=config["copy_paste"],
        degrees=config["degrees"],
        scale=config["scale"],
        hsv_h=config.get("hsv_h", 0.015),
        hsv_s=config.get("hsv_s", 0.7),
        hsv_v=config.get("hsv_v", 0.4),
        fliplr=config.get("fliplr", 0.5),
        shear=config.get("shear", 0.0),
        perspective=config.get("perspective", 0.0),
        erasing=config.get("erasing", 0.0),
        deterministic=True,
        seed=config["seed"],
        verbose=True,
        plots=False,
    )

    run_dir = run_root / new_name
    return {
        "name": new_name,
        "source_variant": variant,
        "source_last": str(source_last),
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
    }


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    manifest = {
        "workspace": str(workspace),
        "epochs_additional": args.epochs_additional,
        "runs": [],
    }
    for variant in args.variant:
        manifest["runs"].append(continue_variant(args, workspace, variant))

    manifest_path = workspace / "artifacts" / "continuation_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
