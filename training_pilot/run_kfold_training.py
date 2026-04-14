from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from guide_utils import summarize_manifest, upsert_manifest_run
from train_from_guide_config import resolve_config_path, run_training_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train one guide config across prepared K-fold splits.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--fold-root", default="artifacts/kfold")
    parser.add_argument("--fold", action="append", default=[], help="Optional fold names like fold_01.")
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--cache", choices=["inherit", "ram", "disk", "off"], default="inherit")
    parser.add_argument("--fraction", type=float, default=1.0)
    parser.add_argument("--batch-auto", action="store_true")
    parser.add_argument("--multi-scale", action="store_true")
    parser.add_argument("--enable-mlflow", action="store_true")
    parser.add_argument("--disable-mlflow", action="store_true")
    parser.add_argument("--enable-tensorboard", action="store_true")
    parser.add_argument("--disable-tensorboard", action="store_true")
    parser.add_argument("--run-tag", default="", help="Optional label to record in run metadata.")
    parser.add_argument("--name-suffix", default="", help="Optional suffix appended after the fold suffix.")
    parser.add_argument("--project-override", default="runs_kfold", help="Project root for fold runs.")
    parser.add_argument("--clear-manifest", action="store_true")
    return parser.parse_args()


def discover_folds(fold_root: Path, selected: set[str]) -> list[Path]:
    folds = [path for path in sorted(fold_root.glob("fold_*")) if (path / "dataset.yaml").exists()]
    if selected:
        folds = [path for path in folds if path.name in selected]
    if not folds:
        raise FileNotFoundError(f"No fold dataset.yaml files were found under {fold_root}")
    return folds


def main() -> None:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    config_path = resolve_config_path(args.config)
    fold_root = (workspace / args.fold_root).resolve()
    manifest_path = fold_root / "training_manifest.json"
    if args.clear_manifest and manifest_path.exists():
        manifest_path.unlink()

    selected = set(args.fold)
    folds = discover_folds(fold_root, selected)
    base_name_suffix = args.name_suffix

    run_summaries: list[dict] = []
    for fold_dir in folds:
        args.data_override = str((fold_dir / "dataset.yaml").resolve())
        args.name_suffix = f"__{fold_dir.name}{base_name_suffix}"
        try:
            run_info = run_training_config(
                workspace=workspace,
                config_path=config_path,
                device=args.device,
                workers=args.workers,
                dry_run=args.dry_run,
                allow_missing_optional=False,
                args=args,
            )
            run_info["fold"] = fold_dir.name
            run_info["fold_dataset"] = args.data_override
            run_info["base_name"] = run_info["name"].split(f"__{fold_dir.name}", 1)[0]
        except Exception as exc:
            run_info = {
                "name": f"{config_path.stem}__{fold_dir.name}{base_name_suffix}",
                "config": str(config_path),
                "fold": fold_dir.name,
                "fold_dataset": args.data_override,
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
