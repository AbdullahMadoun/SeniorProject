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
pip install -r requirements.txt
```

If the base image already has PyTorch with CUDA, keep it. Do not replace it unless it is broken.

This requirements file pins `numpy<2.2` intentionally so `ensemble-boxes` and `numba` stay compatible in a clean training env.

## Instance Checks

Before starting the pipeline, verify the rented box:

```bash
nvidia-smi
df -h
python --version
```

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
bash scripts/03_train_all.sh
python scripts/04_hard_negative_mining.py
bash scripts/05_second_pass_train.sh
python scripts/06_tune_wbf_threshold.py
python scripts/07_select_conf_threshold.py
python scripts/08_final_evaluation.py
```

Outputs:

- `artifacts/prep/filter_stats.json`
- `artifacts/prep/filter_manifest.json`
- `artifacts/prep/split_summary.json`
- `configs/dataset.yaml`
- `weights/pretrained/download_manifest.json`
- `configs/ensemble.yaml`
- `artifacts/tuning/wbf_combo_search_val.json`
- `artifacts/tuning/confidence_sweep_val.json`
- `artifacts/final_test_evaluation.json` after the one-time test pass

## Verified Source Reality

- `rezzzq` Hugging Face file is currently `yolo12s_RDD2022_best.pt`, not `model.pt`
- `oracl4` exposes `models/YOLOv8_Small_RDD.pt`
- `oracl4` training material is notebook-based and ultimately uses Ultralytics training
- `OBC-YOLOv8` does not publish a release asset for the pretrained road-damage checkpoint

## OBC Initializer Rule

- Use a repo-bundled OBC checkpoint only if the repo documentation explicitly ties that checkpoint to RDD or RDD-China pretraining
- If no such explicit documentation exists, initialize OBC from `yolov8l.pt`
- Final ensemble weight for OBC is still the second-pass `runs/obc_yolov8_custom/weights/best.pt`

## Locked Values Now Encoded

- Albumentations stack and args are pinned in `configs/max_recall/pipeline.yaml`
- second-pass hard-negative fine-tune is fixed to `12` epochs
- confidence sweep is fixed to `0.01..0.50` in `0.01` steps
- WBF ranking rule is recall-first under `precision >= 0.30`

End-to-end execution is pending dataset download and OBC initializer resolution; all scripts compile and expose CLI help.

## Ordered Vast Flow

Run the pipeline in this exact order after the dataset is present:

```bash
python scripts/00_filter_and_remap.py
python scripts/01_split_dataset.py
python scripts/02_download_weights.py
bash scripts/03_train_all.sh
python scripts/04_hard_negative_mining.py
bash scripts/05_second_pass_train.sh
python scripts/06_tune_wbf_threshold.py
python scripts/07_select_conf_threshold.py
# 08 stays locked until all above finish
```

Do not run step `08_final_evaluation.py` early.

## Long Runs

Use `tmux` or `screen` for `03_train_all.sh` and the second-pass fine-tune.

Example:

```bash
tmux new -s training
bash scripts/03_train_all.sh
```

Detach with `Ctrl+B` then `D`, and reattach with:

```bash
tmux attach -t training
```
