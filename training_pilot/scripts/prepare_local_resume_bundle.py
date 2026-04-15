from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble a local run-shaped resume bundle from mirrored run metadata and checkpoints."
    )
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--state-dir", required=True, help="Local mirrored run-state directory containing args.yaml/results.csv.")
    parser.add_argument(
        "--weights-dir",
        required=True,
        help="Local mirrored weights directory containing best.pt/last.pt/epoch*.pt.",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Directory where the reconstructed resume bundle will be written.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def read_latest_epoch(results_csv: Path) -> int | None:
    if not results_csv.exists():
        return None
    with results_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return None
    return int(float(rows[-1]["epoch"]))


def main() -> None:
    args = parse_args()
    state_dir = Path(args.state_dir).resolve()
    weights_dir = Path(args.weights_dir).resolve()
    output_root = Path(args.output_root).resolve()
    bundle_root = output_root / args.run_name
    weights_out = bundle_root / "weights"

    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    weights_out.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, object]] = []
    for name in ("args.yaml", "results.csv", "results.png", "labels.jpg", "PR_curve.png", "P_curve.png", "R_curve.png", "F1_curve.png", "confusion_matrix.png", "confusion_matrix_normalized.png"):
        source = state_dir / name
        target = bundle_root / name
        if copy_if_exists(source, target):
            copied.append(
                {
                    "source": str(source),
                    "target": str(target),
                    "sha256": sha256_file(target),
                    "size": target.stat().st_size,
                }
            )

    for source in sorted(weights_dir.glob("*.pt")):
        target = weights_out / source.name
        shutil.copy2(source, target)
        copied.append(
            {
                "source": str(source),
                "target": str(target),
                "sha256": sha256_file(target),
                "size": target.stat().st_size,
            }
        )

    latest_epoch = read_latest_epoch(bundle_root / "results.csv")
    manifest = {
        "run_name": args.run_name,
        "bundle_root": str(bundle_root),
        "latest_epoch": latest_epoch,
        "copied_files": copied,
    }
    manifest_path = bundle_root / "resume_bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
