from __future__ import annotations

import argparse
import os
import urllib.request
from pathlib import Path


DEFAULT_VLM_MODEL = os.getenv("VLM_MODEL", os.getenv("MODEL_NAME", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"))
DEFAULT_YOLO_V12_REPO = os.getenv("YOLO_MODEL_V12", "rezzzq/yolo12s-road-damage-rdd2022")
DEFAULT_YOLO_V8_URL = os.getenv(
    "YOLO_V8_WEIGHTS_URL",
    "https://huggingface.co/oracl4/YOLOv8_Small_RDD/resolve/main/YOLOv8_Small_RDD.pt",
)
DEFAULT_YOLO_V8_DEST = os.getenv("YOLO_MODEL_V8", str(Path("models") / "YOLOv8_Small_RDD.pt"))
DEFAULT_CACHE_DIR = os.getenv("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
DEFAULT_ENABLE_VLM = os.getenv("ENABLE_VLM", "true").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_ENABLE_YOLO_V8 = os.getenv("ENABLE_YOLO_V8", "true" if DEFAULT_ENABLE_VLM else "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def download_vlm(model_id: str, cache_dir: str | None) -> None:
    from huggingface_hub import snapshot_download
    from transformers import AutoProcessor

    print(f"[PREFETCH] Downloading VLM model: {model_id}")
    snapshot_download(repo_id=model_id, cache_dir=cache_dir, resume_download=True)
    AutoProcessor.from_pretrained(model_id, cache_dir=cache_dir, trust_remote_code=True)


def download_yolo_v12(repo_id: str, cache_dir: str | None) -> None:
    from huggingface_hub import hf_hub_download

    filename = "yolo12s_RDD2022_best.pt" if "rezzzq" in repo_id else "best.pt"
    print(f"[PREFETCH] Downloading YOLOv12 weights from {repo_id}/{filename}")
    hf_hub_download(repo_id=repo_id, filename=filename, cache_dir=cache_dir)


def download_yolo_v8(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"[PREFETCH] Downloading YOLOv8 weights to {destination}")
    urllib.request.urlretrieve(url, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-download VLM and YOLO model assets.")
    parser.add_argument("--vlm-model", default=DEFAULT_VLM_MODEL)
    parser.add_argument("--yolo-v12-repo", default=DEFAULT_YOLO_V12_REPO)
    parser.add_argument("--yolo-v8-url", default=DEFAULT_YOLO_V8_URL)
    parser.add_argument("--yolo-v8-dest", default=DEFAULT_YOLO_V8_DEST)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--hf-token", default=os.getenv("HUGGINGFACE_HUB_TOKEN", ""))
    parser.add_argument("--skip-vlm", action="store_true", default=not DEFAULT_ENABLE_VLM)
    parser.add_argument("--skip-yolo-v12", action="store_true")
    parser.add_argument("--skip-yolo-v8", action="store_true", default=not DEFAULT_ENABLE_YOLO_V8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.hf_token:
        os.environ["HUGGINGFACE_HUB_TOKEN"] = args.hf_token

    cache_dir = args.cache_dir or None
    if not args.skip_vlm:
        download_vlm(args.vlm_model, cache_dir)
    if not args.skip_yolo_v12:
        download_yolo_v12(args.yolo_v12_repo, cache_dir)
    if not args.skip_yolo_v8:
        download_yolo_v8(args.yolo_v8_url, Path(args.yolo_v8_dest))

    print("[PREFETCH] Model assets are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
