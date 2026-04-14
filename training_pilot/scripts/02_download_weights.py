from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from huggingface_hub import hf_hub_download

from common import dump_json, load_pipeline_config, resolve_project_root


GIT_REPOS = {
    "yolov12": "https://github.com/sunsmarterjie/yolov12.git",
    "oracl4": "https://github.com/oracl4/RoadDamageDetection.git",
    "obc": "https://github.com/wulihuge/OBC-YOLOv8.git",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download pretrained checkpoints and external repos for the max-recall stack.")
    parser.add_argument("--project-root", default="", help="training_pilot root. Defaults to the local repo copy.")
    return parser.parse_args()


def run_git_clone_or_update(url: str, dest: Path) -> None:
    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"], check=True)
        return
    subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True)


def download_oracl4_weight(dest: Path) -> None:
    weight_url = "https://raw.githubusercontent.com/oracl4/RoadDamageDetection/main/models/YOLOv8_Small_RDD.pt"
    import urllib.request

    with urllib.request.urlopen(weight_url) as response:
        dest.write_bytes(response.read())


def ensure_ultralytics_weight(model_name: str, dest_dir: Path) -> Path:
    from ultralytics import YOLO

    model = YOLO(model_name)
    ckpt_path = getattr(model, "ckpt_path", None)
    if not ckpt_path:
        raise RuntimeError(f"Unable to resolve downloaded path for {model_name}")
    source = Path(ckpt_path).resolve()
    dest = dest_dir / model_name
    if not dest.exists():
        shutil.copy2(source, dest)
    return dest


def documented_obc_repo_checkpoint(obc_root: Path) -> tuple[Path | None, str]:
    readme_path = obc_root / "README.md"
    if not readme_path.exists():
        return None, "README.md missing"

    lines = readme_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    candidate_names = ("best.pt", "updated-model.pt")
    context_hits: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        for candidate in candidate_names:
            if candidate.lower() not in lowered:
                continue
            window = " ".join(lines[max(0, index - 2) : min(len(lines), index + 3)]).lower()
            if "rdd" in window or "road damage" in window or "rddchina" in window or "rdd2022" in window:
                context_hits.append((candidate, index))

    for candidate, _ in context_hits:
        repo_file = obc_root / "ultralytics10.24" / candidate
        if repo_file.exists():
            return repo_file, f"README explicitly documents {candidate} with RDD context"
    return None, "No repo-bundled checkpoint is explicitly documented in README as RDD/RDD-China pretrained"


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    config = load_pipeline_config(project_root)

    pretrained_dir = project_root / config["weights"]["pretrained_dir"]
    pretrained_dir.mkdir(parents=True, exist_ok=True)
    external_dir = project_root / "external"
    external_dir.mkdir(parents=True, exist_ok=True)

    yolov12_dest = project_root / config["external"]["yolov12_repo"]
    oracl4_dest = project_root / config["external"]["oracl4_repo"]
    obc_dest = project_root / config["external"]["obc_repo"]

    run_git_clone_or_update(GIT_REPOS["yolov12"], yolov12_dest)
    run_git_clone_or_update(GIT_REPOS["oracl4"], oracl4_dest)
    run_git_clone_or_update(GIT_REPOS["obc"], obc_dest)

    yolo12_hf = Path(
        hf_hub_download(
            repo_id="rezzzq/yolo12s-road-damage-rdd2022",
            filename="yolo12s_RDD2022_best.pt",
        )
    )
    shutil.copy2(yolo12_hf, pretrained_dir / "yolo12s_rdd2022.pt")

    ozair_hf = Path(
        hf_hub_download(
            repo_id="ozair23/yolov8-road-damage-detector",
            filename="best.pt",
        )
    )
    shutil.copy2(ozair_hf, pretrained_dir / "ozair_yolov8_rdd.pt")

    download_oracl4_weight(pretrained_dir / "oracl4_yolov8_rdd.pt")
    yolov8l_path = ensure_ultralytics_weight("yolov8l.pt", pretrained_dir)

    obc_source, obc_resolution_note = documented_obc_repo_checkpoint(obc_dest)
    obc_strategy = "repo_documented_rdd_checkpoint"
    if obc_source is None:
        obc_source = yolov8l_path
        obc_strategy = "fallback_ultralytics_yolov8l_base"
    shutil.copy2(obc_source, pretrained_dir / "obc_yolov8_rdd.pt")

    manifest = {
        "pretrained_dir": str(pretrained_dir.resolve()),
        "files": {
            "yolo12s_rdd2022.pt": {
                "source": "huggingface",
                "repo_id": "rezzzq/yolo12s-road-damage-rdd2022",
                "filename": "yolo12s_RDD2022_best.pt",
            },
            "ozair_yolov8_rdd.pt": {
                "source": "huggingface",
                "repo_id": "ozair23/yolov8-road-damage-detector",
                "filename": "best.pt",
            },
            "oracl4_yolov8_rdd.pt": {
                "source": "github_raw",
                "repo": "oracl4/RoadDamageDetection",
                "path": "models/YOLOv8_Small_RDD.pt",
            },
            "yolov8l.pt": {
                "source": "ultralytics",
                "model_name": "yolov8l.pt",
            },
            "obc_yolov8_rdd.pt": {
                "source": "repo_bundle" if obc_strategy == "repo_documented_rdd_checkpoint" else "ultralytics",
                "repo": "wulihuge/OBC-YOLOv8" if obc_strategy == "repo_documented_rdd_checkpoint" else None,
                "path": str(obc_source.resolve()),
                "resolution_strategy": obc_strategy,
                "resolution_note": obc_resolution_note,
            },
        },
        "repos": {
            "yolov12": str(yolov12_dest.resolve()),
            "oracl4": str(oracl4_dest.resolve()),
            "obc": str(obc_dest.resolve()),
        },
    }
    dump_json(pretrained_dir / "download_manifest.json", manifest)
    print(manifest)


if __name__ == "__main__":
    main()
