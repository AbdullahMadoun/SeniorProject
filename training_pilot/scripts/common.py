from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_CONFIG = PROJECT_ROOT / "configs" / "max_recall" / "pipeline.yaml"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError(f"Expected YAML object at {path}, got {type(payload).__name__}")
    return payload


def dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_project_root(raw: str | Path | None = None) -> Path:
    if raw is None:
        return PROJECT_ROOT
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def load_pipeline_config(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "configs" / "max_recall" / "pipeline.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing pipeline config: {config_path}")
    return load_yaml(config_path)


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def normalize_class_name(name: str) -> str:
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def resolve_source_data_yaml(raw_dir: Path) -> Path:
    candidates = sorted(raw_dir.rglob("data.yaml"))
    if not candidates:
        raise FileNotFoundError(f"No data.yaml found under {raw_dir}")
    if len(candidates) == 1:
        return candidates[0]
    valid: list[Path] = []
    for candidate in candidates:
        payload = load_yaml(candidate)
        names = extract_class_names(payload)
        normalized = {normalize_class_name(name) for name in names}
        if {"pothole", "crack", "manhole"}.issubset(normalized):
            valid.append(candidate)
    if len(valid) == 1:
        return valid[0]
    raise RuntimeError(
        "Unable to determine the source data.yaml uniquely. "
        f"Candidates: {[str(path) for path in candidates]}"
    )


def extract_class_names(data_yaml: dict[str, Any]) -> list[str]:
    names = data_yaml.get("names", [])
    if isinstance(names, dict):
        return [str(names[key]) for key in sorted(names, key=lambda item: int(item))]
    if isinstance(names, list):
        return [str(name) for name in names]
    return []


def resolve_class_id_map(data_yaml_path: Path) -> dict[str, int]:
    payload = load_yaml(data_yaml_path)
    class_names = extract_class_names(payload)
    mapping: dict[str, int] = {}
    for idx, name in enumerate(class_names):
        mapping[normalize_class_name(name)] = idx
    return mapping


def is_yolo_label_file(path: Path) -> bool:
    if path.name.lower() == "classes.txt":
        return False
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return True
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) < 5:
            return False
        try:
            [float(value) for value in parts[:5]]
        except ValueError:
            return False
    return True


def candidate_images_for_label(label_path: Path) -> list[Path]:
    candidates: list[Path] = []
    for suffix in IMAGE_SUFFIXES:
        candidates.append(label_path.with_suffix(suffix))
        if label_path.parent.name.lower() == "labels":
            candidates.append(label_path.parent.parent / "images" / f"{label_path.stem}{suffix}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def index_image_paths(raw_dir: Path) -> dict[str, list[Path]]:
    by_stem: dict[str, list[Path]] = {}
    for path in raw_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        by_stem.setdefault(path.stem, []).append(path)
    return by_stem


def discover_label_image_pairs(raw_dir: Path) -> list[tuple[Path, Path]]:
    image_index = index_image_paths(raw_dir)
    pairs: list[tuple[Path, Path]] = []
    for label_path in sorted(raw_dir.rglob("*.txt")):
        if not is_yolo_label_file(label_path):
            continue
        image_path = None
        for candidate in candidate_images_for_label(label_path):
            if candidate.exists():
                image_path = candidate
                break
        if image_path is None:
            candidates = image_index.get(label_path.stem, [])
            if len(candidates) == 1:
                image_path = candidates[0]
        if image_path is None:
            raise FileNotFoundError(f"Could not find image for label file {label_path}")
        pairs.append((image_path, label_path))
    if not pairs:
        raise RuntimeError(f"No YOLO image/label pairs were found under {raw_dir}")
    return pairs


def read_yolo_rows(label_path: Path) -> list[tuple[int, list[float]]]:
    rows: list[tuple[int, list[float]]] = []
    if not label_path.exists():
        return rows
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls_id = int(float(parts[0]))
        bbox = [float(value) for value in parts[1:5]]
        rows.append((cls_id, bbox))
    return rows


def write_yolo_rows(label_path: Path, rows: list[tuple[int, list[float]]]) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        label_path.write_text("", encoding="utf-8")
        return
    lines = [f"{cls_id} {' '.join(f'{value:.6f}' for value in bbox)}" for cls_id, bbox in rows]
    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def unique_filtered_name(image_path: Path, raw_dir: Path) -> str:
    relative = image_path.resolve().relative_to(raw_dir.resolve())
    slug = "__".join(relative.with_suffix("").parts)
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in slug)
    return f"{safe}{image_path.suffix.lower()}"


def load_boxes_norm(label_path: Path) -> list[list[float]]:
    boxes: list[list[float]] = []
    for _, (x_center, y_center, width, height) in read_yolo_rows(label_path):
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
    return inter_area / union if union > 0.0 else 0.0


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


def f2_score(precision: float, recall: float) -> float:
    beta_sq = 4.0
    denom = beta_sq * precision + recall
    if denom <= 0.0:
        return 0.0
    return (1.0 + beta_sq) * precision * recall / denom


def summarize_split(records: list[dict[str, Any]]) -> dict[str, Any]:
    strat_counts = Counter(record["stratify_label"] for record in records)
    return {
        "images": len(records),
        "boxes": sum(int(record.get("box_count", 0)) for record in records),
        "strata": dict(sorted(strat_counts.items())),
    }
