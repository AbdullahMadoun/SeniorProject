from __future__ import annotations

import argparse

from ensemble_core import compute_ap50, ensure_prediction_cache, fuse_ensemble_outputs, load_ground_truth
from common import dump_json, load_pipeline_config, load_yaml, resolve_project_root
from ensemble_tensorboard import log_ensemble_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the one-time final test evaluation for the max-recall ensemble.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--device", default="0")
    parser.add_argument("--force-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    result_path = project_root / "artifacts" / "final_test_evaluation.json"
    if result_path.exists():
        raise RuntimeError(
            f"Final test evaluation already exists at {result_path}. "
            "The test split is locked and this script is intentionally one-shot."
        )

    pipeline = load_pipeline_config(project_root)
    ensemble_cfg = load_yaml(project_root / "configs" / "ensemble.yaml")
    selected_threshold = ensemble_cfg.get("selected_conf_threshold")
    if selected_threshold is None:
        raise RuntimeError("Missing selected_conf_threshold in configs/ensemble.yaml. Run 07_select_conf_threshold.py first.")

    manifest, raw_cache = ensure_prediction_cache(project_root, "test", args.device, force=args.force_cache)
    ground_truth = load_ground_truth(project_root, "test")
    outputs = fuse_ensemble_outputs(
        pipeline,
        manifest,
        raw_cache,
        {key: float(value) for key, value in ensemble_cfg["model_weights"].items()},
        float(ensemble_cfg["per_tile_wbf"]["iou_thr"]),
        float(ensemble_cfg["per_tile_wbf"]["skip_box_thr"]),
    )

    from ensemble_core import evaluate_outputs

    metrics = evaluate_outputs(
        outputs,
        ground_truth,
        threshold=float(selected_threshold),
        primary_iou=float(pipeline["inference"]["primary_iou"]),
        all_found_iou=float(pipeline["inference"]["all_damage_found_iou"]),
        include_per_image=True,
    )
    metrics["map50"] = compute_ap50(outputs, ground_truth, iou_thr=float(pipeline["inference"]["primary_iou"]))
    metrics["split"] = "test"
    metrics["selected_conf_threshold"] = float(selected_threshold)
    metrics["per_tile_wbf"] = ensemble_cfg["per_tile_wbf"]
    metrics["merge_wbf"] = ensemble_cfg["merge_wbf"]
    metrics["model_weights"] = ensemble_cfg["model_weights"]

    dump_json(result_path, metrics)
    log_ensemble_metrics(
        project_root,
        run_name="test_final",
        split="test",
        metrics=metrics,
    )
    print({key: value for key, value in metrics.items() if key != "per_image"})


if __name__ == "__main__":
    main()
