from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from guide_utils import dump_json, ensure_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize completed K-fold runs into mean and std metrics.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--manifest", default="artifacts/kfold/training_manifest.json")
    parser.add_argument("--output-dir", default="artifacts/kfold/reporting")
    return parser.parse_args()


def metric_value(row: pd.Series, key: str) -> float:
    value = row.get(key, 0.0)
    return float(value) if pd.notna(value) else 0.0


def summarize_run(run: dict) -> dict | None:
    csv_path = Path(run.get("results_csv", ""))
    if not csv_path.exists():
        return None
    frame = pd.read_csv(csv_path).rename(columns=lambda value: str(value).strip())
    if frame.empty or "epoch" not in frame.columns or "metrics/mAP50(B)" not in frame.columns:
        return None
    best_idx = frame["metrics/mAP50(B)"].astype(float).idxmax()
    best = frame.loc[best_idx]
    final = frame.iloc[-1]
    return {
        "name": run.get("name"),
        "base_name": run.get("base_name", run.get("name")),
        "fold": run.get("fold"),
        "best_epoch": int(best["epoch"]) + 1,
        "best_precision": metric_value(best, "metrics/precision(B)"),
        "best_recall": metric_value(best, "metrics/recall(B)"),
        "best_map50": metric_value(best, "metrics/mAP50(B)"),
        "best_map50_95": metric_value(best, "metrics/mAP50-95(B)"),
        "final_epoch": int(final["epoch"]) + 1,
        "final_map50": metric_value(final, "metrics/mAP50(B)"),
        "final_map50_95": metric_value(final, "metrics/mAP50-95(B)"),
        "results_csv": str(csv_path),
    }


def aggregate(group_rows: list[dict]) -> dict:
    frame = pd.DataFrame(group_rows)
    return {
        "base_name": group_rows[0]["base_name"],
        "fold_count": len(group_rows),
        "mean_best_map50": float(frame["best_map50"].mean()),
        "std_best_map50": float(frame["best_map50"].std(ddof=0)),
        "mean_best_map50_95": float(frame["best_map50_95"].mean()),
        "std_best_map50_95": float(frame["best_map50_95"].std(ddof=0)),
        "mean_best_precision": float(frame["best_precision"].mean()),
        "mean_best_recall": float(frame["best_recall"].mean()),
        "mean_best_epoch": float(frame["best_epoch"].mean()),
    }


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    manifest_path = (workspace / args.manifest).resolve()
    output_dir = (workspace / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = ensure_manifest(manifest_path, workspace)
    fold_rows = [
        summary
        for run in manifest.get("runs", [])
        if run.get("status") == "completed"
        for summary in [summarize_run(run)]
        if summary is not None
    ]
    fold_rows.sort(key=lambda item: (item["base_name"], item.get("fold") or ""))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in fold_rows:
        grouped[row["base_name"]].append(row)

    aggregates = [aggregate(rows) for _, rows in sorted(grouped.items())]
    aggregates.sort(key=lambda item: item["mean_best_map50"], reverse=True)

    dump_json(
        output_dir / "kfold_summary.json",
        {
            "manifest": str(manifest_path),
            "fold_rows": fold_rows,
            "aggregates": aggregates,
        },
    )

    per_fold_csv = output_dir / "kfold_per_fold.csv"
    with per_fold_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "base_name",
                "fold",
                "best_epoch",
                "best_precision",
                "best_recall",
                "best_map50",
                "best_map50_95",
                "final_epoch",
                "final_map50",
                "final_map50_95",
                "results_csv",
                "name",
            ],
        )
        writer.writeheader()
        writer.writerows(fold_rows)

    aggregate_csv = output_dir / "kfold_aggregate.csv"
    with aggregate_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "base_name",
                "fold_count",
                "mean_best_map50",
                "std_best_map50",
                "mean_best_map50_95",
                "std_best_map50_95",
                "mean_best_precision",
                "mean_best_recall",
                "mean_best_epoch",
            ],
        )
        writer.writeheader()
        writer.writerows(aggregates)

    print(json.dumps({"aggregates": aggregates, "fold_rows": fold_rows}, indent=2))


if __name__ == "__main__":
    main()
