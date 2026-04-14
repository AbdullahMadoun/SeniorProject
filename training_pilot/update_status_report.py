from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a markdown status report for the pilot training workspace.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_latest_metrics(results_csv: Path) -> dict:
    if not results_csv.exists():
        return {}
    with results_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    return rows[-1]


def coverage_index(workspace: Path) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for path in sorted((workspace / "artifacts").glob("*coverage*.json")):
        payload = load_json(path)
        model = payload.get("model")
        if model:
            indexed[str(model)] = payload
    return indexed


def coverage_for_run(run: dict, coverage_by_model: dict[str, dict]) -> dict:
    best = str(Path(run["best"]).resolve())
    return coverage_by_model.get(best, {})


def append_run_section(lines: list[str], title: str, runs: list[dict], coverage_by_model: dict[str, dict]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not runs:
        lines.append("- No runs recorded.")
        lines.append("")
        return

    for run in runs:
        metrics = load_latest_metrics(Path(run["results_csv"]))
        coverage = coverage_for_run(run, coverage_by_model)
        lines.append(f"### {run['name']}")
        lines.append("")
        lines.append(f"- Run dir: `{run['run_dir']}`")
        lines.append(f"- Best checkpoint: `{run['best']}`")
        if metrics:
            epoch = metrics.get("epoch", "n/a")
            map50 = metrics.get("metrics/mAP50(B)", metrics.get("metrics/mAP50(M)", "n/a"))
            precision = metrics.get("metrics/precision(B)", "n/a")
            recall = metrics.get("metrics/recall(B)", "n/a")
            train_loss = metrics.get("train/box_loss", "n/a")
            val_loss = metrics.get("val/box_loss", "n/a")
            lines.append(f"- Latest epoch: {epoch}")
            lines.append(f"- mAP50: {map50}")
            lines.append(f"- Precision: {precision}")
            lines.append(f"- Recall: {recall}")
            lines.append(f"- Train box loss: {train_loss}")
            lines.append(f"- Val box loss: {val_loss}")
        else:
            lines.append("- Metrics not available yet.")

        if coverage:
            lines.append(f"- Damage coverage recall: {coverage.get('damage_coverage_recall', 'n/a')}")
            lines.append(f"- All-damages-found image rate: {coverage.get('all_damages_found_image_rate', 'n/a')}")
            lines.append(f"- Exact image match rate: {coverage.get('exact_image_match_rate', 'n/a')}")
            lines.append(f"- Matched GT: {coverage.get('matched_gt', 'n/a')} / {coverage.get('total_gt', 'n/a')}")
            lines.append(f"- Predictions: {coverage.get('total_predictions', 'n/a')}")
        lines.append("")


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    output_path = Path(args.output).resolve()

    dataset_stats = load_json(workspace / "artifacts" / "dataset_stats.json")
    augmentation_stats = load_json(workspace / "artifacts" / "augmentation_stats.json")
    pilot_manifest = load_json(workspace / "artifacts" / "training_manifest.json")
    benchmark_manifest = load_json(workspace / "artifacts" / "benchmark_manifest.json")
    coverage_by_model = coverage_index(workspace)
    frozen_coverage = load_json(workspace / "artifacts" / "frozen_grounding_clip_coverage.json")
    ensemble_coverages = [
        load_json(path)
        for path in sorted((workspace / "artifacts").glob("*ensemble*coverage*.json"))
        if path.name != "frozen_grounding_clip_coverage.json"
    ]

    lines: list[str] = []
    lines.append("# Training Pilot Status")
    lines.append("")

    if dataset_stats:
        lines.append("## Dataset")
        lines.append("")
        lines.append(f"- Total images: {dataset_stats.get('total_images', 'n/a')}")
        splits = dataset_stats.get("splits", {})
        if splits:
            lines.append(f"- Splits: train={splits.get('train', 0)}, val={splits.get('val', 0)}, test={splits.get('test', 0)}")
        lines.append(f"- Converted boxes: {dataset_stats.get('converted_box_count', 'n/a')}")
        lines.append(f"- Negative images: {dataset_stats.get('negative_images', 'n/a')}")
        lines.append(f"- Source classes: {dataset_stats.get('source_class_names', [])}")
        lines.append("")

    if augmentation_stats:
        lines.append("## Offline Augmentation")
        lines.append("")
        lines.append(f"- Source train images augmented: {augmentation_stats.get('source_images_augmented', 0)}")
        lines.append(f"- Horizontal flips created: {augmentation_stats.get('flipped', 0)}")
        lines.append(f"- Brightness/blur variants created: {augmentation_stats.get('jittered', 0)}")
        lines.append("")

    append_run_section(lines, "Pilot Runs", pilot_manifest.get("runs", []), coverage_by_model)
    append_run_section(lines, "Benchmark Runs", benchmark_manifest.get("runs", []), coverage_by_model)

    if frozen_coverage:
        lines.append("## Frozen Member")
        lines.append("")
        lines.append(f"- Model: {frozen_coverage.get('model', 'n/a')}")
        lines.append(f"- Damage coverage recall: {frozen_coverage.get('damage_coverage_recall', 'n/a')}")
        lines.append(f"- All-damages-found image rate: {frozen_coverage.get('all_damages_found_image_rate', 'n/a')}")
        lines.append(f"- Exact image match rate: {frozen_coverage.get('exact_image_match_rate', 'n/a')}")
        lines.append(f"- Matched GT: {frozen_coverage.get('matched_gt', 'n/a')} / {frozen_coverage.get('total_gt', 'n/a')}")
        lines.append(f"- Predictions: {frozen_coverage.get('total_predictions', 'n/a')}")
        lines.append("")

    if ensemble_coverages:
        lines.append("## Ensemble Metrics")
        lines.append("")
        for payload in ensemble_coverages:
            label = " + ".join(Path(member).stem for member in payload.get("ensemble_members", []))
            lines.append(f"### {label or 'ensemble'}")
            lines.append("")
            lines.append(f"- Split: {payload.get('split', 'n/a')}")
            lines.append(f"- TTA enabled: {payload.get('tta_enabled', False)}")
            lines.append(f"- Frozen included: {payload.get('include_frozen', False)}")
            lines.append(f"- Damage coverage recall: {payload.get('damage_coverage_recall', 'n/a')}")
            lines.append(f"- All-damages-found image rate: {payload.get('all_damages_found_image_rate', 'n/a')}")
            lines.append(f"- Exact image match rate: {payload.get('exact_image_match_rate', 'n/a')}")
            lines.append(f"- Matched GT: {payload.get('matched_gt', 'n/a')} / {payload.get('total_gt', 'n/a')}")
            lines.append(f"- Predictions: {payload.get('total_predictions', 'n/a')}")
            lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
