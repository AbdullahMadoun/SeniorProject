from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from common import dump_json, dump_yaml, ensure_clean_dir, greedy_match, load_boxes_norm, load_json, load_pipeline_config, resolve_project_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find hard-negative images where at least two models miss a GT box.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--device", default="0")
    return parser.parse_args()


def run_predictions(project_root: Path, model_id: str, image_dir: Path, device: str, output: Path, conf: float) -> None:
    subprocess.run(
        [
            "python",
            str(project_root / "scripts" / "predict_backend.py"),
            "--project-root",
            str(project_root),
            "--model-id",
            model_id,
            "--image-dir",
            str(image_dir),
            "--output",
            str(output),
            "--device",
            device,
            "--conf",
            str(conf),
            "--imgsz",
            "640",
        ],
        check=True,
    )


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    train_image_dir = project_root / "data" / "train" / "images"
    train_label_dir = project_root / "data" / "train" / "labels"
    if not train_image_dir.exists():
        raise FileNotFoundError(f"Missing train split: {train_image_dir}. Run 01_split_dataset.py first.")

    prediction_root = project_root / "artifacts" / "hard_negative_predictions"
    ensure_clean_dir(prediction_root)
    model_predictions: dict[str, dict[str, dict]] = {}
    for model in pipeline["models"]:
        output = prediction_root / f"{model['id']}.json"
        run_predictions(
            project_root,
            model["id"],
            train_image_dir,
            args.device,
            output,
            float(pipeline["training"]["val_conf"]),
        )
        payload = load_json(output)
        model_predictions[model["id"]] = {record["image"]: record for record in payload["records"]}

    hard_negative_root = project_root / "data" / "hard_negatives" / "train"
    ensure_clean_dir(project_root / "data" / "hard_negatives")
    (hard_negative_root / "images").mkdir(parents=True, exist_ok=True)
    (hard_negative_root / "labels").mkdir(parents=True, exist_ok=True)

    selected_images: list[str] = []
    details: list[dict] = []
    for image_path in sorted(path for path in train_image_dir.iterdir() if path.is_file()):
        gt_boxes = load_boxes_norm(train_label_dir / f"{image_path.stem}.txt")
        missed_by: list[str] = []
        for model_id, records in model_predictions.items():
            pred_boxes = records[image_path.name]["boxes"]
            matched, _ = greedy_match(gt_boxes, pred_boxes, float(pipeline["inference"]["primary_iou"]))
            if matched < len(gt_boxes):
                missed_by.append(model_id)
        if len(missed_by) >= 2:
            selected_images.append(image_path.name)
            shutil.copy2(image_path, hard_negative_root / "images" / image_path.name)
            shutil.copy2(train_label_dir / f"{image_path.stem}.txt", hard_negative_root / "labels" / f"{image_path.stem}.txt")
            details.append({"image": image_path.name, "missed_by": missed_by, "gt_count": len(gt_boxes)})

    hard_negative_list = project_root / "data" / "hard_negatives.txt"
    hard_negative_list.write_text("\n".join(selected_images) + ("\n" if selected_images else ""), encoding="utf-8")
    dataset_yaml = {
        "path": str(project_root.resolve()),
        "train": "data/hard_negatives/train/images",
        "val": "data/val/images",
        "test": "data/test/images",
        "nc": 1,
        "names": {0: "damage"},
    }
    dump_yaml(project_root / "configs" / "dataset_hard_negatives.yaml", dataset_yaml)
    dump_json(
        project_root / "artifacts" / "hard_negative_summary.json",
        {
            "selected_image_count": len(selected_images),
            "hard_negative_list": str(hard_negative_list.resolve()),
            "details": details,
        },
    )
    print({"selected_image_count": len(selected_images)})


if __name__ == "__main__":
    main()
