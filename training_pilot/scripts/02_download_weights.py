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
    parser.add_argument(
        "--obc-weight-file",
        default="best.pt",
        choices=["best.pt", "updated-model.pt", "yolov8n.pt"],
        help="Repo-bundled OBC weight candidate to promote into weights/pretrained.",
    )
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

    obc_source = obc_dest / "ultralytics10.24" / args.obc_weight_file
    if not obc_source.exists():
        raise FileNotFoundError(f"Selected OBC weight candidate does not exist: {obc_source}")
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
            "obc_yolov8_rdd.pt": {
                "source": "repo_bundle",
                "repo": "wulihuge/OBC-YOLOv8",
                "path": f"ultralytics10.24/{args.obc_weight_file}",
                "warning": (
                    "The OBC repo does not expose a machine-readable release asset for the road-damage checkpoint. "
                    "This pipeline currently promotes the selected repo-bundled candidate file."
                ),
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
