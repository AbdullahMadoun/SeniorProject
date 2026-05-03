from __future__ import annotations

from pathlib import Path
from typing import Any


def log_ensemble_metrics(
    project_root: Path,
    run_name: str,
    split: str,
    metrics: dict[str, Any],
    *,
    step: int = 0,
) -> Path:
    from torch.utils.tensorboard import SummaryWriter

    log_dir = (project_root / "runs" / "ensemble_metrics" / run_name).resolve()
    writer = SummaryWriter(log_dir=str(log_dir))

    scalar_map = {
        "precision": metrics.get("precision"),
        "recall": metrics.get("recall"),
        "f2": metrics.get("f2"),
        "all_damage_found_rate": metrics.get("all_damage_found_rate"),
        "map50": metrics.get("map50"),
        "selected_conf_threshold": metrics.get("selected_conf_threshold"),
    }
    for key, value in scalar_map.items():
        if value is None:
            continue
        writer.add_scalar(f"{split}/{key}", float(value), global_step=step)

    total_gt = metrics.get("total_gt")
    total_predictions = metrics.get("total_predictions")
    matched_gt = metrics.get("matched_gt")
    if total_gt is not None:
        writer.add_scalar(f"{split}/total_gt", int(total_gt), global_step=step)
    if total_predictions is not None:
        writer.add_scalar(f"{split}/total_predictions", int(total_predictions), global_step=step)
    if matched_gt is not None:
        writer.add_scalar(f"{split}/matched_gt", int(matched_gt), global_step=step)

    writer.flush()
    writer.close()
    return log_dir
