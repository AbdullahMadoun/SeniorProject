from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

from guide_utils import dump_json, dump_yaml, sha256_file

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install training_pilot/requirements-guide.txt first.") from exc


EXPORT_SPLITS = {
    "train": "train",
    "valid": "val",
    "val": "val",
    "test": "test",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a one-class YOLO detection workspace from a Roboflow export."
    )
    parser.add_argument("--zip", required=True, help="Path to the Roboflow export zip.")
    parser.add_argument("--workspace", required=True, help="Workspace root to create or refresh.")
    parser.add_argument(
        "--allow-segmentation-to-box",
        action="store_true",
        help="Allow lossy polygon-to-box conversion when the export is not plain detection.",
    )
    parser.add_argument("--qa-samples", type=int, default=8, help="Number of overlay images to generate.")
    parser.add_argument("--seed", type=int, default=42, help="Seed used if val/test splits must be synthesized.")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Fallback validation ratio for train-only exports.")
    parser.add_argument("--test-ratio", type=float, default=0.1, help="Fallback test ratio for train-only exports.")
    return parser.parse_args()


def clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def extract_zip(zip_path: Path, raw_root: Path) -> None:
    if raw_root.exists():
        shutil.rmtree(raw_root)
    raw_root.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path) as handle:
        handle.extractall(raw_root)


def load_raw_yaml(raw_root: Path) -> dict:
    data_yaml = raw_root / "data.yaml"
    if not data_yaml.exists():
        return {}
    payload = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def iter_label_files(raw_root: Path):
    for export_split in EXPORT_SPLITS:
        label_dir = raw_root / export_split / "labels"
        if not label_dir.exists():
            continue
        for label_path in sorted(label_dir.glob("*.txt")):
            yield export_split, label_path


def classify_line(line: str) -> str:
    parts = line.strip().split()
    if not parts:
        return "empty"
    values = parts[1:]
    if len(values) == 4:
        return "detect"
    if len(values) >= 6 and len(values) % 2 == 0:
        return "polygon"
    return "unknown"


def inspect_export_format(raw_root: Path) -> tuple[Counter, list[str]]:
    counts: Counter[str] = Counter()
    unknown_examples: list[str] = []
    for _, label_path in iter_label_files(raw_root):
        for raw_line in label_path.read_text(encoding="utf-8").splitlines():
            label_type = classify_line(raw_line)
            counts[label_type] += 1
            if label_type == "unknown" and len(unknown_examples) < 5:
                unknown_examples.append(f"{label_path.name}: {raw_line[:120]}")
    return counts, unknown_examples


def source_names(raw_yaml: dict) -> list[str]:
    names = raw_yaml.get("names", [])
    if isinstance(names, dict):
        return [str(names[idx]) for idx in sorted(names)]
    if isinstance(names, list):
        return [str(name) for name in names]
    return []


def image_paths_for_split(raw_root: Path, export_split: str) -> list[Path]:
    image_dir = raw_root / export_split / "images"
    if not image_dir.exists():
        return []
    return sorted(path for path in image_dir.iterdir() if path.is_file())


def label_path_for_image(raw_root: Path, export_split: str, image_path: Path) -> Path:
    return raw_root / export_split / "labels" / f"{image_path.stem}.txt"


def label_count_bucket(count: int) -> str:
    if count <= 0:
        return "neg"
    if count == 1:
        return "pos_1"
    if count <= 3:
        return "pos_2_3"
    if count <= 7:
        return "pos_4_7"
    return "pos_8_plus"


def estimate_label_rows(label_path: Path) -> int:
    if not label_path.exists():
        return 0
    count = 0
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        label_type = classify_line(raw_line)
        if label_type in {"detect", "polygon"}:
            count += 1
    return count


def build_split_plan(
    raw_root: Path, seed: int, val_ratio: float, test_ratio: float
) -> tuple[dict[str, list[tuple[str, Path]]], str]:
    grouped: dict[str, list[tuple[str, Path]]] = {"train": [], "val": [], "test": []}
    for export_split, final_split in EXPORT_SPLITS.items():
        for image_path in image_paths_for_split(raw_root, export_split):
            grouped[final_split].append((export_split, image_path))

    total = sum(len(items) for items in grouped.values())
    if total == 0:
        raise RuntimeError("No images were found in the Roboflow export.")

    if grouped["val"] and grouped["test"]:
        return grouped, "source_export_splits"

    target_val = max(len(grouped["val"]), int(round(total * val_ratio)))
    target_test = max(len(grouped["test"]), int(round(total * test_ratio)))

    rng = random.Random(seed)
    buckets: dict[str, list[tuple[str, Path]]] = {}
    for export_split, image_path in grouped["train"]:
        label_path = label_path_for_image(raw_root, export_split, image_path)
        bucket = label_count_bucket(estimate_label_rows(label_path))
        buckets.setdefault(bucket, []).append((export_split, image_path))

    train_pool: list[tuple[str, Path]] = []
    for bucket_items in buckets.values():
        rng.shuffle(bucket_items)
        bucket_total = len(bucket_items)
        bucket_val = min(bucket_total, int(round(bucket_total * val_ratio)))
        remaining_after_val = bucket_total - bucket_val
        bucket_test = min(remaining_after_val, int(round(bucket_total * test_ratio)))
        grouped["val"].extend(bucket_items[:bucket_val])
        grouped["test"].extend(bucket_items[bucket_val : bucket_val + bucket_test])
        train_pool.extend(bucket_items[bucket_val + bucket_test :])

    rng.shuffle(train_pool)
    while len(grouped["val"]) < target_val and train_pool:
        grouped["val"].append(train_pool.pop())
    while len(grouped["test"]) < target_test and train_pool:
        grouped["test"].append(train_pool.pop())

    grouped["train"] = train_pool
    return grouped, "synthetic_val_test_from_train"


def line_to_bbox(line: str, allow_segmentation_to_box: bool) -> tuple[int, list[float]] | None:
    parts = line.strip().split()
    if not parts:
        return None
    cls_id = int(float(parts[0]))
    values = [float(value) for value in parts[1:]]
    if len(values) == 4:
        x_center, y_center, width, height = values
        return cls_id, [clip01(x_center), clip01(y_center), clip01(width), clip01(height)]
    if len(values) >= 6 and len(values) % 2 == 0:
        if not allow_segmentation_to_box:
            raise RuntimeError(
                "This export contains polygon labels, not plain detection boxes. "
                "Export Roboflow as YOLO object detection after merging classes, or rerun with "
                "--allow-segmentation-to-box to accept lossy conversion."
            )
        xs = values[0::2]
        ys = values[1::2]
        min_x = clip01(min(xs))
        max_x = clip01(max(xs))
        min_y = clip01(min(ys))
        max_y = clip01(max(ys))
        width = max_x - min_x
        height = max_y - min_y
        if width <= 0.0 or height <= 0.0:
            return None
        x_center = min_x + width / 2.0
        y_center = min_y + height / 2.0
        return cls_id, [clip01(x_center), clip01(y_center), clip01(width), clip01(height)]
    raise RuntimeError(f"Unsupported label row: {line[:160]}")


def write_detection_label(dest: Path, boxes: list[list[float]]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not boxes:
        dest.write_text("", encoding="utf-8")
        return
    lines = [f"0 {' '.join(f'{value:.6f}' for value in box)}" for box in boxes]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def draw_boxes(image_path: Path, label_path: Path, dest_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            _, x_center, y_center, box_w, box_h = [float(value) for value in parts]
            x1 = int((x_center - box_w / 2.0) * width)
            y1 = int((y_center - box_h / 2.0) * height)
            x2 = int((x_center + box_w / 2.0) * width)
            y2 = int((y_center + box_h / 2.0) * height)
            draw.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=3)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest_path)


def make_image_record(
    final_split: str,
    export_split: str,
    image_path: Path,
    dest_image: Path,
    boxes: list[list[float]],
) -> dict:
    file_hash = sha256_file(dest_image)
    return {
        "image_name": image_path.name,
        "source_split": export_split,
        "split": final_split,
        "sha256": file_hash,
        "box_count": len(boxes),
        "negative": len(boxes) == 0,
    }


def analyze_duplicates(records: list[dict]) -> dict:
    by_hash: dict[str, list[dict]] = {}
    for record in records:
        by_hash.setdefault(record["sha256"], []).append(record)

    duplicate_groups = [group for group in by_hash.values() if len(group) > 1]
    cross_split = []
    within_split = []
    for group in duplicate_groups:
        split_names = sorted({item["split"] for item in group})
        payload = {
            "sha256": group[0]["sha256"],
            "count": len(group),
            "splits": split_names,
            "images": [{"image_name": item["image_name"], "split": item["split"]} for item in group],
        }
        if len(split_names) > 1:
            cross_split.append(payload)
        else:
            within_split.append(payload)

    return {
        "duplicate_group_count": len(duplicate_groups),
        "cross_split_duplicate_count": len(cross_split),
        "within_split_duplicate_count": len(within_split),
        "cross_split_duplicates": cross_split,
        "within_split_duplicates": within_split[:50],
    }


def build_dataset_card(workspace: Path, stats: dict, split_rows: dict[str, dict], duplicates: dict) -> str:
    lines = [
        "# Dataset Card",
        "",
        f"- Workspace: `{workspace}`",
        f"- Conversion mode: `{stats['conversion_mode']}`",
        f"- Split strategy: `{stats['split_strategy']}`",
        f"- Total converted boxes: `{stats['converted_box_count']}`",
        f"- Negative images: `{stats['negative_images']}`",
        f"- Cross-split duplicate groups: `{duplicates['cross_split_duplicate_count']}`",
        "",
        "## Split Summary",
        "",
        "| split | images | positive_images | negative_images | boxes |",
        "| ----- | ------ | --------------- | --------------- | ---- |",
    ]
    for split in ("train", "val", "test"):
        row = split_rows[split]
        lines.append(
            f"| {split} | {row['images']} | {row['positive_images']} | {row['negative_images']} | {row['boxes']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    zip_path = Path(args.zip).resolve()
    workspace = Path(args.workspace).resolve()
    raw_root = workspace / "data" / "raw_roboflow"
    prep_root = workspace / "artifacts" / "prep"
    qa_root = prep_root / "qa_samples"

    extract_zip(zip_path, raw_root)
    raw_yaml = load_raw_yaml(raw_root)
    format_counts, unknown_examples = inspect_export_format(raw_root)

    if format_counts.get("unknown"):
        raise RuntimeError(
            "Unsupported label rows were found in the export. Examples: " + "; ".join(unknown_examples)
        )
    if format_counts.get("polygon") and not args.allow_segmentation_to_box:
        raise RuntimeError(
            "The export is segmentation-style YOLO, not plain detection. "
            "Re-export as YOLO object detection after merging classes to damage, or rerun with "
            "--allow-segmentation-to-box if you deliberately accept lossy conversion."
        )

    data_root = workspace / "data"
    if (data_root / "train").exists():
        shutil.rmtree(data_root / "train")
    if (data_root / "val").exists():
        shutil.rmtree(data_root / "val")
    if (data_root / "test").exists():
        shutil.rmtree(data_root / "test")
    if prep_root.exists():
        shutil.rmtree(prep_root)

    for split in ("train", "val", "test"):
        (data_root / split / "images").mkdir(parents=True, exist_ok=True)
        (data_root / split / "labels").mkdir(parents=True, exist_ok=True)

    source_class_counts: Counter[int] = Counter()
    converted_box_count = 0
    negative_images = 0
    bbox_widths: list[float] = []
    bbox_heights: list[float] = []
    suspicious_boxes: list[dict] = []
    qa_written = 0
    image_records: list[dict] = []

    split_plan, split_strategy = build_split_plan(raw_root, args.seed, args.val_ratio, args.test_ratio)

    for final_split in ("train", "val", "test"):
        for export_split, image_path in split_plan[final_split]:
            dest_image = data_root / final_split / "images" / image_path.name
            dest_label = data_root / final_split / "labels" / f"{image_path.stem}.txt"
            shutil.copy2(image_path, dest_image)

            label_path = label_path_for_image(raw_root, export_split, image_path)
            boxes: list[list[float]] = []
            if label_path.exists():
                for raw_line in label_path.read_text(encoding="utf-8").splitlines():
                    converted = line_to_bbox(raw_line, args.allow_segmentation_to_box)
                    if not converted:
                        continue
                    source_cls, bbox = converted
                    source_class_counts[source_cls] += 1
                    boxes.append(bbox)
                    bbox_widths.append(bbox[2])
                    bbox_heights.append(bbox[3])
                    converted_box_count += 1
                    area = bbox[2] * bbox[3]
                    if area >= 0.35 or bbox[2] >= 0.8 or bbox[3] >= 0.8:
                        suspicious_boxes.append(
                            {
                                "split": final_split,
                                "image": image_path.name,
                                "bbox": [round(value, 6) for value in bbox],
                                "area": round(area, 6),
                            }
                        )
            if not boxes:
                negative_images += 1
            write_detection_label(dest_label, boxes)
            image_records.append(make_image_record(final_split, export_split, image_path, dest_image, boxes))

            if boxes and qa_written < args.qa_samples:
                qa_written += 1
                draw_boxes(dest_image, dest_label, qa_root / f"sample_{qa_written:02d}_{image_path.name}")

    dataset_yaml = {
        "path": str(workspace),
        "train": "data/train/images",
        "val": "data/val/images",
        "test": "data/test/images",
        "nc": 1,
        "names": {0: "damage"},
    }
    dump_yaml(workspace / "configs" / "dataset.yaml", dataset_yaml)

    split_rows: dict[str, dict] = {}
    for split in ("train", "val", "test"):
        records = [record for record in image_records if record["split"] == split]
        split_rows[split] = {
            "images": len(records),
            "positive_images": sum(1 for record in records if not record["negative"]),
            "negative_images": sum(1 for record in records if record["negative"]),
            "boxes": sum(int(record["box_count"]) for record in records),
        }
    duplicates = analyze_duplicates(image_records)

    stats = {
        "zip_path": str(zip_path),
        "workspace": str(workspace),
        "source_class_names": source_names(raw_yaml),
        "source_class_counts": dict(sorted(source_class_counts.items())),
        "source_label_formats": dict(sorted(format_counts.items())),
        "conversion_mode": "segmentation_to_axis_aligned_boxes" if format_counts.get("polygon") else "detect_pass_through",
        "allow_segmentation_to_box": bool(args.allow_segmentation_to_box),
        "split_strategy": split_strategy,
        "splits": {split: split_rows[split]["images"] for split in ("train", "val", "test")},
        "split_breakdown": split_rows,
        "converted_box_count": converted_box_count,
        "negative_images": negative_images,
        "avg_bbox_width": round(sum(bbox_widths) / len(bbox_widths), 6) if bbox_widths else 0.0,
        "avg_bbox_height": round(sum(bbox_heights) / len(bbox_heights), 6) if bbox_heights else 0.0,
        "qa_samples_dir": str(qa_root),
        "dataset_fingerprint_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "image_name": record["image_name"],
                        "split": record["split"],
                        "sha256": record["sha256"],
                        "box_count": record["box_count"],
                    }
                    for record in sorted(image_records, key=lambda item: (item["split"], item["image_name"]))
                ],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    dump_json(prep_root / "dataset_stats.json", stats)
    suspicious_boxes = sorted(suspicious_boxes, key=lambda item: item["area"], reverse=True)[:50]
    dump_json(prep_root / "suspicious_boxes.json", {"count": len(suspicious_boxes), "items": suspicious_boxes})
    dump_json(prep_root / "split_manifest.json", {"records": image_records})
    dump_json(prep_root / "duplicate_report.json", duplicates)
    (prep_root / "DATASET_CARD.md").write_text(build_dataset_card(workspace, stats, split_rows, duplicates), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
