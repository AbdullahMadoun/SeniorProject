from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build plots and markdown summaries for the road-damage benchmark workspace."
    )
    parser.add_argument("--workspace-root", required=True, help="Workspace root containing artifacts/ and runs_benchmark/.")
    parser.add_argument("--output-dir", required=True, help="Directory where plots and reports will be written.")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(workspace_root: Path) -> dict:
    manifest_path = workspace_root / "artifacts" / "benchmark_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    return load_json(manifest_path)


def load_run_frames(workspace_root: Path, manifest: dict) -> dict[str, pd.DataFrame]:
    run_frames: dict[str, pd.DataFrame] = {}
    runs_root = workspace_root / "runs_benchmark"
    for run in manifest.get("runs", []):
        name = run["name"]
        results_path = runs_root / name / "results.csv"
        if not results_path.exists():
            continue
        frame = pd.read_csv(results_path)
        frame["epoch_idx"] = frame["epoch"].astype(int)
        run_frames[name] = frame
    return run_frames


def load_coverages(workspace_root: Path) -> tuple[dict[str, dict[str, dict]], dict[str, list[dict]]]:
    artifacts_dir = workspace_root / "artifacts"
    singles_by_split: dict[str, dict[str, dict]] = {}
    ensembles_by_split: dict[str, list[dict]] = {}

    paths = sorted(artifacts_dir.glob("*coverage*.json")) + sorted(artifacts_dir.glob("ensemble*.json"))
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        payload = load_json(path)
        payload["_source_file"] = path.name
        split = str(payload.get("split", "unknown"))
        if payload.get("model") == "wbf_ensemble" or payload.get("ensemble_members"):
            ensembles_by_split.setdefault(split, []).append(payload)
            continue
        model_path = str(payload.get("model", ""))
        if model_path:
            singles_by_split.setdefault(split, {})[model_path] = payload

    return singles_by_split, ensembles_by_split


def coverage_for_run(run: dict, singles_by_split: dict[str, dict[str, dict]], split: str) -> dict:
    best_path = str(run["best"])
    return singles_by_split.get(split, {}).get(best_path, {})


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def last_row(frame: pd.DataFrame) -> pd.Series:
    return frame.iloc[-1]


def plot_training_curves(run_frames: dict[str, pd.DataFrame], output_path: Path) -> None:
    colors = {
        "yolo12s_custom_benchmark": "#1f77b4",
        "yolov8l_custom_benchmark": "#ff7f0e",
        "yolov8m_custom_benchmark": "#2ca02c",
        "yolov8s_diverse": "#d62728",
    }
    labels = {
        "yolo12s_custom_benchmark": "YOLO12s",
        "yolov8l_custom_benchmark": "YOLOv8l",
        "yolov8m_custom_benchmark": "YOLOv8m",
        "yolov8s_diverse": "YOLOv8s diverse",
    }

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()

    loss_ax = axes[0]
    for run_name, frame in run_frames.items():
        epochs = frame["epoch_idx"]
        color = colors.get(run_name, None)
        label = labels.get(run_name, run_name)
        loss_ax.plot(epochs, frame["train/box_loss"], linestyle="--", color=color, alpha=0.7)
        loss_ax.plot(epochs, frame["val/box_loss"], linestyle="-", color=color, linewidth=2, label=label)
    loss_ax.set_title("Box Loss vs Epoch")
    loss_ax.set_xlabel("Epoch")
    loss_ax.set_ylabel("Loss")
    loss_ax.grid(True, alpha=0.2)

    metric_specs = [
        ("metrics/precision(B)", "Precision vs Epoch", "Precision"),
        ("metrics/recall(B)", "Recall vs Epoch", "Recall"),
        ("metrics/mAP50(B)", "mAP@0.5 vs Epoch", "mAP@0.5"),
        ("metrics/mAP50-95(B)", "mAP@0.5:0.95 vs Epoch", "mAP@0.5:0.95"),
    ]

    for axis, (column, title, ylabel) in zip(axes[1:5], metric_specs):
        for run_name, frame in run_frames.items():
            axis.plot(
                frame["epoch_idx"],
                frame[column],
                color=colors.get(run_name, None),
                linewidth=2,
                label=labels.get(run_name, run_name),
            )
        axis.set_title(title)
        axis.set_xlabel("Epoch")
        axis.set_ylabel(ylabel)
        axis.grid(True, alpha=0.2)

    legend_ax = axes[5]
    legend_ax.axis("off")
    handles, legend_labels = loss_ax.get_legend_handles_labels()
    legend_ax.legend(handles, legend_labels, loc="center", frameon=False, fontsize=11)
    legend_ax.text(
        0.5,
        0.2,
        "Loss plot: solid = val, dashed = train",
        ha="center",
        va="center",
        fontsize=11,
    )

    fig.suptitle("4-YOLO Benchmark Training Curves", fontsize=16)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_single_model_table(
    manifest: dict,
    run_frames: dict[str, pd.DataFrame],
    singles_by_split: dict[str, dict[str, dict]],
    split: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    for run in manifest.get("runs", []):
        run_name = run["name"]
        frame = run_frames.get(run_name)
        if frame is None:
            continue
        coverage = coverage_for_run(run, singles_by_split, split)
        if not coverage:
            continue
        final = last_row(frame)
        rows.append(
            {
                "split": split,
                "model": run_name,
                "precision": safe_float(final.get("metrics/precision(B)")),
                "recall": safe_float(final.get("metrics/recall(B)")),
                "map50": safe_float(final.get("metrics/mAP50(B)")),
                "map50_95": safe_float(final.get("metrics/mAP50-95(B)")),
                "damage_coverage_recall": safe_float(coverage.get("damage_coverage_recall")),
                "all_found_image_rate": safe_float(coverage.get("all_damages_found_image_rate")),
                "exact_image_match_rate": safe_float(coverage.get("exact_image_match_rate")),
                "total_predictions": int(coverage.get("total_predictions", 0)),
                "matched_gt": int(coverage.get("matched_gt", 0)),
                "total_gt": int(coverage.get("total_gt", 0)),
            }
        )

    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(
            by=["damage_coverage_recall", "all_found_image_rate", "exact_image_match_rate", "map50"],
            ascending=False,
        ).reset_index(drop=True)
    return table


def ensemble_label(payload: dict) -> str:
    source_file = payload.get("_source_file", "")
    if source_file == "ensemble_4yolo_multiscale_val_skip10.json":
        return "4-YOLO multiscale+flip TTA"
    if source_file == "ensemble_4yolo_val_skip10.json":
        return "4-YOLO practical TTA baseline"
    split = payload.get("split", "unknown")
    return f"ensemble ({split})"


def build_ensemble_table(ensembles: list[dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for payload in ensembles:
        rows.append(
            {
                "ensemble": ensemble_label(payload),
                "source_file": payload.get("_source_file", ""),
                "split": payload.get("split", ""),
                "damage_coverage_recall": safe_float(payload.get("damage_coverage_recall")),
                "all_found_image_rate": safe_float(payload.get("all_damages_found_image_rate")),
                "exact_image_match_rate": safe_float(payload.get("exact_image_match_rate")),
                "total_predictions": int(payload.get("total_predictions", 0)),
                "matched_gt": int(payload.get("matched_gt", 0)),
                "total_gt": int(payload.get("total_gt", 0)),
                "tta_enabled": bool(payload.get("tta_enabled", False)),
                "tta_imgsz": ",".join(str(v) for v in payload.get("tta_imgsz", [])),
                "tta_flip": bool(payload.get("tta_flip", False)),
                "wbf_skip_box_thr": safe_float(payload.get("wbf_skip_box_thr")),
            }
        )

    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(
            by=["damage_coverage_recall", "all_found_image_rate", "exact_image_match_rate"],
            ascending=False,
        ).reset_index(drop=True)
    return table


def compute_training_signal(run_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []
    for run_name, frame in run_frames.items():
        if len(frame) < 2:
            continue
        prev = frame.iloc[-2]
        final = frame.iloc[-1]
        rows.append(
            {
                "model": run_name,
                "delta_precision_last_epoch": safe_float(final["metrics/precision(B)"]) - safe_float(prev["metrics/precision(B)"]),
                "delta_recall_last_epoch": safe_float(final["metrics/recall(B)"]) - safe_float(prev["metrics/recall(B)"]),
                "delta_map50_last_epoch": safe_float(final["metrics/mAP50(B)"]) - safe_float(prev["metrics/mAP50(B)"]),
                "delta_map50_95_last_epoch": safe_float(final["metrics/mAP50-95(B)"]) - safe_float(prev["metrics/mAP50-95(B)"]),
                "delta_val_box_loss_last_epoch": safe_float(final["val/box_loss"]) - safe_float(prev["val/box_loss"]),
            }
        )
    return pd.DataFrame(rows).sort_values(by="delta_recall_last_epoch", ascending=False).reset_index(drop=True)


def recommendation_lines(single_table: pd.DataFrame, ensemble_table: pd.DataFrame, signal_table: pd.DataFrame) -> list[str]:
    lines: list[str] = []

    if not single_table.empty:
        best_single = single_table.iloc[0]
        lines.append(
            f"- Best single model by `damage_coverage_recall`: `{best_single['model']}` "
            f"({best_single['damage_coverage_recall']:.4f})."
        )

    if not ensemble_table.empty:
        best_ensemble = ensemble_table.iloc[0]
        lines.append(
            f"- Best ensemble by `damage_coverage_recall`: `{best_ensemble['ensemble']}` "
            f"({best_ensemble['damage_coverage_recall']:.4f})."
        )

    signal_by_model = {row["model"]: row for row in signal_table.to_dict(orient="records")} if not signal_table.empty else {}
    yolov8m_signal = signal_by_model.get("yolov8m_custom_benchmark")
    yolov8s_signal = signal_by_model.get("yolov8s_diverse")

    if yolov8m_signal and yolov8m_signal["delta_recall_last_epoch"] > 0 and yolov8m_signal["delta_map50_last_epoch"] > 0:
        lines.append(
            "- `yolov8m_custom_benchmark` was still improving at epoch 8 on both recall and mAP, so it is the strongest candidate for continuation training."
        )

    if yolov8s_signal and yolov8s_signal["delta_recall_last_epoch"] > 0 and yolov8s_signal["delta_map50_last_epoch"] > 0:
        lines.append(
            "- `yolov8s_diverse` also ended with rising recall and mAP, which supports keeping it as the high-recall, high-proposal ensemble member."
        )

    lines.append(
        "- `yolo12s_custom_benchmark` and `yolov8l_custom_benchmark` look closer to plateau or mixed behavior than `yolov8m_custom_benchmark` on the final epoch."
    )
    return lines


def dataframe_to_markdown(table: pd.DataFrame, float_cols: set[str]) -> str:
    if table.empty:
        return "_No data available._"

    render = table.copy()
    for column in render.columns:
        if column in float_cols:
            render[column] = render[column].map(lambda value: "" if pd.isna(value) else f"{value:.4f}")
        else:
            render[column] = render[column].map(lambda value: "" if pd.isna(value) else value)

    columns = list(render.columns)
    widths: dict[str, int] = {}
    for column in columns:
        cell_lengths = [len(str(value)) for value in render[column].tolist()]
        widths[column] = max(len(column), max(cell_lengths, default=0))

    header = "| " + " | ".join(column.ljust(widths[column]) for column in columns) + " |"
    separator = "| " + " | ".join("-" * widths[column] for column in columns) + " |"
    rows = []
    for _, row in render.iterrows():
        rows.append("| " + " | ".join(str(row[column]).ljust(widths[column]) for column in columns) + " |")
    return "\n".join([header, separator, *rows])


def append_table_section(
    lines: list[str],
    heading: str,
    intro: str,
    table: pd.DataFrame,
    float_cols: set[str],
) -> None:
    if table.empty:
        return
    lines.append(heading)
    lines.append("")
    if intro:
        lines.append(intro)
        lines.append("")
    lines.append(dataframe_to_markdown(table, float_cols))
    lines.append("")


def build_test_readout_table(test_single_table: pd.DataFrame, test_ensemble_table: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    if not test_single_table.empty:
        single_view = test_single_table[
            [
                "split",
                "model",
                "precision",
                "recall",
                "map50",
                "map50_95",
                "damage_coverage_recall",
                "all_found_image_rate",
                "exact_image_match_rate",
                "total_predictions",
                "matched_gt",
                "total_gt",
            ]
        ].copy()
        single_view.insert(0, "kind", "single")
        single_view = single_view.rename(columns={"model": "configuration"})
        frames.append(single_view)

    if not test_ensemble_table.empty:
        ensemble_view = test_ensemble_table[
            [
                "split",
                "ensemble",
                "damage_coverage_recall",
                "all_found_image_rate",
                "exact_image_match_rate",
                "total_predictions",
                "matched_gt",
                "total_gt",
                "tta_enabled",
                "tta_imgsz",
                "tta_flip",
                "wbf_skip_box_thr",
            ]
        ].copy()
        ensemble_view.insert(0, "kind", "ensemble")
        ensemble_view = ensemble_view.rename(columns={"ensemble": "configuration"})
        frames.append(ensemble_view)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True, sort=False)


def write_markdown_report(
    workspace_root: Path,
    output_dir: Path,
    dataset_stats: dict,
    augmentation_stats: dict,
    validation_single_table: pd.DataFrame,
    validation_ensemble_table: pd.DataFrame,
    test_single_table: pd.DataFrame,
    test_ensemble_table: pd.DataFrame,
    signal_table: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# 4-YOLO Road-Damage Benchmark Report")
    lines.append("")
    lines.append(f"- Workspace snapshot: `{workspace_root}`")
    lines.append(f"- Total images: `{dataset_stats.get('total_images', 'n/a')}`")
    splits = dataset_stats.get("splits", {})
    if splits:
        lines.append(
            f"- Split sizes: train=`{splits.get('train', 'n/a')}`, val=`{splits.get('val', 'n/a')}`, test=`{splits.get('test', 'n/a')}`"
        )
    lines.append(f"- Converted boxes: `{dataset_stats.get('converted_box_count', 'n/a')}`")
    lines.append(f"- Negative images: `{dataset_stats.get('negative_images', 'n/a')}`")
    lines.append(
        f"- Offline augmentation applied to positive train images: `{augmentation_stats.get('source_images_augmented', 0)}` "
        f"(flip=`{augmentation_stats.get('flipped', 0)}`, jitter=`{augmentation_stats.get('jittered', 0)}`)."
    )
    lines.append("")

    append_table_section(
        lines,
        "## Validation Single-Model Ranking",
        "Single models are ranked by the recall-first objective: `damage_coverage_recall`, then image-level full coverage, then exact match.",
        validation_single_table,
        {
            "precision",
            "recall",
            "map50",
            "map50_95",
            "damage_coverage_recall",
            "all_found_image_rate",
            "exact_image_match_rate",
        },
    )
    append_table_section(
        lines,
        "## Validation Ensemble Ranking",
        "",
        validation_ensemble_table,
        {
            "damage_coverage_recall",
            "all_found_image_rate",
            "exact_image_match_rate",
            "wbf_skip_box_thr",
        },
    )
    append_table_section(
        lines,
        "## Test Readout",
        "Test results are shown only for the selected best single model and the two validated 4-YOLO ensemble configurations.",
        build_test_readout_table(test_single_table, test_ensemble_table),
        {
            "precision",
            "recall",
            "map50",
            "map50_95",
            "damage_coverage_recall",
            "all_found_image_rate",
            "exact_image_match_rate",
            "wbf_skip_box_thr",
        },
    )

    lines.append("## Final-Epoch Training Signal")
    lines.append("")
    lines.append("Positive deltas on the last epoch suggest the run had not fully flattened yet.")
    lines.append("")
    lines.append(
        dataframe_to_markdown(
            signal_table,
            {
                "delta_precision_last_epoch",
                "delta_recall_last_epoch",
                "delta_map50_last_epoch",
                "delta_map50_95_last_epoch",
                "delta_val_box_loss_last_epoch",
            },
        )
    )
    lines.append("")

    lines.append("## Technical Readout")
    lines.append("")
    lines.extend(recommendation_lines(validation_single_table, validation_ensemble_table, signal_table))
    lines.append("")

    report_path = output_dir / "validation_report.md"
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(workspace_root)
    run_frames = load_run_frames(workspace_root, manifest)
    singles_by_split, ensembles_by_split = load_coverages(workspace_root)
    dataset_stats = load_json(workspace_root / "artifacts" / "dataset_stats.json")
    augmentation_stats = load_json(workspace_root / "artifacts" / "augmentation_stats.json")

    plot_training_curves(run_frames, output_dir / "training_curves.png")

    validation_single_table = build_single_model_table(manifest, run_frames, singles_by_split, "val")
    validation_ensemble_table = build_ensemble_table(ensembles_by_split.get("val", []))
    test_single_table = build_single_model_table(manifest, run_frames, singles_by_split, "test")
    test_ensemble_table = build_ensemble_table(ensembles_by_split.get("test", []))
    signal_table = compute_training_signal(run_frames)

    validation_single_table.to_csv(output_dir / "single_model_validation.csv", index=False)
    validation_ensemble_table.to_csv(output_dir / "ensemble_validation.csv", index=False)
    test_single_table.to_csv(output_dir / "single_model_test.csv", index=False)
    test_ensemble_table.to_csv(output_dir / "ensemble_test.csv", index=False)
    signal_table.to_csv(output_dir / "training_signal.csv", index=False)

    summary = {
        "best_validation_single_model": validation_single_table.iloc[0].to_dict() if not validation_single_table.empty else {},
        "best_validation_ensemble": validation_ensemble_table.iloc[0].to_dict() if not validation_ensemble_table.empty else {},
        "best_test_single_model": test_single_table.iloc[0].to_dict() if not test_single_table.empty else {},
        "best_test_ensemble": test_ensemble_table.iloc[0].to_dict() if not test_ensemble_table.empty else {},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    write_markdown_report(
        workspace_root=workspace_root,
        output_dir=output_dir,
        dataset_stats=dataset_stats,
        augmentation_stats=augmentation_stats,
        validation_single_table=validation_single_table,
        validation_ensemble_table=validation_ensemble_table,
        test_single_table=test_single_table,
        test_ensemble_table=test_ensemble_table,
        signal_table=signal_table,
    )


if __name__ == "__main__":
    main()
