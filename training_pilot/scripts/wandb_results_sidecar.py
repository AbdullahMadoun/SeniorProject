from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror Ultralytics results.csv into a W&B run without touching the trainer.")
    parser.add_argument("--results-csv", required=True, help="Path to Ultralytics results.csv")
    parser.add_argument("--run-dir", required=True, help="Training run directory")
    parser.add_argument("--project", required=True, help="W&B project name")
    parser.add_argument("--run-name", required=True, help="W&B run name")
    parser.add_argument("--mode", default="offline", choices=["offline", "online", "disabled"], help="W&B mode")
    parser.add_argument("--poll-seconds", type=float, default=30.0, help="Polling interval while training is active")
    parser.add_argument("--idle-timeout-seconds", type=float, default=1800.0, help="Exit after this much idle time with no new rows")
    parser.add_argument("--finish-on-best", action="store_true", help="Exit once best.pt exists and the CSV stops growing")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def try_float(value: str) -> float | int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    if number.is_integer():
        return int(number)
    return number


def read_rows(results_csv: Path) -> list[dict[str, str]]:
    if not results_csv.exists():
        return []
    with results_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def row_to_metrics(row: dict[str, str]) -> tuple[int | None, dict[str, float | int]]:
    metrics: dict[str, float | int] = {}
    step: int | None = None
    for key, raw_value in row.items():
        value = try_float(raw_value)
        if value is None:
            continue
        metrics[key] = value
        if key == "epoch":
            step = int(value)
    return step, metrics


def load_config(run_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"run_dir": str(run_dir)}
    for rel in ["args.yaml", "run_metadata.json", "config_snapshot.yaml"]:
        path = run_dir / rel
        if path.suffix == ".yaml":
            data = load_yaml(path)
        else:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}
        if data:
            payload[rel] = data
    return payload


def should_finish(run_dir: Path, unchanged_since: float, idle_timeout: float, finish_on_best: bool) -> bool:
    if time.time() - unchanged_since >= idle_timeout:
        return True
    if finish_on_best and (run_dir / "weights" / "best.pt").exists():
        if time.time() - unchanged_since >= 120.0:
            return True
    return False


def main() -> None:
    args = parse_args()
    results_csv = Path(args.results_csv).resolve()
    run_dir = Path(args.run_dir).resolve()

    import wandb

    run = wandb.init(
        project=args.project,
        name=args.run_name,
        dir=str(run_dir),
        mode=args.mode,
        config=load_config(run_dir),
        settings=wandb.Settings(start_method="thread"),
        reinit=True,
    )

    last_logged_step = -1
    unchanged_since = time.time()

    try:
        while True:
            rows = read_rows(results_csv)
            if rows:
                newest_step_seen = last_logged_step
                for row in rows:
                    step, metrics = row_to_metrics(row)
                    if step is None or step <= last_logged_step:
                        continue
                    wandb.log(metrics, step=step)
                    newest_step_seen = step
                if newest_step_seen > last_logged_step:
                    last_logged_step = newest_step_seen
                    unchanged_since = time.time()
                    print(f"[wandb-sidecar] logged through epoch {last_logged_step}", flush=True)
            if should_finish(run_dir, unchanged_since, args.idle_timeout_seconds, args.finish_on_best):
                break
            time.sleep(args.poll_seconds)
    finally:
        summary_rows = read_rows(results_csv)
        if summary_rows:
            step, metrics = row_to_metrics(summary_rows[-1])
            if step is not None:
                run.summary["last_logged_epoch"] = step
            for key, value in metrics.items():
                run.summary[f"final/{key}"] = value
        run.finish()


if __name__ == "__main__":
    main()
