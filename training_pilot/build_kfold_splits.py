from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sklearn.model_selection import StratifiedKFold

from guide_utils import dump_json, dump_yaml, load_yaml, sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build stratified K-fold splits from a prepared one-class workspace.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--pool-splits",
        nargs="+",
        default=["train", "val"],
        help="Workspace splits to combine into the K-fold pool. Test is left untouched.",
    )
    return parser.parse_args()


def box_count(label_path: Path) -> int:
    if not label_path.exists():
        return 0
    count = 0
    for line in label_path.read_text(encoding="utf-8").splitlines():
        if len(line.strip().split()) == 5:
            count += 1
    return count


def bucket(count: int) -> str:
    if count <= 0:
        return "neg"
    if count == 1:
        return "pos_1"
    if count <= 3:
        return "pos_2_3"
    if count <= 7:
        return "pos_4_7"
    return "pos_8_plus"


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    dataset_yaml = load_yaml(workspace / "configs" / "dataset.yaml")
    names = dataset_yaml.get("names", {0: "damage"})

    records: list[dict] = []
    for split in args.pool_splits:
        image_dir = workspace / "data" / split / "images"
        label_dir = workspace / "data" / split / "labels"
        for image_path in sorted(image_dir.glob("*")):
            if not image_path.is_file():
                continue
            label_path = label_dir / f"{image_path.stem}.txt"
            count = box_count(label_path)
            records.append(
                {
                    "image_path": image_path,
                    "label_path": label_path,
                    "source_split": split,
                    "box_count": count,
                    "bucket": bucket(count),
                    "sha256": sha256_file(image_path),
                }
            )

    if len(records) < args.n_splits:
        raise RuntimeError(f"Need at least {args.n_splits} images to build {args.n_splits} folds.")

    buckets = [record["bucket"] for record in records]
    splitter = StratifiedKFold(n_splits=args.n_splits, shuffle=True, random_state=args.seed)
    output_root = workspace / "artifacts" / "kfold"
    output_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    for fold_idx, (train_idx, val_idx) in enumerate(splitter.split(records, buckets), start=1):
        fold_name = f"fold_{fold_idx:02d}"
        fold_dir = output_root / fold_name
        fold_dir.mkdir(parents=True, exist_ok=True)

        train_records = [records[i] for i in train_idx]
        val_records = [records[i] for i in val_idx]

        train_txt = fold_dir / "train.txt"
        val_txt = fold_dir / "val.txt"
        train_txt.write_text("\n".join(str(record["image_path"]) for record in train_records) + "\n", encoding="utf-8")
        val_txt.write_text("\n".join(str(record["image_path"]) for record in val_records) + "\n", encoding="utf-8")

        fold_yaml = {
            "path": str(workspace),
            "train": str(train_txt),
            "val": str(val_txt),
            "test": str(workspace / "data" / "test" / "images"),
            "nc": 1,
            "names": names,
        }
        dump_yaml(fold_dir / "dataset.yaml", fold_yaml)

        summary = {
            "fold": fold_name,
            "train_images": len(train_records),
            "val_images": len(val_records),
            "train_boxes": sum(record["box_count"] for record in train_records),
            "val_boxes": sum(record["box_count"] for record in val_records),
            "train_bucket_counts": dict(sorted(Counter(record["bucket"] for record in train_records).items())),
            "val_bucket_counts": dict(sorted(Counter(record["bucket"] for record in val_records).items())),
        }
        dump_json(fold_dir / "summary.json", summary)
        summaries.append(summary)

    manifest = {
        "workspace": str(workspace),
        "pool_splits": args.pool_splits,
        "n_splits": args.n_splits,
        "seed": args.seed,
        "folds": summaries,
    }
    dump_json(output_root / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
