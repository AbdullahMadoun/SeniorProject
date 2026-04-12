from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import hf_hub_download
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a conservative two-model smoke test for road damage detection."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def train_model(model_name: str, model: YOLO, data_yaml: str, args: argparse.Namespace, project_root: Path) -> dict:
    run_root = project_root / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    common = dict(
        data=data_yaml,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(run_root),
        name=model_name,
        exist_ok=True,
        patience=max(2, args.epochs),
        plots=False,
        pretrained=True,
        deterministic=True,
        seed=42,
        cache=False,
        verbose=True,
    )

    if model_name == "yolo12s_custom":
        result = model.train(
            lr0=5e-5,
            lrf=0.01,
            freeze=10,
            weight_decay=0.001,
            mosaic=0.4,
            mixup=0.0,
            copy_paste=0.0,
            **common,
        )
    else:
        result = model.train(
            lr0=5e-4,
            lrf=0.01,
            freeze=8,
            weight_decay=0.001,
            mosaic=0.6,
            mixup=0.05,
            copy_paste=0.0,
            **common,
        )

    run_dir = run_root / model_name
    return {
        "name": model_name,
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "results_csv": str(run_dir / "results.csv"),
        "summary": str(result),
    }


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    data_yaml = str(Path(args.data).resolve())

    weights_dir = workspace / "weights" / "pretrained"
    weights_dir.mkdir(parents=True, exist_ok=True)

    yolo12_weight = Path(
        hf_hub_download(
            repo_id="rezzzq/yolo12s-road-damage-rdd2022",
            filename="yolo12s_RDD2022_best.pt",
        )
    )
    yolo12_local = weights_dir / "yolo12s_rdd2022.pt"
    if not yolo12_local.exists():
        yolo12_local.write_bytes(yolo12_weight.read_bytes())

    manifest = {"workspace": str(workspace), "runs": []}

    yolo12 = YOLO(str(yolo12_local))
    manifest["runs"].append(train_model("yolo12s_custom", yolo12, data_yaml, args, workspace))

    yolov8m = YOLO("yolov8m.pt")
    manifest["runs"].append(train_model("yolov8m_custom", yolov8m, data_yaml, args, workspace))

    manifest_path = workspace / "artifacts" / "training_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
