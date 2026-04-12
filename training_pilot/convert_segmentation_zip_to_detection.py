from __future__ import annotations

import argparse
import json
import random
import shutil
import zipfile
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image, ImageDraw


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a YOLOv8 segmentation export zip into a single-class detection dataset."
    )
    parser.add_argument("--zip", required=True, help="Path to the Roboflow zip export.")
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace directory where raw export, canonical dataset, and artifacts will be created.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--qa-samples", type=int, default=12)
    return parser.parse_args()


def clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def convert_line_to_bbox(line: str) -> tuple[int, list[float]] | None:
    parts = line.strip().split()
    if not parts:
        return None

    cls_id = int(float(parts[0]))
    values = [float(v) for v in parts[1:]]

    if len(values) == 4:
        x_center, y_center, width, height = values
        return cls_id, [clip01(x_center), clip01(y_center), clip01(width), clip01(height)]

    if len(values) < 6 or len(values) % 2 != 0:
        return None

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


def load_names(raw_root: Path) -> list[str]:
    data_yaml = raw_root / "data.yaml"
    if not data_yaml.exists():
        return []

    payload = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    names = payload.get("names", [])
    if isinstance(names, dict):
        return [names[idx] for idx in sorted(names)]
    if isinstance(names, list):
        return names
    return []


def gather_images(raw_root: Path) -> list[Path]:
    images: list[Path] = []
    for split in ("train", "valid", "val", "test"):
        image_dir = raw_root / split / "images"
        if not image_dir.exists():
            continue
        for path in sorted(image_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                images.append(path)
    return images


def write_label_file(dest: Path, boxes: list[list[float]]) -> None:
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
            draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=3)

    image.save(dest_path)


def main() -> None:
    args = parse_args()
    train_ratio = args.train_ratio
    val_ratio = args.val_ratio
    test_ratio = args.test_ratio
    if abs((train_ratio + val_ratio + test_ratio) - 1.0) > 1e-6:
        raise ValueError("train/val/test ratios must sum to 1.0")

    workspace = Path(args.workspace).resolve()
    zip_path = Path(args.zip).resolve()

    raw_root = workspace / "raw_export"
    dataset_root = workspace / "dataset"
    artifact_root = workspace / "artifacts"
    qa_root = artifact_root / "qa_samples"
    stats_path = artifact_root / "dataset_stats.json"

    if raw_root.exists():
        shutil.rmtree(raw_root)
    if dataset_root.exists():
        shutil.rmtree(dataset_root)
    if artifact_root.exists():
        shutil.rmtree(artifact_root)

    raw_root.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(raw_root)

    source_names = load_names(raw_root)
    image_paths = gather_images(raw_root)
    if not image_paths:
        raise RuntimeError(f"No images found after extracting {zip_path}")

    rng = random.Random(args.seed)
    rng.shuffle(image_paths)

    total = len(image_paths)
    train_cut = int(total * train_ratio)
    val_cut = train_cut + int(total * val_ratio)
    split_map: dict[str, list[Path]] = {
        "train": image_paths[:train_cut],
        "val": image_paths[train_cut:val_cut],
        "test": image_paths[val_cut:],
    }

    for split in split_map:
        (dataset_root / split / "images").mkdir(parents=True, exist_ok=True)
        (dataset_root / split / "labels").mkdir(parents=True, exist_ok=True)

    source_class_counts: Counter[int] = Counter()
    converted_box_count = 0
    negative_images = 0
    bbox_widths: list[float] = []
    bbox_heights: list[float] = []

    written_samples: list[tuple[Path, Path]] = []

    for split, split_images in split_map.items():
        for image_path in split_images:
            dest_image = dataset_root / split / "images" / image_path.name
            shutil.copy2(image_path, dest_image)

            label_path = image_path.parents[1] / "labels" / f"{image_path.stem}.txt"
            boxes: list[list[float]] = []
            if label_path.exists():
                for raw_line in label_path.read_text(encoding="utf-8").splitlines():
                    converted = convert_line_to_bbox(raw_line)
                    if not converted:
                        continue
                    source_cls, bbox = converted
                    source_class_counts[source_cls] += 1
                    boxes.append(bbox)
                    bbox_widths.append(bbox[2])
                    bbox_heights.append(bbox[3])
                    converted_box_count += 1

            if not boxes:
                negative_images += 1

            dest_label = dataset_root / split / "labels" / f"{image_path.stem}.txt"
            write_label_file(dest_label, boxes)

            if len(written_samples) < args.qa_samples:
                written_samples.append((dest_image, dest_label))

    data_yaml = {
        "path": str(dataset_root),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "nc": 1,
        "names": {0: "damage"},
        "source_names": source_names,
    }
    (dataset_root / "data.yaml").write_text(
        yaml.safe_dump(data_yaml, sort_keys=False),
        encoding="utf-8",
    )

    for index, (image_path, label_path) in enumerate(written_samples, start=1):
        draw_boxes(image_path, label_path, qa_root / f"sample_{index:02d}_{image_path.name}")

    stats = {
        "zip_path": str(zip_path),
        "workspace": str(workspace),
        "source_class_names": source_names,
        "source_class_counts": dict(sorted(source_class_counts.items())),
        "total_images": total,
        "splits": {split: len(paths) for split, paths in split_map.items()},
        "converted_box_count": converted_box_count,
        "negative_images": negative_images,
        "avg_bbox_width": round(sum(bbox_widths) / len(bbox_widths), 6) if bbox_widths else 0.0,
        "avg_bbox_height": round(sum(bbox_heights) / len(bbox_heights), 6) if bbox_heights else 0.0,
        "qa_samples_dir": str(qa_root),
    }
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
