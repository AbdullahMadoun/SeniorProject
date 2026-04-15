from __future__ import annotations

import argparse

from ensemble_core import (
    compute_model_weights,
    confidence_grid,
    ensure_prediction_cache,
    fuse_ensemble_outputs,
    load_ground_truth,
    save_ensemble_yaml,
    select_best_threshold,
)
from common import dump_json, load_pipeline_config, load_yaml, resolve_project_root
from ensemble_tensorboard import log_ensemble_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select the final confidence threshold on val for the chosen WBF settings.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--device", default="0")
    parser.add_argument("--force-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    ensemble_yaml_path = project_root / "configs" / "ensemble.yaml"
    if not ensemble_yaml_path.exists():
        raise FileNotFoundError(f"Missing ensemble config: {ensemble_yaml_path}. Run 06_tune_wbf_threshold.py first.")
    ensemble_cfg = load_yaml(ensemble_yaml_path)
    per_tile = ensemble_cfg["per_tile_wbf"]

    manifest, raw_cache = ensure_prediction_cache(project_root, "val", args.device, force=args.force_cache)
    ground_truth = load_ground_truth(project_root, "val")
    model_weights = compute_model_weights(
        pipeline,
        manifest,
        raw_cache,
        ground_truth,
        float(per_tile["iou_thr"]),
        float(per_tile["skip_box_thr"]),
    )
    outputs = fuse_ensemble_outputs(
        pipeline,
        manifest,
        raw_cache,
        model_weights,
        float(per_tile["iou_thr"]),
        float(per_tile["skip_box_thr"]),
    )
    selected, sweep_rows = select_best_threshold(
        outputs,
        ground_truth,
        confidence_grid(pipeline),
        float(ensemble_cfg["precision_floor"]),
        float(pipeline["inference"]["primary_iou"]),
        float(pipeline["inference"]["all_damage_found_iou"]),
    )

    ensemble_cfg["model_weights"] = model_weights
    ensemble_cfg["selected_conf_threshold"] = selected["threshold"]
    ensemble_cfg["selected_val_metrics"] = {
        "precision": selected["precision"],
        "recall": selected["recall"],
        "f2": selected["f2"],
        "all_damage_found_rate": selected["all_damage_found_rate"],
    }
    save_ensemble_yaml(project_root, ensemble_cfg)
    dump_json(
        project_root / "artifacts" / "tuning" / "confidence_sweep_val.json",
        {"selected": selected, "rows": sweep_rows},
    )
    log_ensemble_metrics(
        project_root,
        run_name="val_selected",
        split="val",
        metrics={
            "precision": selected["precision"],
            "recall": selected["recall"],
            "f2": selected["f2"],
            "all_damage_found_rate": selected["all_damage_found_rate"],
            "selected_conf_threshold": selected["threshold"],
            "total_gt": selected["total_gt"],
            "total_predictions": selected["total_predictions"],
            "matched_gt": selected["matched_gt"],
        },
    )
    print(selected)


if __name__ == "__main__":
    main()
