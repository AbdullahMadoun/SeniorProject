## Backend Rewrite Resume

Date: 2026-04-17

### Goal

Continue the old full SkyLink server architecture:

- public bridge/frontend with Cloudflare tunnel and autostart
- remote Vast-hosted GPU backend
- detector first, then VLM
- replace the old single/dual YOLO detector with our ensemble
- allow `local` vs `api` VLM selection from the dashboard
- support image and video inference
- keep Supabase/mission persistence in the loop

### What Is Already Done

#### 1. Ensemble runtime is implemented inside `model_server`

Added:

- [model_server/ensemble_runtime.py](D:/downloads/SeniorProject/Skylink2/model_server/ensemble_runtime.py)
- [model_server/vlm_api_client.py](D:/downloads/SeniorProject/Skylink2/model_server/vlm_api_client.py)

Patched:

- [model_server/config.py](D:/downloads/SeniorProject/Skylink2/model_server/config.py)
- [model_server/main.py](D:/downloads/SeniorProject/Skylink2/model_server/main.py)
- [model_server/requirements.txt](D:/downloads/SeniorProject/Skylink2/model_server/requirements.txt)
- [model_server/requirements-yolo.txt](D:/downloads/SeniorProject/Skylink2/model_server/requirements-yolo.txt)

Current model-server behavior:

- active detector path is now ensemble-oriented
- detector output is returned before VLM
- request supports `vlm_mode`
- VLM can run either:
  - local Qwen
  - external API
  - disabled
- `/analyze` now returns:
  - `report.summary`
  - `report.boxes`
  - `report.report_markdown`
  - `report.annotated_image_b64`
  - `report.detector_debug`
- `/health` now reports detector/VLM mode and ensemble selection state

#### 2. Video frame extraction was improved

Patched:

- [app/src/video_extractor.py](D:/downloads/SeniorProject/Skylink2/app/src/video_extractor.py)

Added:

- perceptual near-duplicate removal using average-hash + Hamming distance
- configurable dedupe threshold
- CLI support for `--dedup-distance`

This sits on top of the existing kinematic overlap reduction logic.

#### 3. A reusable video analysis pipeline file exists

Added:

- [app/src/analyze_video_pipeline.py](D:/downloads/SeniorProject/Skylink2/app/src/analyze_video_pipeline.py)

This file currently supports:

- frame extraction from video
- per-frame backend inference
- optional Supabase persistence into:
  - `missions`
  - `mission_images`
  - `damage_detections`
- overlap control
- dedupe control

### Important Files Confirmed As The Correct Backend Surface

#### Public bridge / frontend side

- [deploy/backend](D:/downloads/SeniorProject/Skylink2/deploy/backend)
- [app/src/server.py](D:/downloads/SeniorProject/Skylink2/app/src/server.py)
- [app/src/static/index.html](D:/downloads/SeniorProject/Skylink2/app/src/static/index.html)
- [app/src/static/script.js](D:/downloads/SeniorProject/Skylink2/app/src/static/script.js)

#### Remote GPU inference side

- [model_server/main.py](D:/downloads/SeniorProject/Skylink2/model_server/main.py)
- [model_server/config.py](D:/downloads/SeniorProject/Skylink2/model_server/config.py)

#### Remote autostart / remote deployment side

- [app/src/managed_remote_model.py](D:/downloads/SeniorProject/Skylink2/app/src/managed_remote_model.py)
- [deploy/model_server/bootstrap_remote.sh](D:/downloads/SeniorProject/Skylink2/deploy/model_server/bootstrap_remote.sh)

### Trained RDD Weights Saved Locally

Curated local folder:

- [training_pilot/weights/rdd_trained_local](D:/downloads/SeniorProject/Skylink2/training_pilot/weights/rdd_trained_local)

Manifest:

- [training_pilot/weights/rdd_trained_local/MANIFEST.md](D:/downloads/SeniorProject/Skylink2/training_pilot/weights/rdd_trained_local/MANIFEST.md)

Recovered checkpoints present locally:

- `yolo12s_rezzzq_custom/best.pt`
- `yolo12s_rezzzq_v5align/best.pt`
- `ozair_yolov8_custom/best.pt`
- `oracl4_yolov8_custom/best.pt`

No recovered local trained `obc_yolov8_custom` checkpoint was found.

### What Is Not Finished

#### 1. Bridge/API integration is not finished

Not yet patched:

- [app/src/server.py](D:/downloads/SeniorProject/Skylink2/app/src/server.py)

Still missing there:

- `/api/analyze-video`
- processed video artifact serving
- explicit Supabase-backed mission/image/detection return path
- bridge-side wiring for `vlm_mode`
- inference result persistence path for the new UI

#### 2. Dashboard/UI integration is not finished

Not yet patched:

- [app/src/static/index.html](D:/downloads/SeniorProject/Skylink2/app/src/static/index.html)
- [app/src/static/script.js](D:/downloads/SeniorProject/Skylink2/app/src/static/script.js)

Still missing there:

- file input that handles both image and video cleanly
- VLM mode selector (`local` vs `api`)
- dedicated inference-results tab
- rendering of `annotated_image_b64`
- video frame gallery / selected-frame inspection
- fix for current JS bug: `hasBridge()` is called but not defined

#### 3. Vast VM Docker autostart is only partially patched

Touched but not validated:

- [deploy/model_server/bootstrap_remote.sh](D:/downloads/SeniorProject/Skylink2/deploy/model_server/bootstrap_remote.sh)

Current state:

- a partial `docker_vm` adaptation was started
- it adds Docker/Compose branches and status metadata
- it has **not** been validated end-to-end
- companion Docker assets under `deploy/model_server/` were **not** finished in this session
- [app/src/managed_remote_model.py](D:/downloads/SeniorProject/Skylink2/app/src/managed_remote_model.py) still uses the old host-native sync/bootstrap flow

### Key Risks / Caveats

#### Calibration mismatch

The ensemble config currently points at recovered trained weights under `training_pilot/weights/rdd_trained_local`, but the available calibration artifact came from the earlier datasyn selective-ensemble search:

- [training_pilot/artifacts/datasyn_calibrated_selective_ensemble_20260417_144734](D:/downloads/SeniorProject/Skylink2/training_pilot/artifacts/datasyn_calibrated_selective_ensemble_20260417_144734)

That means:

- selection summary is useful as a starting point
- calibration manifest is **not guaranteed valid** for the trained checkpoints now being loaded

If continuing immediately, either:

1. disable calibration manifest by default for backend runtime, or
2. re-fit calibration for the exact trained checkpoints that will serve production inference

#### UI is still old-contract oriented

The frontend still expects the older image-only path and local-history projection. It does not yet consume the richer `annotated_image_b64` and `detector_debug` contract.

#### No autonomy changes were applied

The autonomy instructions that appeared midstream were not implemented. This session stayed on the training/backend rewrite track.

### Database / API Shape Guidance Already Confirmed

From the Supabase/video inspection work:

- keep `POST /api/analyze` for single-image analysis
- keep `GET /api/history` and `POST /api/history` if the current dashboard history cards must keep working
- add mission-centric persistence centered on:
  - `missions`
  - `mission_images`
  - `damage_detections`
- add a dedicated video analysis route returning per-frame reports and persisted IDs

Canonical stored severity should be normalized as:

- `low`
- `medium`
- `high`

Map those to display labels only at the UI/read-model layer.

### Exact Next Steps

1. Finish [app/src/server.py](D:/downloads/SeniorProject/Skylink2/app/src/server.py)
   - add `/api/analyze-video`
   - mount `/processed_history`
   - call `analyze_video_session(...)`
   - persist annotated outputs and return frontend-friendly gallery payloads

2. Finish the dashboard
   - patch [app/src/static/index.html](D:/downloads/SeniorProject/Skylink2/app/src/static/index.html)
   - patch [app/src/static/script.js](D:/downloads/SeniorProject/Skylink2/app/src/static/script.js)
   - add:
     - image/video upload handling
     - VLM mode selector
     - inference tab
     - video frame gallery
     - detector debug rendering

3. Finish Vast VM Docker path
   - complete Docker assets under `deploy/model_server/`
   - patch [app/src/managed_remote_model.py](D:/downloads/SeniorProject/Skylink2/app/src/managed_remote_model.py) to:
     - use VM-capable Vast offers
     - upload model weights/artifacts needed for ensemble
     - bootstrap remote Docker-on-VM instead of host-native only

4. Revisit ensemble runtime defaults
   - likely disable old calibration manifest by default until recalibrated for the serving checkpoints

5. Validate locally
   - `python -m py_compile model_server/config.py model_server/ensemble_runtime.py model_server/vlm_api_client.py model_server/main.py`
   - `python -m py_compile app/src/video_extractor.py app/src/analyze_video_pipeline.py`
   - then run relevant tests for `analyze_video_pipeline`

### Working Tree Snapshot At Wrap-Up

Modified:

- `app/src/video_extractor.py`
- `deploy/model_server/bootstrap_remote.sh`
- `model_server/config.py`
- `model_server/main.py`
- `model_server/requirements-yolo.txt`
- `model_server/requirements.txt`

Untracked but relevant:

- `app/src/analyze_video_pipeline.py`
- `app/src/tests/test_analyze_video_pipeline.py`
- `model_server/ensemble_runtime.py`
- `model_server/vlm_api_client.py`
- `training_pilot/weights/`
- `training_pilot/artifacts/datasyn_calibrated_selective_ensemble_20260417_144734/`

Not yet touched in this backend rewrite:

- `app/src/server.py`
- `app/src/static/index.html`
- `app/src/static/script.js`
- `app/src/managed_remote_model.py`

