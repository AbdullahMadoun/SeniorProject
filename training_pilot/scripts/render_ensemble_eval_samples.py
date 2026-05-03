from __future__ import annotations

import argparse
import json
import random
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render random annotated ensemble eval samples.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--eval-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def to_abs(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (
        int(round(x1 * width)),
        int(round(y1 * height)),
        int(round(x2 * width)),
        int(round(y2 * height)),
    )


def draw_boxes(image: Image.Image, record: dict) -> Image.Image:
    canvas = image.copy().convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    w, h = canvas.size

    for box in record.get("gt_boxes", []):
        draw.rectangle(to_abs(box, w, h), outline=(60, 220, 90), width=3)

    for box, score in zip(record.get("fused_boxes", []), record.get("fused_scores", [])):
        rect = to_abs(box, w, h)
        draw.rectangle(rect, outline=(255, 80, 80), width=2)
        label = f"{score:.2f}"
        draw.text((rect[0] + 4, max(0, rect[1] - 12)), label, fill=(255, 80, 80), font=font)

    banner = (
        f"{record['image']} | gt={record['gt_count']} pred={record['pred_count']} "
        f"matched={record['matched_gt']} all_found={record['all_found']}"
    )
    draw.rectangle((0, 0, w, 16), fill=(0, 0, 0))
    draw.text((4, 2), banner, fill=(255, 255, 255), font=font)
    return canvas


def build_contact_sheet(images: list[Image.Image], output_path: Path) -> None:
    if not images:
        return
    thumb_w = 480
    thumb_h = 270
    cols = 2
    rows = ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), color=(20, 20, 20))
    for idx, image in enumerate(images):
        thumb = image.copy()
        thumb.thumbnail((thumb_w, thumb_h))
        x = (idx % cols) * thumb_w
        y = (idx // cols) * thumb_h
        sheet.paste(thumb, (x, y))
    sheet.save(output_path)


def main() -> None:
    args = parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    eval_json = Path(args.eval_json).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(eval_json.read_text(encoding="utf-8"))
    per_image = payload.get("per_image", [])
    rng = random.Random(args.seed)
    sample = rng.sample(per_image, min(args.count, len(per_image)))

    rendered: list[Image.Image] = []
    image_dir = dataset_root / payload["split"] / "images"
    for idx, record in enumerate(sample, start=1):
        image_path = image_dir / record["image"]
        with Image.open(image_path) as image:
            annotated = draw_boxes(image, record)
        rendered.append(annotated)
        annotated.save(output_dir / f"{idx:02d}_{Path(record['image']).name}")

    build_contact_sheet(rendered, output_dir / "contact_sheet.jpg")
    (output_dir / "sample_manifest.json").write_text(json.dumps(sample, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
