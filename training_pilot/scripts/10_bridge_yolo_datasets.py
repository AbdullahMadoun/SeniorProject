from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from common import (
    IMAGE_SUFFIXES,
    dump_json,
    dump_yaml,
    ensure_clean_dir,
    read_yolo_rows,
    resolve_project_root,
    write_yolo_rows,
)


DATASET_B_SLUG = "alvarobasily/road-damage"
SPLIT_ALIASES = {
    "train": "train",
    "training": "train",
    "valid": "val",
    "validation": "val",
    "val": "val",
    "test": "test",
    "testing": "test",
}


@dataclass(frozen=True)
class PairRecord:
    split: str
    image_path: Path
    label_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download, remap, dedupe, and merge Dataset B (Kaggle) into Dataset A for YOLOv8."
    )
    parser.add_argument("--project-root", default="", help="training_pilot root. Defaults to the local repo copy.")
    parser.add_argument(
        "--dataset-a-root",
        required=True,
        help="Path to Dataset A root. Supports YOLO split layout or a flat images/labels layout.",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Download/extract root for Dataset B, relative to training_pilot unless absolute.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/unified_bridge",
        help="Merged YOLO dataset root, relative to training_pilot unless absolute.",
    )
    parser.add_argument(
        "--dataset-b-slug",
        default=DATASET_B_SLUG,
        help="Kaggle dataset slug for Dataset B.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download Dataset B even if the zip already exists locally.",
    )
    parser.add_argument(
        "--delete-staging-after-merge",
        action="store_true",
        help="Delete the normalized deduped Dataset B staging tree after the merged dataset is built.",
    )
    return parser.parse_args()


def resolve_path(project_root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def run_command(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def slug_stem(slug: str) -> str:
    return slug.replace("/", "-").replace("\\", "-")


def dataset_b_paths(raw_dir: Path, slug: str) -> tuple[Path, Path]:
    stem = slug_stem(slug)
    slug_leaf = slug.split("/")[-1]
    zip_path = raw_dir / f"{slug_leaf}.zip"
    extracted_root = raw_dir / stem
    return zip_path, extracted_root


def download_dataset_b(raw_dir: Path, slug: str, force_download: bool) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path, _ = dataset_b_paths(raw_dir, slug)
    legacy_zip_path = raw_dir / f"{slug_stem(slug)}.zip"
    if force_download:
        for candidate in (zip_path, legacy_zip_path):
            if candidate.exists():
                candidate.unlink()
    if not zip_path.exists():
        run_command(["kaggle", "datasets", "download", "-d", slug, "-p", str(raw_dir)])
    if not zip_path.exists() and legacy_zip_path.exists():
        zip_path = legacy_zip_path
    if not zip_path.exists():
        raise FileNotFoundError(
            f"Kaggle download did not create the expected archive for slug '{slug}'. "
            f"Checked: {zip_path} and {legacy_zip_path}."
        )
    return zip_path


def extract_zip(zip_path: Path, extracted_root: Path) -> None:
    ensure_clean_dir(extracted_root)
    with ZipFile(zip_path) as handle:
        handle.extractall(extracted_root)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_split_from_path(path: Path) -> str:
    normalized_parts = [part.lower() for part in path.parts]
    for part in reversed(normalized_parts):
        if part in SPLIT_ALIASES:
            return SPLIT_ALIASES[part]
    return "train"


def stem_image_candidates(label_path: Path) -> list[Path]:
    return [label_path.with_suffix(suffix) for suffix in sorted(IMAGE_SUFFIXES)]


def indexed_image_lookup(root: Path) -> dict[str, list[Path]]:
    by_stem: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        by_stem.setdefault(path.stem, []).append(path)
    return by_stem


def discover_pairs(dataset_root: Path) -> list[PairRecord]:
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root does not exist: {dataset_root}")

    split_roots = [
        (alias, dataset_root / alias)
        for alias in ("train", "val", "test", "valid")
        if (dataset_root / alias).is_dir()
    ]

    label_files: list[Path]
    if split_roots:
        label_files = []
        for _, split_root in split_roots:
            labels_dir = split_root / "labels"
            if not labels_dir.is_dir():
                continue
            label_files.extend(
                sorted(
                    path
                    for path in labels_dir.rglob("*.txt")
                    if path.is_file() and path.name.lower() != "classes.txt"
                )
            )
    else:
        label_files = sorted(
            path
            for path in dataset_root.rglob("*.txt")
            if path.is_file() and path.name.lower() != "classes.txt"
        )
    if not label_files:
        raise RuntimeError(f"No YOLO label files were found under {dataset_root}")

    image_index = indexed_image_lookup(dataset_root)
    pairs: list[PairRecord] = []
    for label_path in label_files:
        image_path = None
        for candidate in stem_image_candidates(label_path):
            if candidate.exists():
                image_path = candidate
                break
        if image_path is None and label_path.parent.name.lower() == "labels":
            for suffix in sorted(IMAGE_SUFFIXES):
                candidate = label_path.parent.parent / "images" / f"{label_path.stem}{suffix}"
                if candidate.exists():
                    image_path = candidate
                    break
        if image_path is None:
            candidates = image_index.get(label_path.stem, [])
            if len(candidates) == 1:
                image_path = candidates[0]
        if image_path is None:
            raise FileNotFoundError(f"Could not resolve the image for label file {label_path}")
        pairs.append(
            PairRecord(
                split=detect_split_from_path(label_path.relative_to(dataset_root)),
                image_path=image_path.resolve(),
                label_path=label_path.resolve(),
            )
        )
    return pairs


def safe_image_name(prefix: str, image_path: Path) -> str:
    relative = image_path.with_suffix("")
    slug = "__".join(relative.parts)
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in slug)
    return f"{prefix}__{safe}{image_path.suffix.lower()}"


def copy_dataset_a(dataset_a_root: Path, output_dir: Path) -> tuple[list[dict[str, Any]], set[str]]:
    records: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for pair in discover_pairs(dataset_a_root):
        relative_image = pair.image_path.relative_to(dataset_a_root)
        image_hash = sha256_file(pair.image_path)
        dest_image = output_dir / pair.split / "images" / safe_image_name("dataset_a", relative_image)
        dest_label = output_dir / pair.split / "labels" / f"{dest_image.stem}.txt"
        dest_image.parent.mkdir(parents=True, exist_ok=True)
        dest_label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pair.image_path, dest_image)
        shutil.copy2(pair.label_path, dest_label)
        hashes.add(image_hash)
        records.append(
            {
                "source_dataset": "A",
                "split": pair.split,
                "source_image": str(pair.image_path),
                "source_label": str(pair.label_path),
                "merged_image": str(dest_image),
                "merged_label": str(dest_label),
                "sha256": image_hash,
                "box_count": len(read_yolo_rows(pair.label_path)),
            }
        )
    return records, hashes


def stage_dataset_b(
    extracted_root: Path,
    staging_root: Path,
    dataset_a_hashes: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ensure_clean_dir(staging_root)
    remapped_records: list[dict[str, Any]] = []
    seen_class_ids: Counter[int] = Counter()
    duplicate_records: list[dict[str, Any]] = []
    duplicate_image_paths: set[Path] = set()
    duplicate_label_paths: set[Path] = set()

    for pair in discover_pairs(extracted_root):
        relative_image = pair.image_path.relative_to(extracted_root)
        image_hash = sha256_file(pair.image_path)
        if image_hash in dataset_a_hashes:
            duplicate_image_paths.add(pair.image_path)
            duplicate_label_paths.add(pair.label_path)
            duplicate_records.append(
                {
                    "split": pair.split,
                    "source_image": str(pair.image_path),
                    "source_label": str(pair.label_path),
                    "sha256": image_hash,
                }
            )
            continue

        relative_slug = safe_image_name("dataset_b", relative_image)
        dest_image = staging_root / pair.split / "images" / relative_slug
        dest_label = staging_root / pair.split / "labels" / f"{Path(relative_slug).stem}.txt"
        dest_image.parent.mkdir(parents=True, exist_ok=True)
        dest_label.parent.mkdir(parents=True, exist_ok=True)

        rows = read_yolo_rows(pair.label_path)
        remapped_rows: list[tuple[int, list[float]]] = []
        for cls_id, bbox in rows:
            seen_class_ids[cls_id] += 1
            remapped_rows.append((0, bbox))

        shutil.copy2(pair.image_path, dest_image)
        write_yolo_rows(dest_label, remapped_rows)
        remapped_records.append(
            {
                "source_dataset": "B",
                "split": pair.split,
                "source_image": str(pair.image_path),
                "source_label": str(pair.label_path),
                "staged_image": str(dest_image),
                "staged_label": str(dest_label),
                "sha256": image_hash,
                "box_count": len(remapped_rows),
            }
        )

    for path in sorted(duplicate_label_paths):
        if path.exists():
            path.unlink()
    for path in sorted(duplicate_image_paths):
        if path.exists():
            path.unlink()

    stats = {
        "dataset_b_records_kept": len(remapped_records),
        "dataset_b_duplicates_removed": len(duplicate_records),
        "dataset_b_class_ids_seen": dict(sorted(seen_class_ids.items())),
        "duplicate_records": duplicate_records,
    }
    return remapped_records, stats


def merge_staged_dataset_b(staging_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    merged_records: list[dict[str, Any]] = []
    for pair in discover_pairs(staging_root):
        relative_image = pair.image_path.relative_to(staging_root)
        dest_image = output_dir / pair.split / "images" / relative_image.name
        dest_label = output_dir / pair.split / "labels" / f"{dest_image.stem}.txt"
        dest_image.parent.mkdir(parents=True, exist_ok=True)
        dest_label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pair.image_path, dest_image)
        shutil.copy2(pair.label_path, dest_label)
        merged_records.append(
            {
                "source_dataset": "B",
                "split": pair.split,
                "source_image": str(pair.image_path),
                "source_label": str(pair.label_path),
                "merged_image": str(dest_image),
                "merged_label": str(dest_label),
                "sha256": sha256_file(pair.image_path),
                "box_count": len(read_yolo_rows(pair.label_path)),
            }
        )
    return merged_records


def split_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for split in ("train", "val", "test"):
        split_records = [record for record in records if record["split"] == split]
        summary[split] = {
            "images": len(split_records),
            "boxes": sum(int(record["box_count"]) for record in split_records),
        }
    return summary


def write_dataset_yaml(project_root: Path, output_dir: Path, records: list[dict[str, Any]]) -> Path:
    has_val = any(record["split"] == "val" for record in records)
    has_test = any(record["split"] == "test" for record in records)
    output_relative = output_dir.resolve().relative_to(project_root.resolve())
    dataset_yaml = {
        "path": str(project_root.resolve()),
        "train": str(output_relative / "train" / "images"),
        "val": str((output_relative / ("val" if has_val else "train") / "images")),
        "nc": 1,
        "names": {0: "damage"},
    }
    if has_test:
        dataset_yaml["test"] = str(output_relative / "test" / "images")
    dataset_yaml_path = output_dir / "dataset.yaml"
    dump_yaml(dataset_yaml_path, dataset_yaml)
    return dataset_yaml_path


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    dataset_a_root = resolve_path(project_root, args.dataset_a_root)
    raw_dir = resolve_path(project_root, args.raw_dir)
    output_dir = resolve_path(project_root, args.output_dir)

    zip_path = download_dataset_b(raw_dir, args.dataset_b_slug, bool(args.force_download))
    _, extracted_root = dataset_b_paths(raw_dir, args.dataset_b_slug)
    extract_zip(zip_path, extracted_root)

    staged_b_root = raw_dir / f"{slug_stem(args.dataset_b_slug)}-normalized"
    ensure_clean_dir(output_dir)
    for split in ("train", "val", "test"):
        (output_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (output_dir / split / "labels").mkdir(parents=True, exist_ok=True)

    dataset_a_records, dataset_a_hashes = copy_dataset_a(dataset_a_root, output_dir)
    staged_b_records, staging_stats = stage_dataset_b(extracted_root, staged_b_root, dataset_a_hashes)
    merged_b_records = merge_staged_dataset_b(staged_b_root, output_dir)

    all_records = dataset_a_records + merged_b_records
    dataset_yaml_path = write_dataset_yaml(project_root, output_dir, all_records)

    manifest = {
        "dataset_a_root": str(dataset_a_root),
        "dataset_b_slug": args.dataset_b_slug,
        "dataset_b_zip": str(zip_path),
        "dataset_b_extracted_root": str(extracted_root),
        "dataset_b_staging_root": str(staged_b_root),
        "output_dir": str(output_dir),
        "dataset_yaml": str(dataset_yaml_path),
        "dataset_a_hash_count": len(dataset_a_hashes),
        "dataset_a_records": len(dataset_a_records),
        "dataset_b_staged_records": len(staged_b_records),
        "dataset_b_merged_records": len(merged_b_records),
        "split_summary": split_summary(all_records),
        "staging_stats": staging_stats,
        "records": all_records,
    }
    dump_json(output_dir / "bridge_manifest.json", manifest)

    if args.delete_staging_after_merge and staged_b_root.exists():
        shutil.rmtree(staged_b_root)
        manifest["dataset_b_staging_root_deleted"] = True
        dump_json(output_dir / "bridge_manifest.json", manifest)

    print(
        json.dumps(
            {
                key: value
                for key, value in manifest.items()
                if key not in {"records"} and not (key == "staging_stats" and isinstance(value, dict))
            }
            | {
                "staging_stats": {
                    key: value
                    for key, value in staging_stats.items()
                    if key != "duplicate_records"
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

