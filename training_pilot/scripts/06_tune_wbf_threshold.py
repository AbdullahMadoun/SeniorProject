from __future__ import annotations

import argparse
from pathlib import Path

from ensemble_core import (
    compute_model_weights,
    confidence_grid,
    ensure_prediction_cache,
    fuse_ensemble_outputs,
    load_ground_truth,
    save_ensemble_yaml,
    select_best_threshold,
    wbf_grid,
)
from common import dump_json, load_pipeline_config, resolve_project_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune per-tile WBF IoU and skip threshold on the val split.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--device", default="0")
    parser.add_argument("--force-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    manifest, raw_cache = ensure_prediction_cache(project_root, "val", args.device, force=args.force_cache)
    ground_truth = load_ground_truth(project_root, "val")
    conf_values = confidence_grid(pipeline)
    precision_floor = float(pipeline["inference"]["precision_floor"])
    primary_iou = float(pipeline["inference"]["primary_iou"])
    all_found_iou = float(pipeline["inference"]["all_damage_found_iou"])

    combo_rows: list[dict] = []
    for wbf_iou, skip_box_thr in wbf_grid(pipeline):
        model_weights = compute_model_weights(pipeline, manifest, raw_cache, ground_truth, wbf_iou, skip_box_thr)
        outputs = fuse_ensemble_outputs(pipeline, manifest, raw_cache, model_weights, wbf_iou, skip_box_thr)
        best_threshold, sweep_rows = select_best_threshold(
            outputs,
            ground_truth,
            conf_values,
            precision_floor,
            primary_iou,
            all_found_iou,
        )
        combo_rows.append(
            {
                "wbf_iou": wbf_iou,
                "skip_box_thr": skip_box_thr,
                "best_threshold": best_threshold["threshold"],
                "best_precision": best_threshold["precision"],
                "best_recall": best_threshold["recall"],
                "best_f2": best_threshold["f2"],
                "best_all_damage_found_rate": best_threshold["all_damage_found_rate"],
                "model_weights": model_weights,
                "threshold_sweep": sweep_rows,
            }
        )

    combo_rows.sort(key=lambda item: (-item["best_recall"], -item["best_precision"], item["best_threshold"]))
    selected = combo_rows[0]

    save_ensemble_yaml(
        project_root,
        {
            "split_selected_on": "val",
            "per_tile_wbf": {
                "iou_thr": selected["wbf_iou"],
                "skip_box_thr": selected["skip_box_thr"],
                "conf_type": pipeline["inference"]["per_tile_wbf"]["conf_type"],
            },
            "merge_wbf": pipeline["inference"]["merge_wbf"],
            "model_weight_conf": pipeline["inference"]["model_weight_conf"],
            "model_weights": selected["model_weights"],
            "precision_floor": precision_floor,
            "selected_conf_threshold": None,
            "selection_notes": {
                "combo_ranking": "max recall under precision floor, tie break by higher precision then lower confidence threshold",
            },
        },
    )
    dump_json(
        project_root / "artifacts" / "tuning" / "wbf_combo_search_val.json",
        {"selected": selected, "rows": combo_rows},
    )
    print(
        {
            "selected_wbf_iou": selected["wbf_iou"],
            "selected_skip_box_thr": selected["skip_box_thr"],
            "best_recall": selected["best_recall"],
            "best_precision": selected["best_precision"],
            "best_threshold": selected["best_threshold"],
        }
    )


if __name__ == "__main__":
    main()
