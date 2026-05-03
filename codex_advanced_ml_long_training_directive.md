# Academic ML Lifecycle Directive for Codex

You are the Lead ML Engineer. Your mandate is to execute a **Long Training Cycle** and document it precisely using standard academic Machine Learning frameworks. We are bypassing naive local artifacts and switching to professional MLOps tooling.

## 1. Professional MLOps Logging Frameworks (Required)
Researchers do not rely on manually finding `results.csv`. You must integrate established MLOps dashboards so that Train vs Validation loss curves, Precision-Recall curves, and hyperparameter states are automatically managed.
- **Action:** Install `wandb` (Weights & Biases) and `tensorboard` inside the training environment before starting. 
  ```bash
  pip install wandb tensorboard clearml
  ```
- **Ultralytics Native Hook:** YOLO automatically detects `wandb` and `tensorboard` if they are installed. It will automatically log overlayed `train/box_loss` vs `val/box_loss` curves dynamically. You must enable this during the `YOLO().train()` call.

## 2. Dataset Scope (Train on ALL 2,000+ Images)
The previous runs were limited to the tiny 149-image zip file. This is unacceptable for an academic evaluation. You MUST train on the entire Kaggle dataset.
- **Action:** Execute the dataset download from your previous `MAX_RECALL_VAST_SETUP.md` scripts.
  ```bash
  kaggle datasets download -d lorenzoarcioni/road-damage-dataset-potholes-cracks-and-manholes -p data/raw
  ```

## 3. HARSH Pre-Flight Tests (One-Shot Safety Checks)
The Senior Project is due tomorrow. We have exactly ONE SHOT at this training cycle. If the dataset is corrupted, you will ruin the project. Before you even import ultralytics, you MUST write and execute a `harsh_dataset_audit.py` script that mathematically guarantees the following:
1. **Quantity Assert:** `assert len(train_images) > 1500`
2. **Data Leakage Assert:** Calculate the SHA-256 hash of every single image in `train/` and compare it against `val/` and `test/`. If a single hash overlaps, **CRASH THE SCRIPT**. Leakage will invalidate the entire project.
3. **Label Health Assert:** Parse every `.txt` YOLO label file. If any bounding box coordinate is `< 0.0` or `> 1.0`, **CRASH THE SCRIPT**.
4. **Corrupted Image Assert:** Use `cv2.imread()` or PIL to open every single image. If any image returns a NoneType or Exception, delete it and its label.

Do NOT run `YOLO().train()` until `harsh_dataset_audit.py` outputs `[PASS] ALL CHECKS CLEARED`.

## 4. Advanced Training Hyperparameters (Do NOT Skip)
When invoking Ultralytics YOLO (`YOLO().train(...)`), you must enforce:
- `epochs=500`: Allow the model extremely long horizons to converge. 
- `patience=50`: **Early Stopping Constraint**. Let the system automatically halt training if `mAP50-95` on the validation set fails to improve for 50 straight epochs. This solves overfitting physically.
- `save=True`, `save_period=10`: Checkpoint the network frequently so rolling back is possible.
- `plots=True`: Instructs the backend to actively generate high-resolution PNGs of confusion matrices, F1, and PR-Curves.

## 3. The Academic Evaluation Report
You must not just say "training completed." You must author a `ACADEMIC_ML_EVALUATION.md` report locally after training halts that mimics a research paper:
1. **Convergence Analysis:** Include the exact epoch number where Early Stopping triggered. Did the model naturally plateau or forcibly stop?
2. **Train vs Validation Loss:** Generate or link an explicit graph (via Matplotlib or Wandb) mapping `train_loss` vs `val_loss`. Explain if there was variance/overfitting.
3. **Metric Extraction:** Read the final lines of `results.csv` and report the absolute peak `mAP50-95`. 

## 4. State Syncing
If training happens on the Vast.ai server, you must aggressively automate the rsync of the entire `/runs/detect/train` directory, including all `.png` files and W&B logs, back to the local `artifacts` folder. The user must be able to visually see the output curves without SSHing themselves.
