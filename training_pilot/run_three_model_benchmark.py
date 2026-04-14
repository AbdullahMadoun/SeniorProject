from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import hf_hub_download
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the three pretrained YOLO models chosen for the road-damage benchmark."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def train_yolo12s(args: argparse.Namespace, weights_dir: Path, workspace: Path) -> dict:
    source = Path(
        hf_hub_download(
            repo_id="rezzzq/yolo12s-road-damage-rdd2022",
            filename="yolo12s_RDD2022_best.pt",
        )
    )
    target = weights_dir / "yolo12s_rdd2022.pt"
    if not target.exists():
        target.write_bytes(source.read_bytes())

    model = YOLO(str(target))
    run_root = workspace / "runs_benchmark"
    run_root.mkdir(parents=True, exist_ok=True)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=16,
        device=args.device,
        workers=args.workers,
        project=str(run_root),
        name="yolo12s_custom_benchmark",
        exist_ok=True,
        patience=max(4, args.epochs),
        optimizer="AdamW",
        lr0=5e-5,
        lrf=0.01,
        weight_decay=0.001,
        freeze=10,
        cls=1.0,
        cos_lr=True,
        amp=True,
        mosaic=0.8,
        mixup=0.1,
        copy_paste=0.2,
        degrees=10.0,
        scale=0.5,
        hsv_v=0.4,
        fliplr=0.5,
        deterministic=True,
        seed=42,
        verbose=True,
        plots=False,
    )
    run_dir = run_root / "yolo12s_custom_benchmark"
    return {
        "name": "yolo12s_custom_benchmark",
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
    }


def train_yolov8(args: argparse.Namespace, workspace: Path, variant: str) -> dict:
    configs = {
        "yolov8l_custom_benchmark": {
            "model_name": "yolov8l.pt",
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
        },
        "yolov8m_custom_benchmark": {
            "model_name": "yolov8m.pt",
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
        },
    }
    cfg = configs[variant]
    model = YOLO(cfg["model_name"])
    run_root = workspace / "runs_benchmark"
    run_root.mkdir(parents=True, exist_ok=True)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=cfg["batch"],
        device=args.device,
        workers=args.workers,
        project=str(run_root),
        name=variant,
        exist_ok=True,
        patience=max(4, args.epochs),
        optimizer=cfg["optimizer"],
        lr0=cfg["lr0"],
        lrf=0.01,
        weight_decay=0.001,
        freeze=cfg["freeze"],
        cls=1.0,
        cos_lr=True,
        amp=True,
        mosaic=cfg["mosaic"],
        mixup=cfg["mixup"],
        copy_paste=cfg["copy_paste"],
        degrees=cfg["degrees"],
        scale=cfg["scale"],
        erasing=cfg["erasing"],
        deterministic=True,
        seed=42,
        verbose=True,
        plots=False,
    )
    run_dir = run_root / variant
    return {
        "name": variant,
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
    }


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    weights_dir = workspace / "weights" / "pretrained"
    weights_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"workspace": str(workspace), "runs": []}
    manifest["runs"].append(train_yolo12s(args, weights_dir, workspace))
    manifest["runs"].append(train_yolov8(args, workspace, "yolov8l_custom_benchmark"))
    manifest["runs"].append(train_yolov8(args, workspace, "yolov8m_custom_benchmark"))

    manifest_path = workspace / "artifacts" / "benchmark_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
