from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate damage coverage and exact-match metrics for a YOLO detector.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--conf", type=float, default=0.1)
    parser.add_argument("--iou-match", type=float, default=0.5)
    parser.add_argument("--device", default="0")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def load_boxes(label_path: Path) -> list[list[float]]:
    boxes: list[list[float]] = []
    if not label_path.exists():
        return boxes
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, x_center, y_center, width, height = [float(value) for value in parts]
        x1 = x_center - width / 2.0
        y1 = y_center - height / 2.0
        x2 = x_center + width / 2.0
        y2 = y_center + height / 2.0
        boxes.append([x1, y1, x2, y2])
    return boxes


def iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def greedy_match(gt_boxes: list[list[float]], pred_boxes: list[list[float]], threshold: float) -> tuple[int, int]:
    matches = 0
    used_preds: set[int] = set()
    for gt_box in gt_boxes:
        best_idx = None
        best_iou = 0.0
        for idx, pred_box in enumerate(pred_boxes):
            if idx in used_preds:
                continue
            score = iou(gt_box, pred_box)
            if score >= threshold and score > best_iou:
                best_iou = score
                best_idx = idx
        if best_idx is not None:
            used_preds.add(best_idx)
            matches += 1
    return matches, len(used_preds)


def main() -> None:
    args = parse_args()
    model = YOLO(args.model)

    dataset_root = Path(args.dataset_root).resolve()
    image_dir = dataset_root / args.split / "images"
    label_dir = dataset_root / args.split / "labels"

    image_paths = sorted([p for p in image_dir.iterdir() if p.is_file()])
    total_gt = 0
    total_pred = 0
    total_matched = 0
    exact_all_found_images = 0
    exact_match_images = 0
    negative_correct = 0
    per_image: list[dict] = []

    for image_path in image_paths:
        gt_boxes = load_boxes(label_dir / f"{image_path.stem}.txt")
        total_gt += len(gt_boxes)

        with Image.open(image_path) as img:
            width, height = img.size

        result = model.predict(
            source=str(image_path),
            conf=args.conf,
            iou=0.6,
            verbose=False,
            device=args.device,
        )[0]
        pred_boxes = []
        if result.boxes is not None:
            for xyxy in result.boxes.xyxy.cpu().tolist():
                x1, y1, x2, y2 = xyxy
                pred_boxes.append([x1 / width, y1 / height, x2 / width, y2 / height])

        total_pred += len(pred_boxes)
        matched, used_preds = greedy_match(gt_boxes, pred_boxes, args.iou_match)
        total_matched += matched

        gt_count = len(gt_boxes)
        pred_count = len(pred_boxes)
        all_found = matched == gt_count
        exact_match = all_found and used_preds == pred_count

        if gt_count == 0 and pred_count == 0:
            negative_correct += 1

        if all_found:
            exact_all_found_images += 1
        if exact_match:
            exact_match_images += 1

        per_image.append(
            {
                "image": image_path.name,
                "gt_count": gt_count,
                "pred_count": pred_count,
                "matched_gt": matched,
                "all_found": all_found,
                "exact_match": exact_match,
            }
        )

    metrics = {
        "model": str(Path(args.model).resolve()),
        "split": args.split,
        "confidence_threshold": args.conf,
        "iou_match_threshold": args.iou_match,
        "images": len(image_paths),
        "total_gt": total_gt,
        "total_predictions": total_pred,
        "matched_gt": total_matched,
        "damage_coverage_recall": (total_matched / total_gt) if total_gt else 1.0,
        "all_damages_found_image_rate": exact_all_found_images / len(image_paths) if image_paths else 0.0,
        "exact_image_match_rate": exact_match_images / len(image_paths) if image_paths else 0.0,
        "negative_image_exact_rate": negative_correct,
        "per_image": per_image,
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in metrics.items() if k != "per_image"}, indent=2))


if __name__ == "__main__":
    main()
