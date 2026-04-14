from __future__ import annotations

import argparse
import contextlib
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download the pretrained checkpoints referenced by the training guide.")
    parser.add_argument("--workspace", required=True, help="Workspace root containing weights/pretrained.")
    return parser.parse_args()


def ensure_yolo12s(dest_dir: Path) -> Path:
    source = Path(
        hf_hub_download(
            repo_id="rezzzq/yolo12s-road-damage-rdd2022",
            filename="yolo12s_RDD2022_best.pt",
        )
    )
    dest = dest_dir / "yolo12s_rdd2022.pt"
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest


def ensure_ultralytics_weight(model_name: str, dest_dir: Path) -> Path:
    from ultralytics import YOLO

    with contextlib.chdir(dest_dir):
        model = YOLO(model_name)
        ckpt_path = getattr(model, "ckpt_path", None)
    if not ckpt_path:
        raise RuntimeError(f"Unable to resolve downloaded path for {model_name}")
    source = Path(ckpt_path).resolve()
    dest = dest_dir / model_name
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    dest_dir = workspace / "weights" / "pretrained"
    dest_dir.mkdir(parents=True, exist_ok=True)

    downloaded = [
        ensure_yolo12s(dest_dir),
        ensure_ultralytics_weight("yolov8l.pt", dest_dir),
        ensure_ultralytics_weight("yolov8m.pt", dest_dir),
        ensure_ultralytics_weight("yolov8s.pt", dest_dir),
    ]

    for path in downloaded:
        print(path)


if __name__ == "__main__":
    main()
