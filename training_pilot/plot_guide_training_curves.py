from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from guide_utils import ensure_manifest, dump_json


COLORS = {
    "yolo12s_custom": "#1f77b4",
    "yolov8l_custom": "#ff7f0e",
    "yolov8m_custom": "#2ca02c",
    "obc_yolov8_custom": "#9467bd",
    "yolov8s_diverse": "#d62728",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot multi-run training curves from guide-aligned runs.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def load_results(manifest: dict) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for run in manifest.get("runs", []):
        if run.get("status") != "completed":
            continue
        csv_path = Path(run.get("results_csv", ""))
        if not csv_path.exists():
            continue
        frame = pd.read_csv(csv_path)
        frame = frame.rename(columns=lambda value: str(value).strip())
        frame["epoch_idx"] = frame["epoch"].astype(int) + 1
        frames[run["name"]] = frame
    return frames


def plot(frames: dict[str, pd.DataFrame], output_path: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    axes = axes.flatten()

    specs = [
        ("train/box_loss", "val/box_loss", "Box Loss", axes[0]),
        ("metrics/precision(B)", None, "Precision", axes[1]),
        ("metrics/recall(B)", None, "Recall", axes[2]),
        ("metrics/mAP50(B)", None, "mAP50", axes[3]),
        ("metrics/mAP50-95(B)", None, "mAP50-95", axes[4]),
    ]

    for primary, secondary, title, axis in specs:
        for name, frame in frames.items():
            if primary not in frame.columns:
                continue
            color = COLORS.get(name)
            axis.plot(frame["epoch_idx"], frame[primary], label=name if secondary is None else f"{name} train", color=color)
            if secondary and secondary in frame.columns:
                axis.plot(frame["epoch_idx"], frame[secondary], linestyle="--", color=color, alpha=0.8, label=f"{name} val")
        axis.set_title(title)
        axis.set_xlabel("Epoch")
        axis.grid(True, alpha=0.2)

    axes[5].axis("off")
    handles, labels = axes[0].get_legend_handles_labels()
    axes[5].legend(handles, labels, loc="center", frameon=False, fontsize=10)

    fig.suptitle("Guide-Aligned YOLO Training Curves", fontsize=16)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def final_epoch_rows(frames: dict[str, pd.DataFrame]) -> list[dict]:
    rows: list[dict] = []
    for name, frame in frames.items():
        final = frame.iloc[-1]
        rows.append(
            {
                "name": name,
                "epoch": int(final["epoch"]),
                "precision": float(final.get("metrics/precision(B)", 0.0)),
                "recall": float(final.get("metrics/recall(B)", 0.0)),
                "map50": float(final.get("metrics/mAP50(B)", 0.0)),
                "map50_95": float(final.get("metrics/mAP50-95(B)", 0.0)),
                "train_box_loss": float(final.get("train/box_loss", 0.0)),
                "val_box_loss": float(final.get("val/box_loss", 0.0)),
            }
        )
    rows.sort(key=lambda item: item["map50"], reverse=True)
    return rows


def best_epoch_rows(frames: dict[str, pd.DataFrame]) -> list[dict]:
    rows: list[dict] = []
    for name, frame in frames.items():
        if "metrics/mAP50(B)" not in frame.columns:
            continue
        best_idx = frame["metrics/mAP50(B)"].astype(float).idxmax()
        best = frame.loc[best_idx]
        rows.append(
            {
                "name": name,
                "best_epoch": int(best["epoch"]) + 1,
                "precision": float(best.get("metrics/precision(B)", 0.0)),
                "recall": float(best.get("metrics/recall(B)", 0.0)),
                "map50": float(best.get("metrics/mAP50(B)", 0.0)),
                "map50_95": float(best.get("metrics/mAP50-95(B)", 0.0)),
                "train_box_loss": float(best.get("train/box_loss", 0.0)),
                "val_box_loss": float(best.get("val/box_loss", 0.0)),
            }
        )
    rows.sort(key=lambda item: item["map50"], reverse=True)
    return rows


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else workspace / "artifacts" / "reporting"
    manifest = ensure_manifest(workspace / "artifacts" / "training_manifest.json", workspace)
    frames = load_results(manifest)
    if not frames:
        raise SystemExit("No completed runs with results.csv were found.")
    plot(frames, output_dir / "training_curves.png")
    summary = {
        "best_rows": best_epoch_rows(frames),
        "final_rows": final_epoch_rows(frames),
    }
    dump_json(output_dir / "training_curve_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
