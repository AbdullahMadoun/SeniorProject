# Max Recall Vast Setup

This is the new directive-aligned path. Use `training_pilot` itself as the project root on Vast.

## Scope

- Dataset: Kaggle `lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes`
- Classes kept: `pothole`, `crack`
- Class dropped entirely: `manhole`
- Final class: `damage`
- Primary metric: `Recall@IoU0.5`
- Test policy: one final evaluation only

## Why The Runtime Is Split

This pipeline mixes three different `ultralytics` codebases:

- standard Ultralytics
- `sunsmarterjie/yolov12`
- `wulihuge/OBC-YOLOv8`

They should not share one import context. The training and inference scripts are being built around backend-isolated Python processes so the Vast workflow stays stable.

## Baseline Vast Environment

Recommended starting point:

```bash
cd /workspace/Skylink2/training_pilot
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install ultralytics huggingface_hub kaggle pyyaml scikit-learn pandas pillow opencv-python ensemble-boxes albumentations
```

If the base image already has PyTorch with CUDA, keep it. Do not replace it unless it is broken.

## Kaggle Access

The dataset download step needs Kaggle credentials. On Vast, set:

```bash
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
```

Then download into the locked location:

```bash
kaggle datasets download \
  -d lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes \
  -p data/raw
```

Unzip the archive under `data/raw/` before running the filter step.

## Current Buildable Steps

These are implemented now:

```bash
python scripts/00_filter_and_remap.py
python scripts/01_split_dataset.py
python scripts/02_download_weights.py
```

Outputs:

- `artifacts/prep/filter_stats.json`
- `artifacts/prep/filter_manifest.json`
- `artifacts/prep/split_summary.json`
- `configs/dataset.yaml`
- `weights/pretrained/download_manifest.json`

## Verified Source Reality

- `rezzzq` Hugging Face file is currently `yolo12s_RDD2022_best.pt`, not `model.pt`
- `oracl4` exposes `models/YOLOv8_Small_RDD.pt`
- `oracl4` training material is notebook-based and ultimately uses Ultralytics training
- `OBC-YOLOv8` does not publish a release asset for the pretrained road-damage checkpoint

## Current Known Gaps Before Training Can Be Declared Final

The directive is missing a few values that materially affect reproducibility:

- exact Albumentations probabilities and any non-default transform magnitudes
- exact second-pass epoch count inside the allowed `10-15` range
- exact OBC checkpoint choice if the repo-bundled candidate is not acceptable

I am not hardcoding those silently. The pipeline config has explicit placeholders for the unresolved values.
