from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a recall-biased zero-shot ensemble search on a validation split.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def resolve_project_root(raw: str) -> Path:
    here = Path(__file__).resolve().parents[1]
    if not raw:
        return here
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (here / path).resolve()


def default_model_paths(project_root: Path) -> list[Path]:
    weights = project_root / "weights" / "pretrained"
    return [
        weights / "yolo12s_rdd2022.pt",
        weights / "ozair_yolov8_rdd.pt",
        weights / "oracl4_yolov8_rdd.pt",
        weights / "obc_yolov8_rdd.pt",
    ]


def experiments() -> list[dict[str, float | int | str]]:
    return [
        {"name": "baseline", "yolo_conf": 0.01, "yolo_iou": 0.60, "yolo_max_det": 300, "wbf_iou": 0.40, "wbf_skip": 0.01},
        {"name": "recall_lite", "yolo_conf": 0.005, "yolo_iou": 0.75, "yolo_max_det": 600, "wbf_iou": 0.40, "wbf_skip": 0.01},
        {"name": "balanced_f2", "yolo_conf": 0.003, "yolo_iou": 0.75, "yolo_max_det": 800, "wbf_iou": 0.40, "wbf_skip": 0.01},
        {"name": "recall_push", "yolo_conf": 0.003, "yolo_iou": 0.80, "yolo_max_det": 800, "wbf_iou": 0.35, "wbf_skip": 0.01},
        {"name": "recall_push_skip", "yolo_conf": 0.003, "yolo_iou": 0.85, "yolo_max_det": 1000, "wbf_iou": 0.35, "wbf_skip": 0.005},
        {"name": "recall_floor", "yolo_conf": 0.001, "yolo_iou": 0.85, "yolo_max_det": 1200, "wbf_iou": 0.35, "wbf_skip": 0.005},
        {"name": "recall_floor_wbf40", "yolo_conf": 0.001, "yolo_iou": 0.90, "yolo_max_det": 1200, "wbf_iou": 0.40, "wbf_skip": 0.005},
        {"name": "precision_guard", "yolo_conf": 0.005, "yolo_iou": 0.70, "yolo_max_det": 600, "wbf_iou": 0.40, "wbf_skip": 0.02},
    ]


def run_experiment(
    project_root: Path,
    dataset_root: Path,
    device: str,
    output_root: Path,
    model_paths: list[Path],
    spec: dict[str, float | int | str],
) -> dict:
    output_path = output_root / f"{spec['name']}.json"
    cmd = [
        sys.executable,
        str(project_root / "evaluate_model_ensemble.py"),
        "--dataset-root",
        str(dataset_root),
        "--split",
        "val",
        "--device",
        str(device),
        "--yolo-conf",
        str(spec["yolo_conf"]),
        "--yolo-iou",
        str(spec["yolo_iou"]),
        "--yolo-max-det",
        str(spec["yolo_max_det"]),
        "--wbf-iou",
        str(spec["wbf_iou"]),
        "--wbf-skip-box-thr",
        str(spec["wbf_skip"]),
        "--tta-imgsz",
        "530",
        "--tta-imgsz",
        "640",
        "--tta-imgsz",
        "800",
        "--tta-flip",
        "--output",
        str(output_path),
    ]
    for model_path in model_paths:
        cmd.extend(["--yolo-model", str(model_path)])

    env = os.environ.copy()
    extra_path = str(project_root / "external" / "yolov12")
    env["PYTHONPATH"] = extra_path if not env.get("PYTHONPATH") else f"{extra_path}:{env['PYTHONPATH']}"
    subprocess.run(cmd, check=True, cwd=project_root, env=env)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload["experiment"] = spec
    return payload


def write_summary_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "# Zero-Shot Ensemble Search",
        "",
        "| Rank | Name | F2 | Recall | Precision | All Found | mAP50 N/A | YOLO conf | YOLO IoU | max_det | WBF IoU | WBF skip |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(rows, start=1):
        exp = row["experiment"]
        lines.append(
            f"| {idx} | {exp['name']} | {row['f2']:.4f} | {row['damage_coverage_recall']:.4f} | "
            f"{row['precision']:.4f} | {row['all_damages_found_image_rate']:.4f} | - | "
            f"{exp['yolo_conf']} | {exp['yolo_iou']} | {exp['yolo_max_det']} | {exp['wbf_iou']} | {exp['wbf_skip']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root)
    dataset_root = Path(args.dataset_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else (project_root / "artifacts" / "eval_search")
    output_root.mkdir(parents=True, exist_ok=True)

    model_paths = default_model_paths(project_root)
    rows: list[dict] = []
    for spec in experiments():
        payload = run_experiment(project_root, dataset_root, args.device, output_root, model_paths, spec)
        rows.append(payload)

    rows.sort(key=lambda row: (-row["f2"], -row["damage_coverage_recall"], -row["precision"]))
    summary = {
        "best_experiment": rows[0]["experiment"]["name"],
        "rows": rows,
    }
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_summary_markdown(output_root / "summary.md", rows)

    best_json = output_root / f"{rows[0]['experiment']['name']}.json"
    render_cmd = [
        sys.executable,
        str(project_root / "scripts" / "render_ensemble_eval_samples.py"),
        "--dataset-root",
        str(dataset_root),
        "--eval-json",
        str(best_json),
        "--output-dir",
        str(output_root / "best_samples"),
        "--count",
        "10",
        "--seed",
        str(args.seed),
    ]
    subprocess.run(render_cmd, check=True, cwd=project_root)
    print(json.dumps({k: rows[0][k] for k in ["precision", "damage_coverage_recall", "f2", "all_damages_found_image_rate"]}, indent=2))


if __name__ == "__main__":
    main()
