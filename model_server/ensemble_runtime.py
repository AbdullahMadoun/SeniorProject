from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO

try:
    from ensemble_boxes import weighted_boxes_fusion
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Missing dependency `ensemble_boxes`.") from exc


MODE_TO_TTA = {
    "single1024": {"imgsz": [1024], "flip": False},
    "single640": {"imgsz": [640], "flip": False},
    "msflip": {"imgsz": [640, 800, 1024], "flip": True},
}


def clip_box(box: list[float]) -> list[float] | None:
    if len(box) != 4 or not all(math.isfinite(value) for value in box):
        return None
    x1, y1, x2, y2 = [float(value) for value in box]
    x1 = min(1.0, max(0.0, x1))
    y1 = min(1.0, max(0.0, y1))
    x2 = min(1.0, max(0.0, x2))
    y2 = min(1.0, max(0.0, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def sanitize_predictions(boxes: list[list[float]], scores: list[float]) -> tuple[list[list[float]], list[float]]:
    clean_boxes: list[list[float]] = []
    clean_scores: list[float] = []
    for box, score in zip(boxes, scores):
        clipped = clip_box(box)
        if clipped is None or not math.isfinite(score):
            continue
        clean_boxes.append(clipped)
        clean_scores.append(float(min(1.0, max(0.0, score))))
    return clean_boxes, clean_scores


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
    return inter_area / union if union > 0.0 else 0.0


def to_abs(box: list[float], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = box
    return [
        int(round(x1 * width)),
        int(round(y1 * height)),
        int(round(x2 * width)),
        int(round(y2 * height)),
    ]


class IdentityCalibrator:
    def transform(self, scores: list[float]) -> list[float]:
        return [float(min(1.0, max(0.0, score))) for score in scores]


class ManifestCalibrator:
    def __init__(self, payload: dict[str, object]) -> None:
        self.kind = str(payload.get("type", "identity"))
        self.x = [float(value) for value in payload.get("x_thresholds_", [])]
        self.y = [float(value) for value in payload.get("y_thresholds_", [])]

    def transform(self, scores: list[float]) -> list[float]:
        if not scores:
            return []
        if self.kind != "isotonic" or len(self.x) < 2 or len(self.y) < 2:
            return [float(min(1.0, max(0.0, score))) for score in scores]
        raw = np.asarray(scores, dtype=np.float64)
        pred = np.interp(raw, np.asarray(self.x, dtype=np.float64), np.asarray(self.y, dtype=np.float64))
        return [float(min(1.0, max(0.0, value))) for value in pred.tolist()]


@dataclass
class EnsembleSettings:
    members: list[str]
    alias_paths: dict[str, str]
    mode: str
    weight_mode: str
    wbf_iou: float
    wbf_skip: float
    final_threshold: float
    min_support: int
    base_conf: float
    base_iou: float
    max_det: int
    tta_wbf_iou: float
    tta_wbf_skip: float
    support_iou: float
    calibration_manifest: Path | None
    selection_summary: Path | None
    selection_key: str
    explicit_alias_weights: dict[str, float]


def predict_single_pass(
    model: YOLO,
    image_bgr: np.ndarray,
    width: int,
    height: int,
    *,
    imgsz: int,
    conf: float,
    iou_thr: float,
    max_det: int,
    flipped: bool,
) -> tuple[list[list[float]], list[float]]:
    source = cv2.flip(image_bgr, 1) if flipped else image_bgr
    result = model.predict(
        source=source,
        conf=conf,
        iou=iou_thr,
        verbose=False,
        imgsz=imgsz,
        max_det=max_det,
    )[0]

    boxes: list[list[float]] = []
    scores: list[float] = []
    if result.boxes is not None:
        xyxy = result.boxes.xyxy.cpu().tolist()
        confs = result.boxes.conf.cpu().tolist()
        for box, score in zip(xyxy, confs):
            x1, y1, x2, y2 = [float(v) for v in box]
            x1 /= width
            y1 /= height
            x2 /= width
            y2 /= height
            if flipped:
                x1, x2 = 1.0 - x2, 1.0 - x1
            boxes.append([x1, y1, x2, y2])
            scores.append(float(score))
    return sanitize_predictions(boxes, scores)


def fuse_predictions(
    boxes_list: list[list[list[float]]],
    scores_list: list[list[float]],
    *,
    weights: list[float],
    iou_thr: float,
    skip_box_thr: float,
) -> tuple[list[list[float]], list[float]]:
    if not boxes_list:
        return [], []
    labels = [[0] * len(boxes) for boxes in boxes_list]
    fused_boxes, fused_scores, _ = weighted_boxes_fusion(
        boxes_list,
        scores_list,
        labels,
        weights=weights,
        iou_thr=iou_thr,
        skip_box_thr=skip_box_thr,
        conf_type="avg",
    )
    return sanitize_predictions(
        [list(map(float, box)) for box in fused_boxes.tolist()],
        [float(score) for score in fused_scores.tolist()],
    )


def supporting_members(
    fused_box: list[float],
    member_boxes: dict[str, list[list[float]]],
    *,
    support_iou: float,
) -> list[str]:
    matches: list[str] = []
    for alias, boxes in member_boxes.items():
        if any(iou(fused_box, box) >= support_iou for box in boxes):
            matches.append(alias)
    return matches


class EnsembleDetector:
    def __init__(self, settings: EnsembleSettings) -> None:
        self.settings = settings
        self.selection = self._resolve_selection()
        self.mode_cfg = MODE_TO_TTA.get(self.selection["mode"], MODE_TO_TTA["msflip"])
        self.models = self._load_models()
        self.calibrators = self._load_calibrators()
        self.member_weights = self._resolve_member_weights()

    def _resolve_selection(self) -> dict[str, Any]:
        selection = {
            "members": list(self.settings.members),
            "mode": self.settings.mode,
            "weight_mode": self.settings.weight_mode,
            "wbf_iou": self.settings.wbf_iou,
            "wbf_skip": self.settings.wbf_skip,
            "final_threshold": self.settings.final_threshold,
            "min_support": self.settings.min_support,
        }
        summary_path = self.settings.selection_summary
        if summary_path and summary_path.exists():
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
                selected = payload.get(self.settings.selection_key)
                if isinstance(selected, dict):
                    selection.update(
                        {
                            "members": list(selected.get("members") or selection["members"]),
                            "mode": str(selected.get("mode") or selection["mode"]),
                            "weight_mode": str(selected.get("weight_mode") or selection["weight_mode"]),
                            "wbf_iou": float(selected.get("wbf_iou") or selection["wbf_iou"]),
                            "wbf_skip": float(selected.get("wbf_skip") or selection["wbf_skip"]),
                            "final_threshold": float(selected.get("final_threshold") or selection["final_threshold"]),
                            "min_support": int(selected.get("min_support") or selection["min_support"]),
                        }
                    )
            except Exception:
                pass
        return selection

    def _load_models(self) -> dict[str, YOLO]:
        models: dict[str, YOLO] = {}
        for alias in self.selection["members"]:
            raw_path = str(self.settings.alias_paths.get(alias, "")).strip()
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if candidate.exists():
                models[alias] = YOLO(str(candidate.resolve()))
            else:
                models[alias] = YOLO(raw_path)
        if not models:
            raise RuntimeError("No ensemble members resolved to a usable YOLO weight.")
        return models

    def _load_calibrators(self) -> dict[str, Any]:
        calibrators: dict[str, Any] = {alias: IdentityCalibrator() for alias in self.models}
        manifest_path = self.settings.calibration_manifest
        if not manifest_path or not manifest_path.exists():
            return calibrators
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return calibrators
        mode_name = str(self.selection["mode"])
        for alias in self.models:
            alias_payload = payload.get(alias, {})
            mode_payload = alias_payload.get(mode_name, {})
            calibrator_payload = mode_payload.get("calibrator")
            if isinstance(calibrator_payload, dict):
                calibrators[alias] = ManifestCalibrator(calibrator_payload)
        return calibrators

    def _resolve_member_weights(self) -> list[float]:
        if self.settings.explicit_alias_weights:
            return [
                float(self.settings.explicit_alias_weights.get(alias, 1.0))
                for alias in self.models
            ]

        manifest_path = self.settings.calibration_manifest
        if manifest_path and manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                mode_name = str(self.selection["mode"])
                key = "val_recall" if self.selection["weight_mode"] == "val_recall" else "val_f2"
                if self.selection["weight_mode"] == "equal":
                    return [1.0] * len(self.models)
                weights = []
                for alias in self.models:
                    stats = payload.get(alias, {}).get(mode_name, {}).get("stats", {})
                    weights.append(float(stats.get(key, 1.0)))
                if any(weight > 0.0 for weight in weights):
                    return weights
            except Exception:
                pass
        return [1.0] * len(self.models)

    def predict(
        self,
        image_bgr: np.ndarray,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        overrides = overrides or {}
        selection = dict(self.selection)
        try:
            if overrides.get("wbf_iou") is not None:
                selection["wbf_iou"] = float(overrides["wbf_iou"])
            if overrides.get("wbf_skip") is not None:
                selection["wbf_skip"] = float(overrides["wbf_skip"])
            if overrides.get("final_threshold") is not None:
                selection["final_threshold"] = float(overrides["final_threshold"])
            if overrides.get("min_support") is not None:
                selection["min_support"] = max(1, int(overrides["min_support"]))
        except (TypeError, ValueError):
            pass

        try:
            base_conf = float(overrides.get("base_conf", self.settings.base_conf))
        except (TypeError, ValueError):
            base_conf = self.settings.base_conf
        try:
            base_iou = float(overrides.get("base_iou", self.settings.base_iou))
        except (TypeError, ValueError):
            base_iou = self.settings.base_iou

        height, width = image_bgr.shape[:2]
        boxes_list: list[list[list[float]]] = []
        scores_list: list[list[float]] = []
        member_boxes: dict[str, list[list[float]]] = {}
        active_aliases: list[str] = []
        member_debug: list[dict[str, Any]] = []
        failed_members: list[dict[str, str]] = []

        for alias, model in self.models.items():
            try:
                pass_boxes: list[list[list[float]]] = []
                pass_scores: list[list[float]] = []
                flip_modes = [False, True] if self.mode_cfg["flip"] else [False]
                for imgsz in self.mode_cfg["imgsz"]:
                    for flipped in flip_modes:
                        boxes, scores = predict_single_pass(
                            model,
                            image_bgr,
                            width,
                            height,
                            imgsz=imgsz,
                            conf=base_conf,
                            iou_thr=base_iou,
                            max_det=self.settings.max_det,
                            flipped=flipped,
                        )
                        pass_boxes.append(boxes)
                        pass_scores.append(scores)
            except Exception as exc:
                failed_members.append({"alias": alias, "error": str(exc)})
                member_debug.append(
                    {
                        "alias": alias,
                        "proposal_count": 0,
                        "max_score": 0.0,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            if len(pass_boxes) == 1:
                fused_member_boxes, fused_member_scores = pass_boxes[0], pass_scores[0]
            else:
                fused_member_boxes, fused_member_scores = fuse_predictions(
                    pass_boxes,
                    pass_scores,
                    weights=[1.0] * len(pass_boxes),
                    iou_thr=self.settings.tta_wbf_iou,
                    skip_box_thr=self.settings.tta_wbf_skip,
                )

            fused_member_scores = self.calibrators[alias].transform(fused_member_scores)
            fused_member_boxes, fused_member_scores = sanitize_predictions(fused_member_boxes, fused_member_scores)
            boxes_list.append(fused_member_boxes)
            scores_list.append(fused_member_scores)
            member_boxes[alias] = fused_member_boxes
            active_aliases.append(alias)
            member_debug.append(
                {
                    "alias": alias,
                    "proposal_count": len(fused_member_boxes),
                    "max_score": max(fused_member_scores) if fused_member_scores else 0.0,
                    "status": "ready",
                }
            )

        if not active_aliases:
            raise RuntimeError("All ensemble members failed during inference.")

        active_weights = [
            weight for alias, weight in zip(self.models.keys(), self.member_weights) if alias in active_aliases
        ]

        if len(active_aliases) == 1:
            only_alias = active_aliases[0]
            final_boxes = member_boxes[only_alias]
            final_scores = scores_list[0]
        else:
            final_boxes, final_scores = fuse_predictions(
                boxes_list,
                scores_list,
                weights=active_weights,
                iou_thr=float(selection["wbf_iou"]),
                skip_box_thr=float(selection["wbf_skip"]),
            )

        effective_min_support = min(int(selection["min_support"]), len(active_aliases))

        detections: list[dict[str, Any]] = []
        filtered_count = 0
        for index, (box, score) in enumerate(zip(final_boxes, final_scores)):
            if score < float(selection["final_threshold"]):
                continue
            matches = supporting_members(
                box,
                member_boxes,
                support_iou=self.settings.support_iou,
            )
            if len(matches) < effective_min_support:
                continue
            filtered_count += 1
            detections.append(
                {
                    "id": f"D{len(detections)}",
                    "label": "Damage",
                    "bbox_xyxy": to_abs(box, width, height),
                    "confidence": float(score),
                    "support": len(matches),
                    "member_votes": matches,
                }
            )

        debug = {
            "detector_mode": "ensemble",
            "selection": {
                "members": active_aliases,
                "mode": selection["mode"],
                "weight_mode": selection["weight_mode"],
                "wbf_iou": float(selection["wbf_iou"]),
                "wbf_skip": float(selection["wbf_skip"]),
                "final_threshold": float(selection["final_threshold"]),
                "min_support": effective_min_support,
                "requested_min_support": int(selection["min_support"]),
                "base_conf": float(base_conf),
                "base_iou": float(base_iou),
            },
            "member_weights": {
                alias: weight for alias, weight in zip(active_aliases, active_weights)
            },
            "members": member_debug,
            "failed_members": failed_members,
            "raw_fused_count": len(final_boxes),
            "filtered_detection_count": filtered_count,
        }
        return detections, debug
