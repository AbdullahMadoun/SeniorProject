# Docker to Vast Experiment - Change Documentation

## Metadata
- Branch target: `docker-to-vast-experiment`
- Base branch at start: `feature/companion-hardware-layer`
- Documentation date: 2026-04-12
- Commit intent: experiment branch only (no push to `main`)

## Why these changes were made
This experiment introduces an end-to-end path from local/backend Docker deployment to automated remote model provisioning on Vast.ai, while keeping a safe fallback to static model endpoints and SSH-managed remote hosts.

## High-level summary
- Added a managed remote-model orchestrator in the backend bridge (`ssh` and `vastai` providers).
- Added runtime tunnel/model-state propagation from backend to frontend.
- Added backend and model-server deployment pipelines (container, remote bootstrap scripts, compose files, publishing scripts).
- Added model server startup toggles for YOLO-only validation and first-run model prefetch.
- Added test coverage for offer selection and managed remote environment rendering.
- Added HITL and safety simulation scripts/docs under `autonomy/`.
- Added a training pilot toolkit under `training_pilot/` for dataset conversion, augmentation, benchmarking, evaluation, and status reporting.
- Hardened `.gitignore` to avoid committing local SSH private keys and transient runtime artifacts.

## File-by-file change log

### Repository safety and hygiene
- `M .gitignore`
  - Added ignore rules for local deploy SSH key material and local transient artifacts:
    - `deploy/backend/ssh/id_ed25519`
    - `deploy/backend/ssh/id_ed25519.pub`
    - `companion_video_logger/*.npy`
    - `companion_video_logger/*.csv`
    - `diff_check_utf8.patch`
- `A .dockerignore`
  - Added root Docker build ignore rules for venv/cache/vendor/artifacts and runtime-heavy folders.

### Backend bridge + frontend runtime integration (`app/`)
- `M app/.env.example`
  - Added full environment contract for:
    - bridge runtime/tunnel options,
    - remote model autostart,
    - SSH-managed remote model settings,
    - Vast.ai leasing constraints.
- `M app/Dockerfile`
  - Added containerization for bridge with:
    - `cloudflared`, `openssh-client`, and required runtime tools,
    - backend requirements install,
    - bundled `model_server` and remote bootstrap scripts,
    - healthcheck and runtime data directory.
- `A app/.dockerignore`
  - Added app-scoped Docker ignore rules.
- `A app/requirements-backend.txt`
  - Added minimal backend runtime dependencies (`fastapi`, `uvicorn`, `httpx`, `python-dotenv`).
- `M app/src/server.py`
  - Added Cloudflare tunnel lifecycle tracking.
  - Added managed remote model startup integration via `ManagedRemoteModelState`.
  - Added runtime config synthesis endpoint (`/api/runtime-config`) and dynamic `/config.js` generation.
  - Added forwarding logic for `/api/analyze` with bridge/direct model resolution.
  - Added bridge health/state exposure and history persistence flow.
- `A app/src/managed_remote_model.py`
  - Added managed orchestration for remote model startup.
  - Supports `ssh` and `vastai` providers.
  - Implements Vast offer search/selection, instance provisioning, SSH readiness polling, bundle sync, and remote bootstrap execution.
  - Persists remote status/log/tail and masked key state for UI/runtime config.
- `A app/src/remote_model_helpers.py`
  - Added helpers for:
    - Vast offer normalization/selection,
    - instance normalization,
    - frontend connection strategy resolution (direct vs bridge proxy).
- `M app/src/static/config.js`
  - Added expanded runtime config defaults for bridge/tunnel/model state.
- `M app/src/static/index.html`
  - Added runtime gateway status panel in the scan UI.
- `M app/src/static/script.js`
  - Added runtime-config polling and UI synchronization.
  - Added dynamic routing between bridge proxy and direct model endpoint.
  - Added richer model/tunnel/key status handling and history bridge integration.
- `M app/src/static/styles.css`
  - Added styling for runtime gateway card, status colors, and error blocks.

### Dashboard artifact update
- `M artifacts/dashboard/index.html`
  - Updated dashboard HTML output to align with current runtime/safety visualization behavior.

### Model server runtime (`model_server/`)
- `M model_server/config.py`
  - Added env-driven toggles for `ENABLE_VLM` and `ENABLE_YOLO_V8`.
- `M model_server/main.py`
  - Added conditional VLM loading and YOLO-only fallback report generation.
  - Added startup/runtime behavior for deployments that skip VLM.
  - Extended health response with loaded-model state flags.
- `M model_server/run.sh`
  - Added `.env` loading and normalized env defaults for deployment use.
- `A model_server/prefetch_models.py`
  - Added optional prefetch utility for VLM/YOLO artifacts.
- `A model_server/requirements-yolo.txt`
  - Added reduced dependency set for YOLO-only server mode.

### Deployment tooling (`deploy/` + compose)
- `A docker-compose.backend.yml`
  - Added local backend compose stack with full bridge/remote/Vast env surface and persisted volume.
- `A deploy/backend/README.md`
  - Added backend container deployment guide and remote deployment flow.
- `A deploy/backend/publish.ps1`
  - Added image build/push automation for backend.
- `A deploy/backend/deploy_remote.ps1`
  - Added remote deployment automation for backend container stack.
- `A deploy/backend/docker-compose.server.yml`
  - Added server-side compose template for backend runtime.
- `A deploy/backend/ssh/.gitkeep`
  - Added placeholder for SSH directory structure.
- `A deploy/model_server/README.md`
  - Added remote model-server deployment guide.
- `A deploy/model_server/deploy_remote.ps1`
  - Added model-server SSH deployment utility.
- `A deploy/model_server/bootstrap_remote.sh`
  - Added remote bootstrap script (install, prefetch, start, tunnel, status, stop).

### Autonomy HITL + safety additions
- `A autonomy/docs/HITL_SETUP_GUIDE.md`
  - Added setup guide for Pixhawk HITL with Gazebo bridge/testing path.
- `A autonomy/scripts/configure_pixhawk_hitl.py`
  - Added Pixhawk HITL parameter configuration utility.
- `A autonomy/scripts/probe_pixhawk_sensors.py`
  - Added non-destructive sensor/telemetry probe tool.
- `A autonomy/scripts/px4_gazebo_bridge.py`
  - Added MAVLink serial<->UDP bridge utility for HITL.
- `A autonomy/scripts/safety_dashboard_server.py`
  - Added REST/SSE safety dashboard backend server.
- `A autonomy/scripts/safety_scenario_server.py`
  - Added real-time safety scenario visualization server.
- `A autonomy/scripts/safety_scenario_simulator.py`
  - Added safety scenario simulator for battery/wind/RTL cases.
- `A autonomy/scripts/test_mavlink_connection.py`
  - Added quick MAVLink connectivity test script.
- `A autonomy/scripts/test_waypoint_mission.py`
  - Added waypoint upload/monitor test script.

### Test coverage
- `A tests/test_managed_remote_model.py`
  - Added managed remote model tests (Vast key prerequisite and env rendering).
- `A tests/test_remote_model_helpers.py`
  - Added helper tests for offer selection and frontend routing resolution.

### Training pilot workflow (`training_pilot/`)
- `A training_pilot/RESUME_HERE.md`
  - Added experiment state, remote environment, and continuation notes.
- `A training_pilot/SeniorProject.code-workspace`
  - Added workspace convenience file.
- `A training_pilot/augment_detection_dataset.py`
  - Added offline augmentation utility for YOLO detection data.
- `A training_pilot/build_benchmark_report.py`
  - Added benchmark plots/report generation utility.
- `A training_pilot/convert_segmentation_zip_to_detection.py`
  - Added segmentation-to-single-class detection conversion utility.
- `A training_pilot/evaluate_damage_coverage.py`
  - Added custom coverage and exact-match evaluator.
- `A training_pilot/evaluate_frozen_grounding_clip.py`
  - Added frozen GroundingDINO+CLIP evaluator.
- `A training_pilot/evaluate_model_ensemble.py`
  - Added WBF ensemble evaluator.
- `A training_pilot/run_selected_continuation.py`
  - Added selected-run continuation trainer.
- `A training_pilot/run_three_model_benchmark.py`
  - Added 3-model benchmark training script.
- `A training_pilot/run_two_model_pilot.py`
  - Added conservative 2-model pilot trainer.
- `A training_pilot/run_yolov8s_diverse.py`
  - Added YOLOv8s diverse-branch trainer.
- `A training_pilot/status_report.md`
  - Added current training status snapshot.
- `A training_pilot/update_status_report.py`
  - Added status report generation utility.

## Diff statistics (tracked files)
- `.gitignore`: `+5/-0`
- `app/.env.example`: `+49/-0`
- `app/Dockerfile`: `+22/-10`
- `app/src/server.py`: `+325/-15`
- `app/src/static/config.js`: `+19/-3`
- `app/src/static/index.html`: `+46/-12`
- `app/src/static/script.js`: `+261/-118`
- `app/src/static/styles.css`: `+66/-6`
- `artifacts/dashboard/index.html`: `+157/-2`
- `model_server/config.py`: `+10/-3`
- `model_server/main.py`: `+157/-93`
- `model_server/run.sh`: `+14/-3`

## Validation run
Executed locally:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Result: `Ran 6 tests ... OK`

## Explicitly excluded from commit/push
These remained local by design and were not included in the branch commit:
- `deploy/backend/ssh/id_ed25519`
- `deploy/backend/ssh/id_ed25519.pub`
- `companion_video_logger/latest_frame.jpg.npy`
- `companion_video_logger/telemetry_log.csv`
- `diff_check_utf8.patch`

Reason: local secrets and transient/generated artifacts should not be versioned in this experiment branch.
