from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
from PIL import Image

from common import load_pipeline_config, resolve_project_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run backend-isolated predictions for one model over one image directory.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--conf", type=float, default=0.001)
    parser.add_argument("--iou", type=float, default=0.6)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--flip", choices=["none", "horizontal"], default="none")
    return parser.parse_args()


def resolve_model_entry(config: dict, model_id: str) -> dict:
    for entry in config.get("models", []):
        if entry["id"] == model_id:
            return entry
    raise KeyError(f"Unknown model id: {model_id}")


def inject_backend_path(project_root: Path, model_entry: dict) -> None:
    if model_entry["backend"] == "ultralytics":
        return
    repo_dir = project_root / model_entry["repo_dir"]
    if not repo_dir.exists():
        raise FileNotFoundError(f"Missing backend repo dir for {model_entry['id']}: {repo_dir}")
    sys.path.insert(0, str(repo_dir.resolve()))


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    model_entry = resolve_model_entry(pipeline, args.model_id)
    inject_backend_path(project_root, model_entry)

    weights_path = (project_root / pipeline["weights"]["finetuned_dir"] / args.model_id / "best.pt").resolve()
    if not weights_path.exists():
        raise FileNotFoundError(f"Missing finetuned checkpoint for {args.model_id}: {weights_path}")

    from ultralytics import YOLO

    model = YOLO(str(weights_path))
    image_dir = Path(args.image_dir).resolve()
    records: list[dict] = []
    for image_path in sorted(path for path in image_dir.iterdir() if path.is_file()):
        with Image.open(image_path) as img:
            width, height = img.size
        source = cv2.imread(str(image_path))
        if args.flip == "horizontal":
            source = cv2.flip(source, 1)
        result = model.predict(
            source=source if args.flip != "none" else str(image_path),
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            device=args.device,
            verbose=False,
        )[0]

        boxes = []
        scores = []
        if result.boxes is not None:
            for xyxy, score in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                x1, y1, x2, y2 = xyxy
                x1 /= width
                y1 /= height
                x2 /= width
                y2 /= height
                if args.flip == "horizontal":
                    x1, x2 = 1.0 - x2, 1.0 - x1
                boxes.append([x1, y1, x2, y2])
                scores.append(float(score))
        records.append({"image": image_path.name, "boxes": boxes, "scores": scores})

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"model_id": args.model_id, "records": records}, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
