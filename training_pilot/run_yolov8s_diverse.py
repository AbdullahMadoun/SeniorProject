from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the guide-aligned YOLOv8s diverse branch.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def upsert_run(manifest_path: Path, run_info: dict) -> None:
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"workspace": str(manifest_path.parent.parent), "runs": []}

    runs = [run for run in manifest.get("runs", []) if run.get("name") != run_info["name"]]
    runs.append(run_info)
    manifest["runs"] = runs
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    run_root = workspace / "runs_benchmark"
    run_root.mkdir(parents=True, exist_ok=True)

    model = YOLO("yolov8s.pt")
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=32,
        device=args.device,
        workers=args.workers,
        project=str(run_root),
        name="yolov8s_diverse",
        exist_ok=True,
        patience=max(4, args.epochs),
        optimizer="SGD",
        lr0=1e-3,
        lrf=0.01,
        momentum=0.937,
        weight_decay=5e-4,
        freeze=5,
        cls=1.0,
        cos_lr=True,
        amp=True,
        mosaic=1.0,
        mixup=0.3,
        copy_paste=0.4,
        hsv_h=0.05,
        hsv_s=0.9,
        hsv_v=0.5,
        fliplr=0.5,
        degrees=20.0,
        scale=0.7,
        shear=5.0,
        perspective=0.001,
        erasing=0.5,
        deterministic=True,
        seed=123,
        verbose=True,
        plots=False,
    )

    run_dir = run_root / "yolov8s_diverse"
    run_info = {
        "name": "yolov8s_diverse",
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
    }

    manifest_path = workspace / "artifacts" / "benchmark_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    upsert_run(manifest_path, run_info)
    print(json.dumps(run_info, indent=2))


if __name__ == "__main__":
    main()
