from __future__ import annotations

import json
import math
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from common import dump_json, dump_yaml, f2_score, greedy_match, iou, load_boxes_norm, load_json, load_pipeline_config, resolve_project_root


def get_weighted_boxes_fusion():
    try:
        from ensemble_boxes import weighted_boxes_fusion
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Failed to import ensemble_boxes.weighted_boxes_fusion. "
            "Use a clean env on Vast with compatible numpy/numba/ensemble-boxes versions."
        ) from exc
    return weighted_boxes_fusion


def confidence_grid(pipeline: dict[str, Any]) -> list[float]:
    sweep = pipeline["inference"]["conf_sweep"]
    start = float(sweep["start"])
    stop = float(sweep["stop"])
    step = float(sweep["step"])
    count = int(round((stop - start) / step)) + 1
    return [round(start + idx * step, 6) for idx in range(count)]


def wbf_grid(pipeline: dict[str, Any]) -> list[tuple[float, float]]:
    per_tile = pipeline["inference"]["per_tile_wbf"]
    return list(product(per_tile["iou_grid"], per_tile["skip_box_grid"]))


def tile_positions(length: int, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    stride = tile_size - overlap
    positions = list(range(0, max(length - tile_size, 0) + 1, stride))
    last = length - tile_size
    if positions[-1] != last:
        positions.append(last)
    return positions


def build_split_tiles(project_root: Path, split: str, tile_size: int, overlap: int) -> Path:
    split_root = project_root / "data" / split / "images"
    tiles_root = project_root / "artifacts" / "tiles" / split
    tile_image_dir = tiles_root / "images"
    manifest_path = tiles_root / "manifest.json"

    if manifest_path.exists():
        return manifest_path

    tile_image_dir.mkdir(parents=True, exist_ok=True)
    image_records: list[dict[str, Any]] = []
    tile_records: list[dict[str, Any]] = []
    for image_path in sorted(path for path in split_root.iterdir() if path.is_file()):
        with Image.open(image_path) as img:
            image = img.convert("RGB")
            width, height = image.size
            xs = tile_positions(width, tile_size, overlap)
            ys = tile_positions(height, tile_size, overlap)
            image_tile_ids: list[str] = []
            for x in xs:
                for y in ys:
                    tile_w = min(tile_size, width - x)
                    tile_h = min(tile_size, height - y)
                    tile_id = f"{image_path.stem}__x{x}_y{y}_w{tile_w}_h{tile_h}"
                    tile_name = f"{tile_id}{image_path.suffix.lower()}"
                    tile_crop = image.crop((x, y, x + tile_w, y + tile_h))
                    tile_crop.save(tile_image_dir / tile_name)
                    tile_records.append(
                        {
                            "tile_id": tile_id,
                            "tile_name": tile_name,
                            "image": image_path.name,
                            "x": x,
                            "y": y,
                            "tile_width": tile_w,
                            "tile_height": tile_h,
                            "image_width": width,
                            "image_height": height,
                        }
                    )
                    image_tile_ids.append(tile_id)
            image_records.append(
                {
                    "image": image_path.name,
                    "width": width,
                    "height": height,
                    "tile_ids": image_tile_ids,
                }
            )

    dump_json(
        manifest_path,
        {
            "split": split,
            "tile_size": tile_size,
            "overlap": overlap,
            "tile_image_dir": str(tile_image_dir.resolve()),
            "images": image_records,
            "tiles": tile_records,
        },
    )
    return manifest_path


def ensure_prediction_cache(project_root: Path, split: str, device: str, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline = load_pipeline_config(project_root)
    inference = pipeline["inference"]
    manifest_path = build_split_tiles(project_root, split, int(inference["tile_size"]), int(inference["tile_overlap"]))
    manifest = load_json(manifest_path)
    tile_dir = Path(manifest["tile_image_dir"])
    cache_root = project_root / "artifacts" / "predictions" / split
    cache_root.mkdir(parents=True, exist_ok=True)

    for model in pipeline["models"]:
        for imgsz in inference["scales"]:
            for flip in inference["flips"]:
                output = cache_root / f"{model['id']}__imgsz{imgsz}__flip{flip}.json"
                if output.exists() and not force:
                    continue
                subprocess.run(
                    [
                        sys.executable,
                        str(project_root / "scripts" / "predict_backend.py"),
                        "--project-root",
                        str(project_root),
                        "--model-id",
                        model["id"],
                        "--image-dir",
                        str(tile_dir),
                        "--output",
                        str(output),
                        "--device",
                        device,
                        "--conf",
                        str(pipeline["training"]["val_conf"]),
                        "--imgsz",
                        str(imgsz),
                        "--flip",
                        flip,
                    ],
                    check=True,
                )

    raw_cache: dict[str, dict[int, dict[str, dict[str, Any]]]] = {}
    for model in pipeline["models"]:
        model_cache: dict[int, dict[str, dict[str, Any]]] = {}
        for imgsz in inference["scales"]:
            flip_cache: dict[str, dict[str, Any]] = {}
            for flip in inference["flips"]:
                output = cache_root / f"{model['id']}__imgsz{imgsz}__flip{flip}.json"
                payload = load_json(output)
                flip_cache[flip] = {record["image"]: record for record in payload["records"]}
            model_cache[int(imgsz)] = flip_cache
        raw_cache[model["id"]] = model_cache
    return manifest, raw_cache


def load_ground_truth(project_root: Path, split: str) -> dict[str, dict[str, Any]]:
    image_dir = project_root / "data" / split / "images"
    label_dir = project_root / "data" / split / "labels"
    ground_truth: dict[str, dict[str, Any]] = {}
    for image_path in sorted(path for path in image_dir.iterdir() if path.is_file()):
        with Image.open(image_path) as img:
            width, height = img.size
        ground_truth[image_path.name] = {
            "boxes": load_boxes_norm(label_dir / f"{image_path.stem}.txt"),
            "width": width,
            "height": height,
        }
    return ground_truth


def safe_wbf(
    boxes_list: list[list[list[float]]],
    scores_list: list[list[float]],
    weights: list[float],
    iou_thr: float,
    skip_box_thr: float,
    conf_type: str,
) -> tuple[list[list[float]], list[float]]:
    if not any(boxes_list):
        return [], []
    weighted_boxes_fusion = get_weighted_boxes_fusion()
    labels_list = [[0] * len(boxes) for boxes in boxes_list]
    fused_boxes, fused_scores, _ = weighted_boxes_fusion(
        boxes_list,
        scores_list,
        labels_list,
        weights=weights,
        iou_thr=iou_thr,
        skip_box_thr=skip_box_thr,
        conf_type=conf_type,
    )
    return [list(map(float, box)) for box in fused_boxes.tolist()], [float(score) for score in fused_scores.tolist()]


def project_tile_boxes_to_image(tile: dict[str, Any], boxes: list[list[float]]) -> list[list[float]]:
    projected: list[list[float]] = []
    image_w = float(tile["image_width"])
    image_h = float(tile["image_height"])
    tile_w = float(tile["tile_width"])
    tile_h = float(tile["tile_height"])
    offset_x = float(tile["x"])
    offset_y = float(tile["y"])
    for x1, y1, x2, y2 in boxes:
        projected.append(
            [
                (offset_x + x1 * tile_w) / image_w,
                (offset_y + y1 * tile_h) / image_h,
                (offset_x + x2 * tile_w) / image_w,
                (offset_y + y2 * tile_h) / image_h,
            ]
        )
    return projected


def fuse_single_model_outputs(
    pipeline: dict[str, Any],
    manifest: dict[str, Any],
    raw_cache: dict[str, Any],
    model_id: str,
    wbf_iou: float,
    skip_box_thr: float,
) -> dict[str, dict[str, Any]]:
    merge_cfg = pipeline["inference"]["merge_wbf"]
    outputs: dict[str, dict[str, Any]] = {}
    tiles_by_id = {tile["tile_id"]: tile for tile in manifest["tiles"]}
    for image_info in manifest["images"]:
        tile_sets_boxes: list[list[list[float]]] = []
        tile_sets_scores: list[list[float]] = []
        for tile_id in image_info["tile_ids"]:
            tile = tiles_by_id[tile_id]
            boxes_list: list[list[list[float]]] = []
            scores_list: list[list[float]] = []
            weights: list[float] = []
            for imgsz in pipeline["inference"]["scales"]:
                for flip in pipeline["inference"]["flips"]:
                    record = raw_cache[model_id][int(imgsz)][flip].get(tile["tile_name"], {"boxes": [], "scores": []})
                    boxes_list.append(record["boxes"])
                    scores_list.append(record["scores"])
                    weights.append(1.0)
            fused_tile_boxes, fused_tile_scores = safe_wbf(
                boxes_list,
                scores_list,
                weights,
                iou_thr=float(wbf_iou),
                skip_box_thr=float(skip_box_thr),
                conf_type=str(pipeline["inference"]["per_tile_wbf"]["conf_type"]),
            )
            projected = project_tile_boxes_to_image(tile, fused_tile_boxes)
            tile_sets_boxes.append(projected)
            tile_sets_scores.append(fused_tile_scores)
        merged_boxes, merged_scores = safe_wbf(
            tile_sets_boxes,
            tile_sets_scores,
            [1.0] * len(tile_sets_boxes),
            iou_thr=float(merge_cfg["iou_thr"]),
            skip_box_thr=float(merge_cfg["skip_box_thr"]),
            conf_type=str(merge_cfg["conf_type"]),
        )
        outputs[image_info["image"]] = {"boxes": merged_boxes, "scores": merged_scores}
    return outputs


def fuse_ensemble_outputs(
    pipeline: dict[str, Any],
    manifest: dict[str, Any],
    raw_cache: dict[str, Any],
    model_weights: dict[str, float],
    wbf_iou: float,
    skip_box_thr: float,
) -> dict[str, dict[str, Any]]:
    merge_cfg = pipeline["inference"]["merge_wbf"]
    outputs: dict[str, dict[str, Any]] = {}
    tiles_by_id = {tile["tile_id"]: tile for tile in manifest["tiles"]}
    for image_info in manifest["images"]:
        tile_sets_boxes: list[list[list[float]]] = []
        tile_sets_scores: list[list[float]] = []
        for tile_id in image_info["tile_ids"]:
            tile = tiles_by_id[tile_id]
            boxes_list: list[list[list[float]]] = []
            scores_list: list[list[float]] = []
            weights: list[float] = []
            for model in pipeline["models"]:
                model_weight = float(model_weights[model["id"]])
                for imgsz in pipeline["inference"]["scales"]:
                    for flip in pipeline["inference"]["flips"]:
                        record = raw_cache[model["id"]][int(imgsz)][flip].get(tile["tile_name"], {"boxes": [], "scores": []})
                        boxes_list.append(record["boxes"])
                        scores_list.append(record["scores"])
                        weights.append(model_weight)
            fused_tile_boxes, fused_tile_scores = safe_wbf(
                boxes_list,
                scores_list,
                weights,
                iou_thr=float(wbf_iou),
                skip_box_thr=float(skip_box_thr),
                conf_type=str(pipeline["inference"]["per_tile_wbf"]["conf_type"]),
            )
            projected = project_tile_boxes_to_image(tile, fused_tile_boxes)
            tile_sets_boxes.append(projected)
            tile_sets_scores.append(fused_tile_scores)
        merged_boxes, merged_scores = safe_wbf(
            tile_sets_boxes,
            tile_sets_scores,
            [1.0] * len(tile_sets_boxes),
            iou_thr=float(merge_cfg["iou_thr"]),
            skip_box_thr=float(merge_cfg["skip_box_thr"]),
            conf_type=str(merge_cfg["conf_type"]),
        )
        outputs[image_info["image"]] = {"boxes": merged_boxes, "scores": merged_scores}
    return outputs


def filter_predictions(prediction: dict[str, Any], threshold: float) -> list[list[float]]:
    return [box for box, score in zip(prediction["boxes"], prediction["scores"]) if float(score) >= threshold]


def evaluate_outputs(
    outputs: dict[str, dict[str, Any]],
    ground_truth: dict[str, dict[str, Any]],
    threshold: float,
    primary_iou: float,
    all_found_iou: float,
    include_per_image: bool = False,
) -> dict[str, Any]:
    total_gt = 0
    total_pred = 0
    total_matched = 0
    all_found_images = 0
    per_image: list[dict[str, Any]] = []
    for image_name, gt in ground_truth.items():
        gt_boxes = gt["boxes"]
        pred_boxes = filter_predictions(outputs[image_name], threshold)
        total_gt += len(gt_boxes)
        total_pred += len(pred_boxes)
        matched, _ = greedy_match(gt_boxes, pred_boxes, primary_iou)
        all_found_matched, _ = greedy_match(gt_boxes, pred_boxes, all_found_iou)
        total_matched += matched
        all_found = all_found_matched == len(gt_boxes)
        if all_found:
            all_found_images += 1
        if include_per_image:
            per_image.append(
                {
                    "image": image_name,
                    "gt_count": len(gt_boxes),
                    "pred_count": len(pred_boxes),
                    "matched_gt_iou05": matched,
                    "matched_gt_iou04": all_found_matched,
                    "all_damage_found": all_found,
                }
            )

    precision = total_matched / total_pred if total_pred else 0.0
    recall = total_matched / total_gt if total_gt else 1.0
    metrics = {
        "threshold": threshold,
        "total_gt": total_gt,
        "total_predictions": total_pred,
        "matched_gt": total_matched,
        "precision": precision,
        "recall": recall,
        "f2": f2_score(precision, recall),
        "all_damage_found_rate": all_found_images / len(ground_truth) if ground_truth else 0.0,
    }
    if include_per_image:
        metrics["per_image"] = per_image
    return metrics


def compute_ap50(outputs: dict[str, dict[str, Any]], ground_truth: dict[str, dict[str, Any]], iou_thr: float = 0.5) -> float:
    total_gt = sum(len(item["boxes"]) for item in ground_truth.values())
    if total_gt == 0:
        return 1.0

    detections: list[tuple[float, str, list[float]]] = []
    for image_name, prediction in outputs.items():
        for box, score in zip(prediction["boxes"], prediction["scores"]):
            detections.append((float(score), image_name, box))
    detections.sort(key=lambda item: item[0], reverse=True)

    matched_gt: dict[str, set[int]] = {image_name: set() for image_name in ground_truth}
    tp: list[int] = []
    fp: list[int] = []
    for _, image_name, pred_box in detections:
        gt_boxes = ground_truth[image_name]["boxes"]
        best_idx = None
        best_iou = 0.0
        for idx, gt_box in enumerate(gt_boxes):
            if idx in matched_gt[image_name]:
                continue
            score = iou(gt_box, pred_box)
            if score >= iou_thr and score > best_iou:
                best_iou = score
                best_idx = idx
        if best_idx is not None:
            matched_gt[image_name].add(best_idx)
            tp.append(1)
            fp.append(0)
        else:
            tp.append(0)
            fp.append(1)

    if not tp:
        return 0.0

    tp_cum = np.cumsum(tp)
    fp_cum = np.cumsum(fp)
    recall = tp_cum / total_gt
    precision = tp_cum / np.maximum(tp_cum + fp_cum, 1e-12)
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([0.0], precision, [0.0]))
    for idx in range(len(mpre) - 1, 0, -1):
        mpre[idx - 1] = max(mpre[idx - 1], mpre[idx])
    change = np.where(mrec[1:] != mrec[:-1])[0]
    ap = np.sum((mrec[change + 1] - mrec[change]) * mpre[change + 1])
    return float(ap)


def select_best_threshold(
    outputs: dict[str, dict[str, Any]],
    ground_truth: dict[str, dict[str, Any]],
    conf_values: list[float],
    precision_floor: float,
    primary_iou: float,
    all_found_iou: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sweep_rows: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for threshold in conf_values:
        metrics = evaluate_outputs(outputs, ground_truth, threshold, primary_iou, all_found_iou)
        sweep_rows.append(metrics)
        if metrics["precision"] >= precision_floor:
            eligible.append(metrics)
    if not eligible:
        raise RuntimeError(f"No confidence threshold satisfies precision >= {precision_floor:.2f}")
    eligible.sort(key=lambda item: (-item["recall"], -item["precision"], item["threshold"]))
    return eligible[0], sweep_rows


def compute_model_weights(
    pipeline: dict[str, Any],
    manifest: dict[str, Any],
    raw_cache: dict[str, Any],
    ground_truth: dict[str, dict[str, Any]],
    wbf_iou: float,
    skip_box_thr: float,
) -> dict[str, float]:
    conf = float(pipeline["inference"]["model_weight_conf"])
    weights: dict[str, float] = {}
    for model in pipeline["models"]:
        outputs = fuse_single_model_outputs(pipeline, manifest, raw_cache, model["id"], wbf_iou, skip_box_thr)
        metrics = evaluate_outputs(
            outputs,
            ground_truth,
            threshold=conf,
            primary_iou=float(pipeline["inference"]["primary_iou"]),
            all_found_iou=float(pipeline["inference"]["all_damage_found_iou"]),
        )
        weights[model["id"]] = float(metrics["recall"])
    if math.isclose(sum(weights.values()), 0.0):
        raise RuntimeError("All model recall weights are zero at conf=0.10; cannot build the ensemble faithfully.")
    return weights


def save_ensemble_yaml(project_root: Path, payload: dict[str, Any]) -> Path:
    path = project_root / "configs" / "ensemble.yaml"
    dump_yaml(path, payload)
    return path
