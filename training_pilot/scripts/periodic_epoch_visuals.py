from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import IMAGE_SUFFIXES, load_yaml, read_yolo_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render annotated validation previews every N epochs.")
    parser.add_argument("--run-dir", required=True, help="Ultralytics run directory.")
    parser.add_argument("--data-yaml", required=True, help="Dataset yaml used for training.")
    parser.add_argument("--split", default="val", choices=["train", "val", "test"], help="Dataset split to sample from.")
    parser.add_argument("--epoch-step", type=int, default=25, help="Render previews every N epochs.")
    parser.add_argument("--sample-count", type=int, default=8, help="How many fixed images to render each cycle.")
    parser.add_argument("--conf", type=float, default=0.25, help="Prediction confidence threshold.")
    parser.add_argument("--imgsz", type=int, default=1024, help="Inference size for preview rendering.")
    parser.add_argument("--device", default="cpu", help="Prediction device. Defaults to CPU to avoid interfering with training.")
    parser.add_argument("--poll-seconds", type=float, default=30.0, help="How often to inspect results.csv.")
    parser.add_argument("--idle-timeout-seconds", type=float, default=5400.0, help="Exit after this much idle time.")
    return parser.parse_args()


def resolve_split_dirs(data_yaml_path: Path, split: str) -> tuple[Path, Path]:
    payload = load_yaml(data_yaml_path)
    base = Path(payload["path"]).resolve() if payload.get("path") else data_yaml_path.parent.resolve()
    split_value = payload.get(split)
    if split_value is None:
        raise KeyError(f"Dataset yaml does not declare split '{split}'.")
    image_dir = Path(split_value)
    if not image_dir.is_absolute():
        image_dir = (base / image_dir).resolve()
    label_dir = image_dir.parent / "labels"
    if not image_dir.exists():
        raise FileNotFoundError(f"Missing image dir for split '{split}': {image_dir}")
    if not label_dir.exists():
        raise FileNotFoundError(f"Missing label dir for split '{split}': {label_dir}")
    return image_dir, label_dir


def choose_sample_images(image_dir: Path, label_dir: Path, count: int) -> list[Path]:
    positives: list[Path] = []
    negatives: list[Path] = []
    for image_path in sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES):
        label_path = label_dir / f"{image_path.stem}.txt"
        rows = read_yolo_rows(label_path)
        if rows:
            positives.append(image_path)
        else:
            negatives.append(image_path)
    selected = positives[:count]
    if len(selected) < count:
        selected.extend(negatives[: count - len(selected)])
    if not selected:
        raise RuntimeError(f"No preview images found under {image_dir}")
    return selected


def read_results_rows(results_csv: Path) -> list[dict[str, str]]:
    if not results_csv.exists():
        return []
    with results_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def yolo_rows_to_xyxy(rows: list[tuple[int, list[float]]], width: int, height: int) -> list[list[float]]:
    boxes: list[list[float]] = []
    for _, (x_center, y_center, box_w, box_h) in rows:
        x1 = (x_center - box_w / 2.0) * width
        y1 = (y_center - box_h / 2.0) * height
        x2 = (x_center + box_w / 2.0) * width
        y2 = (y_center + box_h / 2.0) * height
        boxes.append([x1, y1, x2, y2])
    return boxes


def draw_box(draw: ImageDraw.ImageDraw, box: list[float], color: str, label: str) -> None:
    x1, y1, x2, y2 = box
    draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
    if label:
        font = ImageFont.load_default()
        draw.text((x1 + 4, max(0, y1 - 12)), label, fill=color, font=font)


def render_epoch(run_dir: Path, checkpoint_path: Path, sample_images: list[Path], label_dir: Path, args: argparse.Namespace, epoch: int) -> None:
    from ultralytics import YOLO

    model = YOLO(str(checkpoint_path))
    output_dir = run_dir / "epoch_visuals" / f"epoch_{epoch:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "epoch": epoch,
        "checkpoint": str(checkpoint_path),
        "samples": [],
    }

    for image_path in sample_images:
        label_path = label_dir / f"{image_path.stem}.txt"
        with Image.open(image_path) as raw:
            image = raw.convert("RGB")
        width, height = image.size
        result = model.predict(
            source=str(image_path),
            conf=args.conf,
            imgsz=args.imgsz,
            device=args.device,
            verbose=False,
        )[0]
        draw = ImageDraw.Draw(image)
        for gt_box in yolo_rows_to_xyxy(read_yolo_rows(label_path), width, height):
            draw_box(draw, gt_box, "#00ff66", "GT")
        pred_count = 0
        if result.boxes is not None:
            for xyxy, score in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                pred_count += 1
                draw_box(draw, [float(v) for v in xyxy], "#ff3355", f"P {float(score):.2f}")
        draw.text((10, 10), f"epoch {epoch} | GT green | Pred red", fill="#ffffff", font=ImageFont.load_default())
        output_path = output_dir / image_path.name
        image.save(output_path)
        manifest["samples"].append(
            {
                "image": image_path.name,
                "output": str(output_path),
                "ground_truth_boxes": len(read_yolo_rows(label_path)),
                "predicted_boxes": pred_count,
            }
        )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    data_yaml = Path(args.data_yaml).resolve()
    results_csv = run_dir / "results.csv"
    weights_dir = run_dir / "weights"
    image_dir, label_dir = resolve_split_dirs(data_yaml, args.split)
    sample_images = choose_sample_images(image_dir, label_dir, args.sample_count)
    state_path = run_dir / "epoch_visuals" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_epochs: set[int] = set()
    if state_path.exists():
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        rendered_epochs = {int(value) for value in payload.get("rendered_epochs", [])}
    unchanged_since = time.time()

    while True:
        rows = read_results_rows(results_csv)
        if rows:
            newest_epoch = int(float(rows[-1]["epoch"]))
            unchanged_since = time.time()
            target_epochs = [epoch for epoch in range(args.epoch_step, newest_epoch + 1, args.epoch_step)]
            for epoch in target_epochs:
                if epoch in rendered_epochs:
                    continue
                checkpoint_path = weights_dir / f"epoch{epoch}.pt"
                if not checkpoint_path.exists():
                    continue
                render_epoch(run_dir, checkpoint_path, sample_images, label_dir, args, epoch)
                rendered_epochs.add(epoch)
                state_path.write_text(
                    json.dumps({"rendered_epochs": sorted(rendered_epochs), "samples": [path.name for path in sample_images]}, indent=2),
                    encoding="utf-8",
                )
        if time.time() - unchanged_since >= args.idle_timeout_seconds:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()

