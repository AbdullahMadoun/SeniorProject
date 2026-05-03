from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import open_clip
import torch
from PIL import Image
from groundingdino.util.inference import load_image, load_model, predict


POSITIVE_PROMPTS = [
    "road damage",
    "crack on asphalt road",
    "pothole on pavement",
    "damaged road surface",
]

NEGATIVE_PROMPTS = [
    "clean asphalt road",
    "lane marking on road",
    "road shadow",
    "parked vehicle",
    "curb edge",
]

TEXT_PROMPT = "road damage . crack . pothole . damaged pavement ."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a frozen GroundingDINO + CLIP baseline.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--gdino-config", required=True)
    parser.add_argument("--gdino-weights", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--box-threshold", type=float, default=0.25)
    parser.add_argument("--text-threshold", type=float, default=0.25)
    parser.add_argument("--clip-threshold", type=float, default=0.45)
    parser.add_argument("--iou-match", type=float, default=0.5)
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


def clip_score(
    clip_model,
    preprocess,
    tokenizer,
    device: str,
    image_rgb: np.ndarray,
    bbox_xyxy: list[float],
) -> float:
    h, w = image_rgb.shape[:2]
    x1, y1, x2, y2 = bbox_xyxy
    x1 = max(0, min(int(x1) - 20, w - 1))
    y1 = max(0, min(int(y1) - 20, h - 1))
    x2 = max(0, min(int(x2) + 20, w))
    y2 = max(0, min(int(y2) + 20, h))
    if x2 <= x1 or y2 <= y1:
        return 0.0

    crop = Image.fromarray(image_rgb[y1:y2, x1:x2])
    image_tensor = preprocess(crop).unsqueeze(0).to(device)
    texts = POSITIVE_PROMPTS + NEGATIVE_PROMPTS
    text_tokens = tokenizer(texts).to(device)

    with torch.no_grad():
        image_features = clip_model.encode_image(image_tensor)
        text_features = clip_model.encode_text(text_tokens)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        sims = (100.0 * image_features @ text_features.T).softmax(dim=-1)[0].cpu().numpy()

    pos_score = float(np.sum(sims[: len(POSITIVE_PROMPTS)]))
    neg_score = float(np.sum(sims[len(POSITIVE_PROMPTS) :]))
    return pos_score / (pos_score + neg_score + 1e-6)


def cxcywh_norm_to_xyxy_abs(box: list[float], width: int, height: int) -> list[float]:
    cx, cy, bw, bh = box
    x1 = (cx - bw / 2.0) * width
    y1 = (cy - bh / 2.0) * height
    x2 = (cx + bw / 2.0) * width
    y2 = (cy + bh / 2.0) * height
    return [x1, y1, x2, y2]


def main() -> None:
    args = parse_args()
    device = args.device if torch.cuda.is_available() else "cpu"
    dataset_root = Path(args.dataset_root).resolve()
    image_dir = dataset_root / args.split / "images"
    label_dir = dataset_root / args.split / "labels"

    gdino_model = load_model(args.gdino_config, args.gdino_weights)
    clip_model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai", device=device)
    tokenizer = open_clip.get_tokenizer("ViT-L-14")
    clip_model.eval()

    image_paths = sorted([p for p in image_dir.iterdir() if p.is_file()])
    total_gt = 0
    total_pred = 0
    total_matched = 0
    all_found_images = 0
    exact_match_images = 0
    negative_correct = 0

    per_image: list[dict] = []

    for image_path in image_paths:
        gt_boxes = load_boxes(label_dir / f"{image_path.stem}.txt")
        total_gt += len(gt_boxes)

        image_bgr = cv2.imread(str(image_path))
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = image_rgb.shape[:2]

        _, image_tensor = load_image(str(image_path))
        boxes, logits, _ = predict(
            model=gdino_model,
            image=image_tensor,
            caption=TEXT_PROMPT,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
        )

        pred_boxes: list[list[float]] = []
        for box, logit in zip(boxes.tolist(), logits.tolist()):
            xyxy_abs = cxcywh_norm_to_xyxy_abs(box, w, h)
            clip_conf = clip_score(clip_model, preprocess, tokenizer, device, image_rgb, xyxy_abs)
            fused_score = float(logit) * clip_conf
            if fused_score < args.clip_threshold:
                continue
            pred_boxes.append([xyxy_abs[0] / w, xyxy_abs[1] / h, xyxy_abs[2] / w, xyxy_abs[3] / h])

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
            all_found_images += 1
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
        "model": "frozen_groundingdino_clip_vitl14",
        "split": args.split,
        "box_threshold": args.box_threshold,
        "text_threshold": args.text_threshold,
        "clip_threshold": args.clip_threshold,
        "iou_match_threshold": args.iou_match,
        "images": len(image_paths),
        "total_gt": total_gt,
        "total_predictions": total_pred,
        "matched_gt": total_matched,
        "damage_coverage_recall": (total_matched / total_gt) if total_gt else 1.0,
        "all_damages_found_image_rate": all_found_images / len(image_paths) if image_paths else 0.0,
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
