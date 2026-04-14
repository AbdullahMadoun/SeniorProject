from __future__ import annotations

import argparse
import hashlib
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import cv2
except Exception:  # pragma: no cover - optional import fallback
    cv2 = None

from PIL import Image

from common import IMAGE_SUFFIXES, dump_json, load_yaml, resolve_project_root


class AuditFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run harsh one-shot pre-flight checks before any YOLO training is allowed to start."
    )
    parser.add_argument("--project-root", default="", help="training_pilot root. Defaults to the local repo copy.")
    parser.add_argument("--data-yaml", default="", help="Optional explicit dataset.yaml path.")
    parser.add_argument(
        "--output-json",
        default="artifacts/prep/harsh_dataset_audit.json",
        help="Where to write the audit summary relative to project root.",
    )
    parser.add_argument(
        "--min-train-images-exclusive",
        type=int,
        default=1000,
        help="Exclusive lower bound for the train image count assert. Default matches the current override: >1000.",
    )
    return parser.parse_args()


def resolve_data_yaml(project_root: Path, raw: str) -> Path:
    if raw:
        path = Path(raw)
        return path.resolve() if path.is_absolute() else (project_root / path).resolve()
    path = project_root / "configs" / "dataset.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset yaml: {path}. Build the train/val/test split first.")
    return path.resolve()


def resolve_dataset_root(data_yaml_path: Path, dataset_yaml: dict[str, Any]) -> Path:
    path_value = dataset_yaml.get("path")
    if not path_value:
        return data_yaml_path.parent.resolve()
    path = Path(str(path_value))
    return path.resolve() if path.is_absolute() else (data_yaml_path.parent / path).resolve()


def resolve_split_dirs(data_yaml_path: Path) -> tuple[Path, dict[str, dict[str, Path]]]:
    payload = load_yaml(data_yaml_path)
    dataset_root = resolve_dataset_root(data_yaml_path, payload)
    split_dirs: dict[str, dict[str, Path]] = {}
    for split in ("train", "val", "test"):
        entry = payload.get(split)
        if not entry:
            raise FileNotFoundError(f"Dataset yaml {data_yaml_path} is missing '{split}'")
        image_dir = Path(str(entry))
        image_dir = image_dir.resolve() if image_dir.is_absolute() else (dataset_root / image_dir).resolve()
        if image_dir.name != "images":
            raise RuntimeError(
                f"Expected '{split}' to point to an images/ directory, got {image_dir}. "
                "The harsh audit only supports the repo's standard images/labels split layout."
            )
        label_dir = (image_dir.parent / "labels").resolve()
        split_dirs[split] = {"images": image_dir, "labels": label_dir}
    return dataset_root, split_dirs


def list_images(image_dir: Path) -> list[Path]:
    if not image_dir.exists():
        raise FileNotFoundError(f"Missing image directory: {image_dir}")
    return sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def verify_image(path: Path) -> None:
    if cv2 is not None:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("cv2.imread() returned None")
    with Image.open(path) as img:
        img.verify()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def label_for_image(image_path: Path, label_dir: Path) -> Path:
    return label_dir / f"{image_path.stem}.txt"


def purge_corrupted_images(split: str, image_dir: Path, label_dir: Path) -> tuple[list[Path], list[dict[str, str]]]:
    healthy: list[Path] = []
    removed: list[dict[str, str]] = []
    for image_path in list_images(image_dir):
        try:
            verify_image(image_path)
        except Exception as exc:
            label_path = label_for_image(image_path, label_dir)
            if image_path.exists():
                image_path.unlink()
            if label_path.exists():
                label_path.unlink()
            removed.append(
                {
                    "split": split,
                    "image": str(image_path),
                    "label": str(label_path),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        healthy.append(image_path)
    return healthy, removed


def parse_label_rows(label_path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line_no, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != 5:
            raise AuditFailure(f"{label_path}:{line_no} has {len(parts)} fields, expected exactly 5 for YOLO boxes")
        rows.append(parts)
    return rows


def audit_label_health(split_dirs: dict[str, dict[str, Path]]) -> list[str]:
    failures: list[str] = []
    for split, dirs in split_dirs.items():
        image_dir = dirs["images"]
        label_dir = dirs["labels"]
        if not label_dir.exists():
            failures.append(f"{split}: missing label directory {label_dir}")
            continue

        image_stems = {path.stem for path in list_images(image_dir)}
        for label_path in sorted(label_dir.glob("*.txt")):
            if label_path.stem not in image_stems:
                failures.append(f"{split}: orphan label without matching image -> {label_path}")
                continue
            try:
                rows = parse_label_rows(label_path)
            except AuditFailure as exc:
                failures.append(str(exc))
                continue

            for line_no, parts in enumerate(rows, start=1):
                try:
                    coords = [float(value) for value in parts[1:5]]
                except ValueError as exc:
                    failures.append(f"{label_path}:{line_no} contains non-numeric YOLO coordinates: {exc}")
                    continue
                for value in coords:
                    if math.isnan(value) or math.isinf(value) or value < 0.0 or value > 1.0:
                        failures.append(
                            f"{label_path}:{line_no} has out-of-range coordinate {value}; expected all bbox values in [0.0, 1.0]"
                        )
    return failures


def build_hash_index(paths: list[Path]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        index[sha256_file(path)].append(str(path))
    return dict(index)


def audit_leakage(split_images: dict[str, list[Path]]) -> list[str]:
    failures: list[str] = []
    hash_index = {split: build_hash_index(paths) for split, paths in split_images.items()}
    pairs = (("train", "val"), ("train", "test"), ("val", "test"))
    for left, right in pairs:
        overlap = sorted(set(hash_index[left]).intersection(hash_index[right]))
        for digest in overlap:
            failures.append(
                f"sha256 overlap between {left} and {right}: {digest} -> {hash_index[left][digest][0]} | {hash_index[right][digest][0]}"
            )
    return failures


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    output_json = (project_root / args.output_json).resolve()
    data_yaml_path = resolve_data_yaml(project_root, args.data_yaml)
    _, split_dirs = resolve_split_dirs(data_yaml_path)

    summary: dict[str, Any] = {
        "data_yaml": str(data_yaml_path),
        "splits": {},
        "corrupted_purged": [],
        "failures": [],
        "status": "running",
    }

    split_images: dict[str, list[Path]] = {}
    for split, dirs in split_dirs.items():
        healthy_images, removed = purge_corrupted_images(split, dirs["images"], dirs["labels"])
        split_images[split] = healthy_images
        summary["splits"][split] = {
            "image_dir": str(dirs["images"]),
            "label_dir": str(dirs["labels"]),
            "healthy_images": len(healthy_images),
            "purged_corrupted_images": len(removed),
        }
        summary["corrupted_purged"].extend(removed)

    train_count = len(split_images["train"])
    if train_count <= int(args.min_train_images_exclusive):
        summary["failures"].append(
            f"Quantity assert failed: len(train_images)={train_count}, expected > {int(args.min_train_images_exclusive)} before training is allowed."
        )

    summary["failures"].extend(audit_label_health(split_dirs))
    summary["failures"].extend(audit_leakage(split_images))

    if summary["failures"]:
        summary["status"] = "fail"
        dump_json(output_json, summary)
        for failure in summary["failures"]:
            print(f"[FAIL] {failure}")
        raise AuditFailure("HARSH DATASET AUDIT FAILED")

    summary["status"] = "pass"
    dump_json(output_json, summary)
    print("[PASS] ALL CHECKS CLEARED")


if __name__ == "__main__":
    try:
        main()
    except AuditFailure as exc:
        print(f"[FAIL] {exc}")
        sys.exit(1)
