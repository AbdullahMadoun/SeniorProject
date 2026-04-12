from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply light offline augmentation to the train split of a YOLO detection dataset."
    )
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of train images augmented. 0 means all positive train images.",
    )
    return parser.parse_args()


def read_boxes(label_path: Path) -> list[list[float]]:
    boxes: list[list[float]] = []
    if not label_path.exists():
        return boxes
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, x_center, y_center, width, height = [float(value) for value in parts]
        boxes.append([x_center, y_center, width, height])
    return boxes


def write_boxes(label_path: Path, boxes: list[list[float]]) -> None:
    if not boxes:
        label_path.write_text("", encoding="utf-8")
        return
    lines = [f"0 {' '.join(f'{value:.6f}' for value in box)}" for box in boxes]
    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def flip_boxes(boxes: list[list[float]]) -> list[list[float]]:
    return [[1.0 - x_center, y_center, width, height] for x_center, y_center, width, height in boxes]


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    dataset_root = Path(args.dataset_root).resolve()
    train_images = dataset_root / "train" / "images"
    train_labels = dataset_root / "train" / "labels"
    artifact_root = dataset_root.parent / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    candidates = []
    for image_path in sorted(train_images.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        label_path = train_labels / f"{image_path.stem}.txt"
        if read_boxes(label_path):
            candidates.append((image_path, label_path))

    rng.shuffle(candidates)
    if args.limit > 0:
        candidates = candidates[: args.limit]

    created = {
        "flipped": 0,
        "jittered": 0,
        "source_images_augmented": len(candidates),
    }

    for index, (image_path, label_path) in enumerate(candidates):
        boxes = read_boxes(label_path)
        image = Image.open(image_path).convert("RGB")

        flip_name = f"{image_path.stem}_augflip{image_path.suffix}"
        flip_path = train_images / flip_name
        image.transpose(Image.FLIP_LEFT_RIGHT).save(flip_path)
        write_boxes(train_labels / f"{Path(flip_name).stem}.txt", flip_boxes(boxes))
        created["flipped"] += 1

        brightness = 0.85 if index % 2 == 0 else 1.15
        jittered = ImageEnhance.Brightness(image).enhance(brightness).filter(ImageFilter.GaussianBlur(radius=1.0))
        jitter_name = f"{image_path.stem}_augjitter{image_path.suffix}"
        jitter_path = train_images / jitter_name
        jittered.save(jitter_path)
        write_boxes(train_labels / f"{Path(jitter_name).stem}.txt", boxes)
        created["jittered"] += 1

    stats_path = artifact_root / "augmentation_stats.json"
    stats_path.write_text(json.dumps(created, indent=2), encoding="utf-8")
    print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()
