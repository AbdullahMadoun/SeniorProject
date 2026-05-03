# Resume State for Skylink RDD Ensemble

## Current Goal
- Maximize detection recall for road-damage instances using the **4-YOLO ensemble only**.
- Do **not** use the frozen GroundingDINO+CLIP member.
- Communicate and track results like an ML engineer: validation curves, recall-oriented metrics, and ensemble-vs-single comparisons.
- Main optimization target is not generic classification accuracy.
- The practical objective is: detect every real damage instance in the image with as few misses as possible.

## Current Dataset Contract
- Source export: `D:\downloads\SeniorProject\My First Project.yolov8.zip`
- Original project type: segmentation
- Local conversion already done on the remote host:
  - polygons converted to axis-aligned YOLO detection boxes
  - classes merged to single class: `damage`
  - split: `train/val/test = 149/18/20`
  - negatives kept: `21`
  - no split overlap detected
- No leakage observed at the file level between train/val/test.
- Important caveat: random split means there can still be semantic similarity between images if the source had near-duplicates. No exact overlap was found.
- Conversion policy used:
  - keep empty-label images as negatives
  - keep labels in standard YOLO detection format only
  - do not use OBB for this pipeline
  - do not keep the original subtype classes for training

## Remote Compute
- Vast instance id: `34615752`
- Label: `skylink-rdd-ensemble-4090`
- Host: `ssh9.vast.ai`
- SSH port: `15752`
- GPU: `RTX 4090`
- VRAM: `24 GB`
- Remote workspace: `/opt/skylink-rdd-ensemble`
- Training logs: `/opt/skylink-rdd-ensemble/logs`
- Dataset workspace: `/opt/skylink-rdd-ensemble/workspace`
- Docker: not required for this run
- Access method that worked:
  - `ssh -T -i D:\downloads\SeniorProject\Skylink2\deploy\backend\ssh\id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 15752 root@ssh9.vast.ai`
- Host health at last check:
  - GPU idle/low use before training reruns
  - CUDA available in the remote Python env
  - no Docker dependency required

## Models In Scope
Use only these 4 trainable YOLO members:
- `yolo12s_custom_benchmark`
- `yolov8l_custom_benchmark`
- `yolov8m_custom_benchmark`
- `yolov8s_diverse`
- The frozen CLIP/GroundingDINO member was explicitly excluded from the active comparison.

## Validation Metrics to Track
Standard detection metrics:
- `precision`
- `recall`
- `mAP@0.5`
- `mAP@0.5:0.95`

User-defined objective:
- `damage_coverage_recall` = fraction of GT damage instances matched
- `all_damages_found_image_rate` = fraction of images where all GT damages were found
- `exact_image_match_rate` = strictest metric, often low
- Reporting priority:
  1. `damage_coverage_recall`
  2. `all_damages_found_image_rate`
  3. `exact_image_match_rate`
  4. standard YOLO metrics for model comparison and sanity checks

## Current Results

### Best Single Model on Validation
- `yolov8m_custom_benchmark`
  - `precision = 0.50622`
  - `recall = 0.53226`
  - `mAP@0.5 = 0.51848`
  - `damage_coverage_recall = 0.6612903225806451`
  - `all_damages_found_image_rate = 0.4444444444444444`
  - `exact_image_match_rate = 0.16666666666666666`

### Other Single Models on Validation
- `yolo12s_custom_benchmark`
  - `precision = 0.67576`
  - `recall = 0.35484`
  - `mAP@0.5 = 0.4087`
  - `damage_coverage_recall = 0.5483870967741935`
  - `all_damages_found_image_rate = 0.3888888888888889`
  - `exact_image_match_rate = 0.05555555555555555`

- `yolov8l_custom_benchmark`
  - `precision = 0.60208`
  - `recall = 0.38710`
  - `mAP@0.5 = 0.49669`
  - `damage_coverage_recall = 0.5967741935483871`
  - `all_damages_found_image_rate = 0.3888888888888889`
  - `exact_image_match_rate = 0.1111111111111111`

- `yolov8s_diverse`
  - `precision = 0.256`
  - `recall = 0.371`
  - `mAP@0.5 = 0.258`
  - `mAP@0.5:0.95 = 0.104`
  - `damage_coverage_recall = 0.6290322580645161`
  - `all_damages_found_image_rate = 0.4444444444444444`
  - `exact_image_match_rate = 0.0`

### Best 4-YOLO Ensemble on Validation
- Heavy multi-scale + flip TTA ensemble:
  - `damage_coverage_recall = 0.8870967741935484`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `exact_image_match_rate = 0.0`
  - `total_predictions = 785`
- Practical weighted-fusion baseline:
  - `damage_coverage_recall = 0.8064516129032258`
  - `all_damages_found_image_rate = 0.5`
  - `exact_image_match_rate = 0.0`
- Interpretation:
  - ensemble improves recall materially over the best single model
  - ensemble does not currently improve strict exact-match behavior
  - if the user wants "do not miss damages", the ensemble is the correct direction
  - if the user wants exact count match, thresholds and fusion need more tuning

## Interpretation
- The ensemble **does help** for the user-defined recall objective.
- Current best single-model exactness is still better than the ensemble on strict match, but the ensemble wins on finding all damages.
- If the user-defined priority is "do not miss any damages," the ensemble is currently the right direction.
- If the priority becomes exact-image-match, the pipeline needs threshold/fusion tuning, not more model count alone.

## Leakage Status
- No file-level leakage detected between `train`, `val`, and `test`.
- Training and evaluation were run against the proper split contract, not against the same data.
- Remaining risk is only semantic similarity from random splitting if the original dataset had near-duplicate frames.
- Practical takeaway:
  - there is no evidence of exact split leakage
  - there is still a nonzero risk of correlated frames if the original source had bursts or near-duplicates
  - nothing indicates the validation metrics are being inflated by reuse of the same files

## What Was Already Done
- Reused the Vast host instead of creating a new one.
- Set up a remote training workspace at `/opt/skylink-rdd-ensemble`.
- Installed the training dependencies on the host Python environment.
- Converted the segmentation export into detection format locally on the remote host.
- Ran augmentation on the train split only.
- Trained the 4 YOLO models.
- Evaluated individual models and the 4-YOLO ensemble on validation.
- Important remote artifacts:
  - dataset root: `/opt/skylink-rdd-ensemble/workspace/dataset`
  - model runs: `/opt/skylink-rdd-ensemble/workspace/runs_benchmark/*`
  - logs: `/opt/skylink-rdd-ensemble/logs/*`
  - coverage outputs: `/opt/skylink-rdd-ensemble/workspace/artifacts/*.json`
- Known useful scripts:
  - `training_pilot/convert_segmentation_zip_to_detection.py`
  - `training_pilot/augment_detection_dataset.py`
  - `training_pilot/run_three_model_benchmark.py`
  - `training_pilot/run_yolov8s_diverse.py`
  - `training_pilot/evaluate_damage_coverage.py`
  - `training_pilot/evaluate_model_ensemble.py`

## What Not To Do
- Do not reintroduce Qwen into this path.
- Do not use oriented bounding boxes for this pipeline.
- Do not evaluate on train and call it accuracy.
- Do not count the frozen GroundingDINO+CLIP member in the current ensemble comparison.
- Do not treat `mAP` as the only success criterion here; it is secondary to missed-damage reduction.
- Do not re-split the dataset without checking for overlap first.
- Do not compare a train metric against a validation metric and call it progress.

## Next Steps
1. Generate YOLO-style training graphs from the saved `results.csv` files:
   - box loss vs epoch
   - precision vs epoch
   - recall vs epoch
   - `mAP@0.5` vs epoch
   - `mAP@0.5:0.95` vs epoch
2. Produce a clean ensemble-vs-single comparison table on validation.
3. If needed, run the 4-YOLO ensemble on the untouched `test` split only after validation reporting is finished.
4. Keep the output framed around recall and image-level full-coverage, since that matches the user-defined metric.
5. If the user wants a final “best model” answer, report both:
   - the best single model by `damage_coverage_recall`
   - the best 4-YOLO ensemble by the same metric

## Remote Commands Previously Used
These are the key commands that established the current state:

```powershell
ssh -T -i D:\downloads\SeniorProject\Skylink2\deploy\backend\ssh\id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 15752 root@ssh9.vast.ai
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/convert_segmentation_zip_to_detection.py --zip /opt/skylink-rdd-ensemble/data/raw_export.zip --workspace /opt/skylink-rdd-ensemble/workspace --seed 42 --qa-samples 12
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/augment_detection_dataset.py --dataset-root /opt/skylink-rdd-ensemble/workspace/dataset --seed 42
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/run_three_model_benchmark.py --workspace /opt/skylink-rdd-ensemble/workspace --data /opt/skylink-rdd-ensemble/workspace/dataset/data.yaml --device 0 --epochs 8 --imgsz 640 --workers 4
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/run_yolov8s_diverse.py --workspace /opt/skylink-rdd-ensemble/workspace --data /opt/skylink-rdd-ensemble/workspace/dataset/data.yaml --device 0 --epochs 8 --imgsz 640 --workers 4
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/evaluate_damage_coverage.py --dataset-root /opt/skylink-rdd-ensemble/workspace/dataset --split val --device 0 --model /path/to/model.pt
```

```bash
/opt/skylink-rdd-ensemble/venv/bin/python /opt/skylink-rdd-ensemble/training_pilot/evaluate_model_ensemble.py --dataset-root /opt/skylink-rdd-ensemble/workspace/dataset --split val --device 0 --tta --yolo-model /path/to/yolo12s.pt --yolo-model /path/to/yolov8l.pt --yolo-model /path/to/yolov8m.pt --yolo-model /path/to/yolov8s.pt
```

## Resume Checklist
Before doing anything new:
1. Confirm the remote instance is still up.
2. Confirm the remote workspace still exists.
3. Confirm the four model `best.pt` files are still present.
4. Confirm the validation and test split folders are still intact.
5. Regenerate plots from `results.csv` if the user asks for graphs.
6. Evaluate the 4-YOLO ensemble on `test` only if validation reporting is complete.

## Notes for the Next Session
- The current state is already past “dataset salvage” and into “model comparison”.
- The most important open question is not whether the pipeline works; it does.
- The next meaningful question is whether additional threshold/fusion tuning can raise strict exact-image-match without sacrificing recall too much.
- If the user asks for a summary, say the ensemble is currently better for finding all damages, while the best single model is still better on strict exact-match.

## Latest Continuation Update (2026-04-11)

### Remote Verification
- The Vast instance was confirmed alive again.
- The remote workspace still exists at `/opt/skylink-rdd-ensemble/workspace`.
- All four original benchmark checkpoints were still present.
- Validation and test split folders were still intact.

### Reporting Added
- A benchmark reporting script now exists locally at `training_pilot/build_benchmark_report.py`.
- It generates:
  - multi-model training curves from `results.csv`
  - single-model comparison CSVs
  - ensemble comparison CSVs
  - markdown summary report
- Remote report output path:
  - `/opt/skylink-rdd-ensemble/workspace/artifacts/reporting_val`

### Continuation Runs Performed
These were new runs from the saved `last.pt` checkpoints, not destructive overwrites of the original baselines:
- `yolov8m_custom_benchmark_plus8`
  - run dir: `/opt/skylink-rdd-ensemble/workspace/runs_benchmark/yolov8m_custom_benchmark_plus8`
- `yolov8s_diverse_plus8`
  - run dir: `/opt/skylink-rdd-ensemble/workspace/runs_benchmark/yolov8s_diverse_plus8`

### Validation Results After Continuation
- `yolov8m_custom_benchmark_plus8`
  - `damage_coverage_recall = 0.7096774193548387`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `exact_image_match_rate = 0.05555555555555555`
  - `total_predictions = 137`
- `yolov8s_diverse_plus8`
  - `damage_coverage_recall = 0.7096774193548387`
  - `all_damages_found_image_rate = 0.5555555555555556`
  - `exact_image_match_rate = 0.0`
  - `total_predictions = 354`

### Updated Ensemble Tuning On Validation
Using the old `skip_box_thr=0.1` settings with the new checkpoints reduced ensemble recall, so fusion was retuned on validation:
- `ensemble_4yolo_plus8_val_skip10.json`
  - `damage_coverage_recall = 0.7903225806451613`
  - `all_damages_found_image_rate = 0.6111111111111112`
  - `total_predictions = 346`
- `ensemble_4yolo_plus8_multiscale_val_skip10.json`
  - `damage_coverage_recall = 0.8387096774193549`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `total_predictions = 562`
- `ensemble_4yolo_plus8_multiscale_val_skip06.json`
  - `damage_coverage_recall = 0.8709677419354839`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `total_predictions = 914`
- `ensemble_4yolo_plus8_multiscale_val_skip08.json`
  - `damage_coverage_recall = 0.8709677419354839`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `total_predictions = 706`
- Best validation recall after continuation and tuning:
  - `ensemble_4yolo_plus8_multiscale_val_skip04.json`
  - `damage_coverage_recall = 0.9032258064516129`
  - `all_damages_found_image_rate = 0.6666666666666666`
  - `exact_image_match_rate = 0.0`
  - `total_predictions = 1089`

### Test Results After Continuation
Selection was still made on validation, then tested once:
- `yolov8m_custom_benchmark_plus8`
  - `damage_coverage_recall = 0.6417910447761194`
  - `all_damages_found_image_rate = 0.35`
  - `exact_image_match_rate = 0.05`
  - `total_predictions = 139`
- Final recall-first ensemble candidate:
  - `ensemble_4yolo_plus8_multiscale_test_skip04.json`
  - `damage_coverage_recall = 0.8805970149253731`
  - `all_damages_found_image_rate = 0.65`
  - `exact_image_match_rate = 0.0`
  - `total_predictions = 1242`

### Interpretation After Continuation
- The single-model continuation improved validation metrics but did not improve standalone test generalization.
- The ensemble did benefit from the continuation once fusion was retuned.
- Compared with the earlier best multiscale ensemble test run (`damage_coverage_recall = 0.835820895522388`), the tuned continued ensemble improved test recall to `0.8805970149253731`.
- For the stated recall-first objective, the current best overall result is now the tuned continued 4-YOLO multiscale ensemble.
- For a lower-prediction operating point, `skip_box_thr=0.08` is a useful tradeoff checkpoint, but it is not the top recall configuration.

### Current Best Answer
- Best single model by validation recall:
  - `yolov8m_custom_benchmark_plus8`
- Best single model observed on test among evaluated singles:
  - original `yolov8m_custom_benchmark`
- Best overall recall-first system:
  - `ensemble_4yolo_plus8_multiscale_*_skip04`

### Recommended Next Step
- Do not spend more test unless a final locked candidate is needed for presentation.
- If more tuning is needed, do it on validation only:
  - ensemble weights
  - `wbf_skip_box_thr`
  - `yolo_conf`
- If the user asks for the final presentation answer, report:
  - the strongest single model separately
  - the tuned continued 4-YOLO ensemble as the best recall-first system
