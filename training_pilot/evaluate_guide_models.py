from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from guide_utils import SCRIPT_ROOT, dump_json, dump_yaml, ensure_manifest, load_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate trained guide models and emit val/test summaries.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    return parser.parse_args()


def f1_score(precision: float, recall: float) -> float:
    if precision + recall <= 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def safe_sum(value) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "sum"):
            return float(value.sum())
        return float(sum(value))
    except Exception:
        return None


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    manifest_path = workspace / "artifacts" / "training_manifest.json"
    manifest = ensure_manifest(manifest_path, workspace)
    dataset_yaml = workspace / "configs" / "dataset.yaml"
    output_dir = workspace / "artifacts" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for run in manifest.get("runs", []):
        if run.get("status") != "completed":
            continue
        best_path = Path(run.get("best", ""))
        if not best_path.exists():
            continue
        from ultralytics import YOLO

        model = YOLO(str(best_path))
        metrics = model.val(
            data=str(dataset_yaml),
            split=args.split,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            verbose=False,
            plots=False,
        )
        precision = float(metrics.box.mp)
        recall = float(metrics.box.mr)
        row = {
            "name": run["name"],
            "checkpoint": str(best_path),
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
            "map50": float(metrics.box.map50),
            "map50_95": float(metrics.box.map),
            "fitness": float(getattr(metrics, "fitness", 0.0)),
            "tp": None,
            "fp": None,
            "fn": None,
            "detection_accuracy": None,
            "inference_ms": None,
        }
        tp = safe_sum(getattr(metrics.box, "tp", None))
        fp = safe_sum(getattr(metrics.box, "fp", None))
        fn = safe_sum(getattr(metrics.box, "fn", None))
        if tp is not None:
            row["tp"] = tp
        if fp is not None:
            row["fp"] = fp
        if fn is not None:
            row["fn"] = fn
        if tp is not None and fp is not None and fn is not None and (tp + fp + fn) > 0.0:
            row["detection_accuracy"] = tp / (tp + fp + fn)
        speed = getattr(metrics, "speed", None)
        if isinstance(speed, dict) and speed.get("inference") is not None:
            row["inference_ms"] = float(speed["inference"])
        rows.append(row)

    rows.sort(key=lambda item: item["map50"], reverse=True)
    json_path = output_dir / f"{args.split}_metrics.json"
    dump_json(json_path, {"split": args.split, "rows": rows})

    csv_path = output_dir / f"{args.split}_metrics.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "checkpoint",
                "precision",
                "recall",
                "f1",
                "map50",
                "map50_95",
                "fitness",
                "tp",
                "fp",
                "fn",
                "detection_accuracy",
                "inference_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    if args.split == "val" and rows:
        template_path = SCRIPT_ROOT / "configs" / "ensemble.template.yaml"
        template = load_json(template_path) if template_path.suffix == ".json" else None
        if template is None:
            import yaml
            template = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
        weights_by_name = {row["name"]: round(row["map50"], 6) for row in rows}
        for model_entry in template.get("models", []):
            if model_entry.get("name") in weights_by_name:
                model_entry["weight"] = weights_by_name[model_entry["name"]]
        dump_yaml(workspace / "configs" / "ensemble.generated.yaml", template)

    print(json.dumps({"split": args.split, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
