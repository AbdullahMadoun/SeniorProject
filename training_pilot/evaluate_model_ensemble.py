from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from ultralytics import YOLO

try:
    from ensemble_boxes import weighted_boxes_fusion
except ImportError as exc:  # pragma: no cover - handled at runtime on remote host
    raise SystemExit("Missing dependency: ensemble_boxes. Install with `pip install ensemble-boxes`.") from exc

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
    parser = argparse.ArgumentParser(description="Evaluate a WBF ensemble against custom road-damage coverage metrics.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--device", default="0")
    parser.add_argument("--output", default="")
    parser.add_argument("--iou-match", type=float, default=0.5)
    parser.add_argument("--wbf-iou", type=float, default=0.5)
    parser.add_argument("--wbf-skip-box-thr", type=float, default=0.04)
    parser.add_argument("--yolo-model", action="append", default=[], help="Repeat for each YOLO checkpoint path.")
    parser.add_argument("--yolo-weight", action="append", type=float, default=[], help="Repeat for each YOLO model.")
    parser.add_argument("--yolo-conf", type=float, default=0.05)
    parser.add_argument("--yolo-iou", type=float, default=0.6, help="YOLO NMS IoU threshold at prediction time.")
    parser.add_argument("--yolo-max-det", type=int, default=300, help="YOLO max_det at prediction time.")
    parser.add_argument("--tta", action="store_true")
    parser.add_argument("--tta-imgsz", action="append", type=int, default=[], help="Repeat for explicit multi-scale TTA.")
    parser.add_argument("--tta-flip", action="store_true", help="Enable horizontal-flip TTA when using --tta-imgsz.")
    parser.add_argument("--include-frozen", action="store_true")
    parser.add_argument("--frozen-weight", type=float, default=0.6)
    parser.add_argument("--gdino-config", default="")
    parser.add_argument("--gdino-weights", default="")
    parser.add_argument("--box-threshold", type=float, default=0.25)
    parser.add_argument("--text-threshold", type=float, default=0.25)
    parser.add_argument("--clip-threshold", type=float, default=0.45)
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


def load_frozen_components(args: argparse.Namespace):
    if not args.include_frozen:
        return None

    if not args.gdino_config or not args.gdino_weights:
        raise SystemExit("--include-frozen requires --gdino-config and --gdino-weights")

    import open_clip
    from groundingdino.util.inference import load_model

    device = "cuda" if torch.cuda.is_available() and args.device != "cpu" else "cpu"
    gdino_model = load_model(args.gdino_config, args.gdino_weights)
    clip_model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai", device=device)
    tokenizer = open_clip.get_tokenizer("ViT-L-14")
    clip_model.eval()
    return {
        "device": device,
        "gdino_model": gdino_model,
        "clip_model": clip_model,
        "preprocess": preprocess,
        "tokenizer": tokenizer,
    }


def predict_yolo(
    model: YOLO,
    image_path: Path,
    device: str,
    conf: float,
    iou_thr: float,
    max_det: int,
    tta: bool,
) -> tuple[list[list[float]], list[float]]:
    with Image.open(image_path) as img:
        width, height = img.size

    result = model.predict(
        source=str(image_path),
        conf=conf,
        iou=iou_thr,
        verbose=False,
        device=device,
        max_det=max_det,
        augment=tta,
    )[0]

    boxes: list[list[float]] = []
    scores: list[float] = []
    if result.boxes is not None:
        xyxy = result.boxes.xyxy.cpu().tolist()
        confs = result.boxes.conf.cpu().tolist()
        for box, score in zip(xyxy, confs):
            x1, y1, x2, y2 = box
            boxes.append([x1 / width, y1 / height, x2 / width, y2 / height])
            scores.append(float(score))
    return boxes, scores


def predict_yolo_explicit_tta(
    model: YOLO,
    image_path: Path,
    device: str,
    conf: float,
    iou_thr: float,
    max_det: int,
    tta_imgsz: list[int],
    tta_flip: bool,
) -> tuple[list[list[list[float]]], list[list[float]]]:
    with Image.open(image_path) as img:
        width, height = img.size
    image_bgr = cv2.imread(str(image_path))

    boxes_per_pass: list[list[list[float]]] = []
    scores_per_pass: list[list[float]] = []
    flip_modes = [False, True] if tta_flip else [False]

    for imgsz in tta_imgsz:
        for flipped in flip_modes:
            source = cv2.flip(image_bgr, 1) if flipped else image_bgr
            result = model.predict(
                source=source,
                conf=conf,
                iou=iou_thr,
                verbose=False,
                device=device,
                imgsz=imgsz,
                max_det=max_det,
            )[0]

            pass_boxes: list[list[float]] = []
            pass_scores: list[float] = []
            if result.boxes is not None:
                xyxy = result.boxes.xyxy.cpu().tolist()
                confs = result.boxes.conf.cpu().tolist()
                for box, score in zip(xyxy, confs):
                    x1, y1, x2, y2 = box
                    x1 /= width
                    y1 /= height
                    x2 /= width
                    y2 /= height
                    if flipped:
                        x1, x2 = 1.0 - x2, 1.0 - x1
                    pass_boxes.append([x1, y1, x2, y2])
                    pass_scores.append(float(score))
            boxes_per_pass.append(pass_boxes)
            scores_per_pass.append(pass_scores)

    return boxes_per_pass, scores_per_pass


def predict_frozen(
    frozen: dict,
    args: argparse.Namespace,
    image_path: Path,
) -> tuple[list[list[float]], list[float]]:
    from groundingdino.util.inference import load_image, predict

    image_bgr = cv2.imread(str(image_path))
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h, w = image_rgb.shape[:2]

    _, image_tensor = load_image(str(image_path))
    boxes, logits, _ = predict(
        model=frozen["gdino_model"],
        image=image_tensor,
        caption=TEXT_PROMPT,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
    )

    pred_boxes: list[list[float]] = []
    pred_scores: list[float] = []
    for box, logit in zip(boxes.tolist(), logits.tolist()):
        xyxy_abs = cxcywh_norm_to_xyxy_abs(box, w, h)
        clip_conf = clip_score(
            frozen["clip_model"],
            frozen["preprocess"],
            frozen["tokenizer"],
            frozen["device"],
            image_rgb,
            xyxy_abs,
        )
        fused_score = float(logit) * clip_conf
        if fused_score < args.clip_threshold:
            continue
        pred_boxes.append([xyxy_abs[0] / w, xyxy_abs[1] / h, xyxy_abs[2] / w, xyxy_abs[3] / h])
        pred_scores.append(fused_score)
    return pred_boxes, pred_scores


def main() -> None:
    args = parse_args()
    if not args.yolo_model:
        raise SystemExit("Provide at least one --yolo-model")

    if args.yolo_weight and len(args.yolo_weight) != len(args.yolo_model):
        raise SystemExit("Number of --yolo-weight values must match --yolo-model values")

    yolo_weights = args.yolo_weight or [1.0] * len(args.yolo_model)
    yolo_models = [YOLO(model_path) for model_path in args.yolo_model]
    frozen = load_frozen_components(args)

    dataset_root = Path(args.dataset_root).resolve()
    image_dir = dataset_root / args.split / "images"
    label_dir = dataset_root / args.split / "labels"
    image_paths = sorted([path for path in image_dir.iterdir() if path.is_file()])

    total_gt = 0
    total_pred = 0
    total_matched = 0
    all_found_images = 0
    exact_match_images = 0
    negative_correct = 0
    negative_total = 0
    per_image: list[dict] = []

    for image_path in image_paths:
        gt_boxes = load_boxes(label_dir / f"{image_path.stem}.txt")
        total_gt += len(gt_boxes)

        boxes_list: list[list[list[float]]] = []
        scores_list: list[list[float]] = []
        labels_list: list[list[int]] = []
        weights: list[float] = []

        for model, weight in zip(yolo_models, yolo_weights):
            if args.tta_imgsz:
                tta_boxes_list, tta_scores_list = predict_yolo_explicit_tta(
                    model,
                    image_path,
                    args.device,
                    args.yolo_conf,
                    args.yolo_iou,
                    args.yolo_max_det,
                    args.tta_imgsz,
                    args.tta_flip,
                )
                for pred_boxes, pred_scores in zip(tta_boxes_list, tta_scores_list):
                    boxes_list.append(pred_boxes)
                    scores_list.append(pred_scores)
                    labels_list.append([0] * len(pred_boxes))
                    weights.append(weight)
            else:
                pred_boxes, pred_scores = predict_yolo(
                    model,
                    image_path,
                    args.device,
                    args.yolo_conf,
                    args.yolo_iou,
                    args.yolo_max_det,
                    args.tta,
                )
                boxes_list.append(pred_boxes)
                scores_list.append(pred_scores)
                labels_list.append([0] * len(pred_boxes))
                weights.append(weight)

        if frozen is not None:
            pred_boxes, pred_scores = predict_frozen(frozen, args, image_path)
            boxes_list.append(pred_boxes)
            scores_list.append(pred_scores)
            labels_list.append([0] * len(pred_boxes))
            weights.append(args.frozen_weight)

        fused_boxes, fused_scores, _ = weighted_boxes_fusion(
            boxes_list,
            scores_list,
            labels_list,
            weights=weights,
            iou_thr=args.wbf_iou,
            skip_box_thr=args.wbf_skip_box_thr,
            conf_type="box_and_model_avg",
        )

        pred_boxes = [list(map(float, box)) for box in fused_boxes.tolist()]
        pred_scores = [float(score) for score in fused_scores.tolist()]

        total_pred += len(pred_boxes)
        matched, used_preds = greedy_match(gt_boxes, pred_boxes, args.iou_match)
        total_matched += matched

        gt_count = len(gt_boxes)
        pred_count = len(pred_boxes)
        all_found = matched == gt_count
        exact_match = all_found and used_preds == pred_count

        if gt_count == 0:
            negative_total += 1
            if pred_count == 0:
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
                "gt_boxes": gt_boxes,
                "fused_boxes": pred_boxes,
                "fused_scores": pred_scores,
            }
        )

    precision = (total_matched / total_pred) if total_pred else 1.0
    recall = (total_matched / total_gt) if total_gt else 1.0
    f2 = (5.0 * precision * recall / (4.0 * precision + recall)) if (4.0 * precision + recall) > 0.0 else 0.0

    metrics = {
        "model": "wbf_ensemble",
        "split": args.split,
        "ensemble_members": args.yolo_model + (["frozen_groundingdino_clip_vitl14"] if frozen is not None else []),
        "ensemble_weights": yolo_weights + ([args.frozen_weight] if frozen is not None else []),
        "yolo_conf": args.yolo_conf,
        "yolo_iou": args.yolo_iou,
        "yolo_max_det": args.yolo_max_det,
        "wbf_iou": args.wbf_iou,
        "wbf_skip_box_thr": args.wbf_skip_box_thr,
        "tta_enabled": args.tta,
        "tta_imgsz": args.tta_imgsz,
        "tta_flip": args.tta_flip,
        "include_frozen": frozen is not None,
        "iou_match_threshold": args.iou_match,
        "images": len(image_paths),
        "total_gt": total_gt,
        "total_predictions": total_pred,
        "matched_gt": total_matched,
        "precision": precision,
        "damage_coverage_recall": recall,
        "f2": f2,
        "all_damages_found_image_rate": all_found_images / len(image_paths) if image_paths else 0.0,
        "exact_image_match_rate": exact_match_images / len(image_paths) if image_paths else 0.0,
        "negative_image_exact_count": negative_correct,
        "negative_image_exact_rate": (negative_correct / negative_total) if negative_total else 1.0,
        "negative_image_total": negative_total,
        "per_image": per_image,
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in metrics.items() if k != "per_image"}, indent=2))


if __name__ == "__main__":
    main()
