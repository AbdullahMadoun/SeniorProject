from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from guide_utils import SCRIPT_ROOT, summarize_manifest, upsert_manifest_run
from train_from_guide_config import resolve_config_path, run_training_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the guide-aligned multi-model training stack.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--model-set",
        default=str((SCRIPT_ROOT / "configs" / "model_sets" / "guide_v2_single_class.yaml").resolve()),
    )
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--data-override", default="", help="Optional dataset YAML override for every run.")
    parser.add_argument("--project-override", default="", help="Optional project directory override for every run.")
    parser.add_argument("--name-suffix", default="", help="Optional suffix appended to every run name.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true", help="Record failed runs and continue with the rest.")
    parser.add_argument("--only", action="append", default=[], help="Optional run names to include.")
    parser.add_argument("--cache", choices=["inherit", "ram", "disk", "off"], default="inherit")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--batch-auto", action="store_true")
    parser.add_argument("--multi-scale", action="store_true")
    parser.add_argument("--enable-mlflow", action="store_true")
    parser.add_argument("--disable-mlflow", action="store_true")
    parser.add_argument("--enable-tensorboard", action="store_true")
    parser.add_argument("--disable-tensorboard", action="store_true")
    parser.add_argument("--run-tag", default="", help="Optional label to record in run metadata.")
    parser.add_argument("--clear-manifest", action="store_true", help="Delete the existing training manifest first.")
    return parser.parse_args()


try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install training_pilot/requirements-guide.txt first.") from exc


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    model_set_path = resolve_config_path(args.model_set)
    model_set = yaml.safe_load(model_set_path.read_text(encoding="utf-8")) or {}
    manifest_path = workspace / "artifacts" / "training_manifest.json"
    if args.clear_manifest and manifest_path.exists():
        manifest_path.unlink()

    run_summaries: list[dict] = []
    selected = set(args.only)
    for entry in model_set.get("models", []):
        config_ref = entry["config"]
        optional = bool(entry.get("optional", False))
        config_path = (model_set_path.parent / config_ref).resolve()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        name = str(config.get("name", config_path.stem))
        run_name = f"{name}{args.name_suffix}" if args.name_suffix else name
        if selected and name not in selected:
            continue
        if optional and not args.include_optional:
            run_info = {
                "name": run_name,
                "config": str(config_path),
                "status": "skipped_optional_disabled",
            }
        else:
            try:
                run_info = run_training_config(
                    workspace=workspace,
                    config_path=config_path,
                    device=args.device,
                    workers=args.workers,
                    dry_run=args.dry_run,
                    allow_missing_optional=args.include_optional,
                    args=args,
                )
            except Exception as exc:
                run_info = {
                    "name": run_name,
                    "config": str(config_path),
                    "status": "failed",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                upsert_manifest_run(manifest_path, workspace, run_info)
                run_summaries.append(run_info)
                if not args.continue_on_error:
                    raise
                continue
        upsert_manifest_run(manifest_path, workspace, run_info)
        run_summaries.append(run_info)

    print(json.dumps({"runs": run_summaries, "manifest": summarize_manifest(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
