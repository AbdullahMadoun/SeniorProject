# Guide-Aligned Training Setup

This workflow implements the local training setup described in:

- [RDD_Implementation_Guide_v2.md](D:\downloads\SeniorProject\guides\RDD_Implementation_Guide_v2.md)
- [RDD_Guide_v3_Patch.md](D:\downloads\SeniorProject\guides\RDD_Guide_v3_Patch.md)

It keeps the current `training_pilot/` scripts intact and adds a clean, config-driven path for:

- one detection class: `damage`
- pretrained initialization only
- the guide model lineup
- reproducible `results.csv` outputs
- TensorBoard and MLflow compatible logging
- repeatable validation summaries and training curves
- split auditing, duplicate detection, and dataset fingerprinting
- K-fold cross-validation support for small-data model selection
- structured hyperparameter tuning using Ultralytics' native tuner

## What Changed

New files:

- `training_pilot/prepare_one_class_detection_dataset.py`
- `training_pilot/download_guide_weights.py`
- `training_pilot/train_from_guide_config.py`
- `training_pilot/run_guide_training.py`
- `training_pilot/evaluate_guide_models.py`
- `training_pilot/plot_guide_training_curves.py`
- `training_pilot/build_kfold_splits.py`
- `training_pilot/tune_guide_model.py`
- `training_pilot/run_kfold_training.py`
- `training_pilot/summarize_kfold_results.py`
- `training_pilot/guide_utils.py`
- `training_pilot/requirements-guide.txt`
- `training_pilot/configs/models/*.yaml`
- `training_pilot/configs/model_sets/guide_v2_single_class.yaml`
- `training_pilot/configs/ensemble.template.yaml`
- `training_pilot/configs/tuning/small_dataset_search_space.yaml`

## Workflow Contract

### Dataset

The intended dataset contract is:

- task: object detection
- classes: one class only
- final class name: `damage`
- final label row format: `class x_center y_center width height`

The prep script is strict on purpose.

- If the Roboflow export is already plain detection labels, it remaps every class to `0` and builds the workspace.
- If the export is segmentation-style YOLO, it stops by default and tells you to re-export as object detection.
- If you deliberately want lossy polygon-to-box conversion, you must opt in with `--allow-segmentation-to-box`.
- If the export is train-only, it synthesizes `val` and `test` splits deterministically from the train pool.

That prevents the old failure mode where segmentation polygons were silently wrapped into coarse boxes and treated as clean detection labels.

## Workspace Layout

The scripts create and use a separate workspace root, for example:

```text
D:\downloads\SeniorProject\rdd_workspace
├── configs\
│   ├── dataset.yaml
│   └── ensemble.generated.yaml
├── data\
│   ├── raw_roboflow\
│   ├── train\images
│   ├── train\labels
│   ├── val\images
│   ├── val\labels
│   ├── test\images
│   └── test\labels
├── weights\pretrained\
├── runs\
└── artifacts\
    ├── prep\
    ├── evaluation\
    ├── reporting\
    └── training_manifest.json
```

## Install

Create a clean environment first.

```powershell
cd D:\downloads\SeniorProject\Skylink2
python -m venv .venv-training
.\.venv-training\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r training_pilot\requirements-guide.txt
```

Optional but recommended for live graphs:

```powershell
yolo settings tensorboard=True
```

MLflow uses environment variables. A simple local setup is:

```powershell
$env:MLFLOW_TRACKING_URI = "file:///D:/downloads/SeniorProject/rdd_workspace/artifacts/mlflow"
```

## Prepare Data

Use a clean workspace outside the repo root so runs and weights are isolated.

### Recommended path: true detection export from Roboflow

Before export in Roboflow:

1. Merge all classes into one class named `damage`
2. Export as YOLO object detection, not segmentation and not OBB

Then run:

```powershell
python training_pilot\prepare_one_class_detection_dataset.py `
  --zip "D:\downloads\My First Project.yolov8.zip" `
  --workspace "D:\downloads\SeniorProject\rdd_workspace"
```

### Fallback path: segmentation export with explicit lossy conversion

Only use this if Roboflow cannot provide a true detection export.

```powershell
python training_pilot\prepare_one_class_detection_dataset.py `
  --zip "D:\downloads\My First Project.yolov8 (1).zip" `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --allow-segmentation-to-box
```

After prep, inspect:

- `...\artifacts\prep\dataset_stats.json`
- `...\artifacts\prep\suspicious_boxes.json`
- `...\artifacts\prep\split_manifest.json`
- `...\artifacts\prep\duplicate_report.json`
- `...\artifacts\prep\DATASET_CARD.md`
- `...\artifacts\prep\qa_samples\`

If the suspicious boxes look bad, do not train. Fix the export first.

The prep step now also:

- preserves positive and negative balance when it synthesizes splits
- computes a dataset fingerprint
- checks for exact duplicate images across splits

## Download Guide Weights

```powershell
python training_pilot\download_guide_weights.py --workspace "D:\downloads\SeniorProject\rdd_workspace"
```

This fetches:

- `weights\pretrained\yolo12s_rdd2022.pt`
- `weights\pretrained\yolov8l.pt`
- `weights\pretrained\yolov8m.pt`
- `weights\pretrained\yolov8s.pt`

## Train One Model

Example:

```powershell
python training_pilot\train_from_guide_config.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --config "configs\models\yolo12s_finetune.yaml" `
  --device 0
```

Dry run first if you want to inspect resolved paths and arguments:

```powershell
python training_pilot\train_from_guide_config.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --config "configs\models\yolov8m_finetune.yaml" `
  --device 0 `
  --dry-run
```

Useful experiment overrides without editing YAML:

```powershell
python training_pilot\train_from_guide_config.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --config "configs\models\yolov8m_finetune.yaml" `
  --device 0 `
  --cache ram `
  --fraction 0.25 `
  --batch-auto `
  --multi-scale `
  --enable-mlflow `
  --enable-tensorboard `
  --run-tag "smoke_tune_round_1"
```

Each run now writes:

- `config_snapshot.yaml`
- `run_metadata.json`

inside the run directory before and after training.

The trainer now also validates the one-class contract before every run:

- `nc: 1`
- class name `damage`
- existing train, val, and test paths

and defaults `single_cls=True`, `close_mosaic=10`, `save=True`, and `val=True` unless a config explicitly overrides them.

## Train The Guide Stack

This uses the guide-aligned lineup:

- `yolo12s_custom`
- `yolov8l_custom`
- `yolov8m_custom`
- `obc_yolov8_custom` (optional external dependency)
- `yolov8s_diverse`

Run all non-optional models:

```powershell
python training_pilot\run_guide_training.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --device 0 `
  --clear-manifest
```

Run a subset:

```powershell
python training_pilot\run_guide_training.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --device 0 `
  --only yolo12s_custom `
  --only yolov8m_custom
```

Include the guide's optional OBC trainer if you cloned that repo into `rdd_workspace\external\OBC-YOLOv8`:

```powershell
python training_pilot\run_guide_training.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --device 0 `
  --include-optional
```

## Live Monitoring

TensorBoard:

```powershell
tensorboard --logdir "D:\downloads\SeniorProject\rdd_workspace\runs"
```

MLflow UI:

```powershell
mlflow ui --backend-store-uri "D:\downloads\SeniorProject\rdd_workspace\artifacts\mlflow"
```

Guide expectations to monitor during training:

- `results.csv` exists for every completed run
- `best.pt` and `last.pt` exist
- train and val box loss both trend down without val divergence
- recall and `mAP50` flatten before patience triggers

## Evaluate

Validation metrics and WBF weight generation:

```powershell
python training_pilot\evaluate_guide_models.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --split val `
  --device 0
```

This writes:

- `artifacts\evaluation\val_metrics.json`
- `artifacts\evaluation\val_metrics.csv`
- `configs\ensemble.generated.yaml`

The evaluation output also includes:

- `f1`
- `fitness`
- `tp`, `fp`, `fn` when Ultralytics exposes them
- `detection_accuracy = TP / (TP + FP + FN)` when available
- per-run inference time

Test metrics:

```powershell
python training_pilot\evaluate_guide_models.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --split test `
  --device 0
```

## Generate Training Curves

```powershell
python training_pilot\plot_guide_training_curves.py --workspace "D:\downloads\SeniorProject\rdd_workspace"
```

Outputs:

- `artifacts\reporting\training_curves.png`
- `artifacts\reporting\training_curve_summary.json`

The curve summary now reports both:

- best validation epoch by `mAP50`
- final epoch metrics

## K-Fold Cross Validation

For a small dataset, use K-fold when selecting which base configuration deserves full training.

This script keeps the workspace `test` split fixed and builds stratified folds from the combined `train` + `val` pool.

```powershell
python training_pilot\build_kfold_splits.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --n-splits 5 `
  --seed 42
```

Outputs land in:

- `artifacts\kfold\manifest.json`
- `artifacts\kfold\fold_01\dataset.yaml`
- `artifacts\kfold\fold_01\summary.json`

Train one guide config across those folds:

```powershell
python training_pilot\run_kfold_training.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --config "configs\models\yolov8m_finetune.yaml" `
  --device 0 `
  --project-override runs_kfold `
  --enable-mlflow `
  --enable-tensorboard
```

Then summarize the fold results:

```powershell
python training_pilot\summarize_kfold_results.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace"
```

This writes:

- `artifacts\kfold\training_manifest.json`
- `artifacts\kfold\reporting\kfold_per_fold.csv`
- `artifacts\kfold\reporting\kfold_aggregate.csv`
- `artifacts\kfold\reporting\kfold_summary.json`

## Hyperparameter Tuning

Use tuning only after the dataset and baseline config are stable.

The tuning entrypoint uses Ultralytics `model.tune()` with a constrained small-dataset search space:

```powershell
python training_pilot\tune_guide_model.py `
  --workspace "D:\downloads\SeniorProject\rdd_workspace" `
  --config "configs\models\yolov8m_finetune.yaml" `
  --device 0 `
  --iterations 30 `
  --epochs 40 `
  --enable-mlflow `
  --enable-tensorboard
```

Search space file:

- `training_pilot\configs\tuning\small_dataset_search_space.yaml`

Use tuning outputs only as candidate improvements. Do not treat a short tuning run as final evidence.

## Notes On The Current Roboflow Zip

The file `D:\downloads\My First Project.yolov8 (1).zip` is still segmentation-style YOLO, not plain detection.

That means:

- it is not OBB
- it is not ready for direct detect fine-tuning on your fixed pretrained detect models
- it must either be re-exported as object detection or converted deliberately with `--allow-segmentation-to-box`

For this project, the preferred path is still:

1. merge everything to one class `damage`
2. export as standard YOLO detection
3. train the guide configs on that export

## Where The Guide Configs Live

- [yolo12s_finetune.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\models\yolo12s_finetune.yaml)
- [yolov8l_finetune.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\models\yolov8l_finetune.yaml)
- [yolov8m_finetune.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\models\yolov8m_finetune.yaml)
- [obc_yolov8_finetune.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\models\obc_yolov8_finetune.yaml)
- [yolov8s_diverse.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\models\yolov8s_diverse.yaml)
- [guide_v2_single_class.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\model_sets\guide_v2_single_class.yaml)
- [dataset.template.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\dataset.template.yaml)
- [ensemble.template.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\ensemble.template.yaml)
- [small_dataset_search_space.yaml](D:\downloads\SeniorProject\Skylink2\training_pilot\configs\tuning\small_dataset_search_space.yaml)
