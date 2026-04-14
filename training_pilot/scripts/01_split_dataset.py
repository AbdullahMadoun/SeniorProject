from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from sklearn.model_selection import train_test_split

from common import dump_json, dump_yaml, ensure_clean_dir, load_json, load_pipeline_config, resolve_project_root, summarize_split


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the locked 70/15/15 stratified split from filtered data.")
    parser.add_argument("--project-root", default="", help="training_pilot root. Defaults to the local repo copy.")
    return parser.parse_args()


def copy_record(record: dict, project_root: Path, split: str) -> dict:
    image_path = Path(record["filtered_image"])
    label_path = Path(record["filtered_label"])
    dest_image = project_root / "data" / split / "images" / image_path.name
    dest_label = project_root / "data" / split / "labels" / label_path.name
    dest_image.parent.mkdir(parents=True, exist_ok=True)
    dest_label.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image_path, dest_image)
    shutil.copy2(label_path, dest_label)
    updated = dict(record)
    updated["split"] = split
    updated["dataset_image"] = str(dest_image.resolve())
    updated["dataset_label"] = str(dest_label.resolve())
    return updated


def stratified_split(records: list[dict], seed: int) -> tuple[list[dict], list[dict], list[dict]]:
    labels = [record["stratify_label"] for record in records]
    train_records, temp_records = train_test_split(
        records,
        test_size=0.30,
        random_state=seed,
        stratify=labels,
    )
    temp_labels = [record["stratify_label"] for record in temp_records]
    val_records, test_records = train_test_split(
        temp_records,
        test_size=0.50,
        random_state=seed,
        stratify=temp_labels,
    )
    return train_records, val_records, test_records


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    config = load_pipeline_config(project_root)
    manifest_path = project_root / "artifacts" / "prep" / "filter_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing filter manifest: {manifest_path}. Run 00_filter_and_remap.py first.")

    records = load_json(manifest_path)["records"]
    if not records:
        raise RuntimeError("The filter manifest is empty. No images remain after filtering.")

    strat_counts = Counter(record["stratify_label"] for record in records)
    too_small = {label: count for label, count in strat_counts.items() if count < 3}
    if too_small:
        raise RuntimeError(
            "Stratified split cannot proceed because at least one stratum has fewer than 3 images: "
            f"{too_small}"
        )

    data_root = project_root / "data"
    for split in ("train", "val", "test"):
        ensure_clean_dir(data_root / split)
        (data_root / split / "images").mkdir(parents=True, exist_ok=True)
        (data_root / split / "labels").mkdir(parents=True, exist_ok=True)

    train_records, val_records, test_records = stratified_split(records, int(config["dataset"]["split_seed"]))
    split_records = {
        "train": [copy_record(record, project_root, "train") for record in train_records],
        "val": [copy_record(record, project_root, "val") for record in val_records],
        "test": [copy_record(record, project_root, "test") for record in test_records],
    }

    dataset_yaml = {
        "path": str(project_root.resolve()),
        "train": "data/train/images",
        "val": "data/val/images",
        "test": "data/test/images",
        "nc": 1,
        "names": {0: "damage"},
    }
    dump_yaml(project_root / "configs" / "dataset.yaml", dataset_yaml)

    summary = {
        "seed": int(config["dataset"]["split_seed"]),
        "splits": {name: summarize_split(items) for name, items in split_records.items()},
        "records": split_records,
        "test_set_locked": True,
    }
    dump_json(project_root / "artifacts" / "prep" / "split_summary.json", summary)
    print(summary["splits"])


if __name__ == "__main__":
    main()
