from __future__ import annotations

import argparse
import hashlib
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cluster_priority(label: str) -> tuple[int, str]:
    order = {"both": 0, "crack": 1, "pothole": 2}
    return order.get(label, 99), label


def cluster_stratify_label(records: list[dict]) -> str:
    counts = Counter(record["stratify_label"] for record in records)
    if not counts:
        raise RuntimeError("Encountered an empty hash cluster during split preparation.")
    return min(counts.items(), key=lambda item: (-item[1], *cluster_priority(item[0])))[0]


def build_hash_clusters(records: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        image_path = Path(record["filtered_image"])
        digest = sha256_file(image_path)
        grouped.setdefault(digest, []).append(record)

    clusters: list[dict] = []
    for digest, members in grouped.items():
        labels = sorted({record["stratify_label"] for record in members})
        clusters.append(
            {
                "sha256": digest,
                "records": members,
                "size": len(members),
                "stratify_label": cluster_stratify_label(members),
                "mixed_labels": labels if len(labels) > 1 else [],
            }
        )
    return sorted(clusters, key=lambda item: (item["size"], item["sha256"]))


def stratified_cluster_split(clusters: list[dict], seed: int) -> tuple[list[dict], list[dict], list[dict]]:
    labels = [cluster["stratify_label"] for cluster in clusters]
    train_clusters, temp_clusters = train_test_split(
        clusters,
        test_size=0.30,
        random_state=seed,
        stratify=labels,
    )
    temp_labels = [cluster["stratify_label"] for cluster in temp_clusters]
    val_clusters, test_clusters = train_test_split(
        temp_clusters,
        test_size=0.50,
        random_state=seed,
        stratify=temp_labels,
    )
    return train_clusters, val_clusters, test_clusters


def flatten_clusters(clusters: list[dict]) -> list[dict]:
    records: list[dict] = []
    for cluster in clusters:
        records.extend(cluster["records"])
    return records


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

    clusters = build_hash_clusters(records)
    strat_counts = Counter(cluster["stratify_label"] for cluster in clusters)
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

    train_clusters, val_clusters, test_clusters = stratified_cluster_split(clusters, int(config["dataset"]["split_seed"]))
    train_records = flatten_clusters(train_clusters)
    val_records = flatten_clusters(val_clusters)
    test_records = flatten_clusters(test_clusters)
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
        "hash_clusters": {
            "total_clusters": len(clusters),
            "duplicate_clusters": sum(1 for cluster in clusters if cluster["size"] > 1),
            "duplicate_images_total": sum(cluster["size"] for cluster in clusters if cluster["size"] > 1),
            "mixed_label_duplicate_clusters": [
                {
                    "sha256": cluster["sha256"],
                    "size": cluster["size"],
                    "labels": cluster["mixed_labels"],
                }
                for cluster in clusters
                if cluster["mixed_labels"]
            ],
        },
        "records": split_records,
        "test_set_locked": True,
    }
    dump_json(project_root / "artifacts" / "prep" / "split_summary.json", summary)
    print(summary["splits"])


if __name__ == "__main__":
    main()
