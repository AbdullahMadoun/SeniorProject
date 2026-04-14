from __future__ import annotations

import argparse
import re
import shutil
from collections import Counter
from pathlib import Path

from common import (
    IMAGE_SUFFIXES,
    dump_json,
    ensure_clean_dir,
    discover_label_image_pairs,
    load_pipeline_config,
    normalize_class_name,
    read_yolo_rows,
    resolve_class_id_map,
    resolve_project_root,
    resolve_source_data_yaml,
    unique_filtered_name,
    write_yolo_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter manholes, drop empty images, and remap pothole/crack to class 0.")
    parser.add_argument("--project-root", default="", help="training_pilot root. Defaults to the local repo copy.")
    return parser.parse_args()


def stratify_label(class_names: set[str]) -> str:
    has_pothole = "pothole" in class_names
    has_crack = "crack" in class_names
    if has_pothole and has_crack:
        return "both"
    if has_pothole:
        return "pothole"
    if has_crack:
        return "crack"
    raise RuntimeError(f"Unexpected class combination after filtering: {sorted(class_names)}")


def resolve_kaggle_class_id_map(raw_dir: Path) -> dict[str, int]:
    candidates = sorted(raw_dir.rglob("README.md"))
    if not candidates:
        raise FileNotFoundError(
            "The Kaggle raw package does not include data.yaml here, and no README.md was found to recover the class map."
        )
    row_re = re.compile(r"^\|\s*(\d+)\s*\|\s*([A-Za-z0-9 _-]+?)\s*\|")
    mapping: dict[str, int] = {}
    for candidate in candidates:
        for line in candidate.read_text(encoding="utf-8").splitlines():
            match = row_re.match(line.strip())
            if not match:
                continue
            class_id = int(match.group(1))
            class_name = normalize_class_name(match.group(2))
            mapping[class_name] = class_id
        required = {"pothole", "crack", "manhole"}
        if required.issubset(mapping):
            return mapping
        mapping.clear()
    raise RuntimeError(
        "Failed to recover the Kaggle class table from README.md. "
        "The raw package layout is present, but the class mapping was not parsed successfully."
    )


def find_image_for_label(image_root: Path, label_path: Path) -> Path:
    for suffix in IMAGE_SUFFIXES:
        candidate = image_root / f"{label_path.stem}{suffix}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find an image in {image_root} for label file {label_path}")


def resolve_source_pairs_and_classes(raw_dir: Path) -> tuple[list[tuple[Path, Path]], dict[str, int]]:
    yolo_label_roots = [path for path in sorted(raw_dir.rglob("labels-YOLO")) if path.is_dir()]
    if yolo_label_roots:
        if len(yolo_label_roots) != 1:
            raise RuntimeError(f"Expected exactly one labels-YOLO directory under {raw_dir}, found {yolo_label_roots}")
        label_root = yolo_label_roots[0]
        image_root = label_root.parent / "images"
        if not image_root.exists():
            raise FileNotFoundError(f"Expected YOLO image directory next to {label_root}, but {image_root} does not exist")
        pairs = [(find_image_for_label(image_root, label_path), label_path) for label_path in sorted(label_root.glob("*.txt"))]
        if not pairs:
            raise RuntimeError(f"No YOLO label/image pairs were found under {label_root}")
        return pairs, resolve_kaggle_class_id_map(raw_dir)

    data_yaml_path = resolve_source_data_yaml(raw_dir)
    return discover_label_image_pairs(raw_dir), resolve_class_id_map(data_yaml_path)


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    config = load_pipeline_config(project_root)

    raw_dir = project_root / config["dataset"]["raw_dir"]
    filtered_dir = project_root / config["dataset"]["filtered_dir"]
    filtered_images = filtered_dir / "images"
    filtered_labels = filtered_dir / "labels"
    artifact_dir = project_root / "artifacts" / "prep"
    ensure_clean_dir(filtered_dir)
    filtered_images.mkdir(parents=True, exist_ok=True)
    filtered_labels.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    source_pairs, class_id_map = resolve_source_pairs_and_classes(raw_dir)
    required = {"pothole", "crack", "manhole"}
    missing = sorted(required - set(class_id_map))
    if missing:
        raise RuntimeError(f"Source dataset is missing required classes: {missing}")

    keep_ids = {class_id_map["pothole"], class_id_map["crack"]}
    drop_id = class_id_map["manhole"]
    inverse_class_map = {value: key for key, value in class_id_map.items()}

    before_counts: Counter[str] = Counter()
    after_counts: Counter[str] = Counter()
    manifest: list[dict] = []
    dropped_empty = 0
    dropped_manhole_only = 0

    for image_path, label_path in source_pairs:
        rows = read_yolo_rows(label_path)
        original_present: set[str] = set()
        filtered_rows: list[tuple[int, list[float]]] = []
        for cls_id, bbox in rows:
            class_name = inverse_class_map.get(cls_id, f"unknown_{cls_id}")
            before_counts[class_name] += 1
            if cls_id == drop_id:
                original_present.add("manhole")
                continue
            if cls_id in keep_ids:
                original_present.add(class_name)
                after_counts[class_name] += 1
                filtered_rows.append((0, bbox))

        if not filtered_rows:
            dropped_empty += 1
            if original_present == {"manhole"}:
                dropped_manhole_only += 1
            continue

        filtered_name = unique_filtered_name(image_path, raw_dir)
        dest_image = filtered_images / filtered_name
        dest_label = filtered_labels / f"{Path(filtered_name).stem}.txt"
        shutil.copy2(image_path, dest_image)
        write_yolo_rows(dest_label, filtered_rows)
        manifest.append(
            {
                "source_image": str(image_path.resolve()),
                "source_label": str(label_path.resolve()),
                "filtered_image": str(dest_image.resolve()),
                "filtered_label": str(dest_label.resolve()),
                "stratify_label": stratify_label(set(name for name in original_present if name != "manhole")),
                "box_count": len(filtered_rows),
                "kept_source_classes": sorted(name for name in original_present if name != "manhole"),
            }
        )

    stats = {
        "raw_dir": str(raw_dir.resolve()),
        "source_class_map": dict(sorted(class_id_map.items())),
        "image_count_after_filtering": len(manifest),
        "dropped_images_zero_boxes_after_filtering": dropped_empty,
        "dropped_images_manhole_only": dropped_manhole_only,
        "source_class_counts_before_filtering": dict(sorted(before_counts.items())),
        "kept_class_counts_after_filtering": dict(sorted(after_counts.items())),
    }

    dump_json(artifact_dir / "filter_manifest.json", {"records": manifest})
    dump_json(artifact_dir / "filter_stats.json", stats)
    print(stats)


if __name__ == "__main__":
    main()
