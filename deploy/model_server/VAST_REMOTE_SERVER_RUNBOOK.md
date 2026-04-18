# Vast Remote Server Runbook

This is the repeatable remote-only path for the current `model_server` deployment.

Scope:

- remote GPU host on Vast.ai
- Docker VM deployment
- ensemble detector first
- optional VLM mode:
  - `local`: run Qwen on the same remote GPU
  - `api`: keep the ensemble on Vast and call an external VLM API

## What Must Exist Locally

- `model_server/`
- `deploy/model_server/`
- `training_pilot/weights/rdd_trained_local/`

Optional but supported:

- `external/yolov12/`

If `external/yolov12/` is missing, the remote bootstrap clones the YOLO12 fork from:

- `https://github.com/sunsmarterjie/yolov12.git`

## Why YOLO12 Previously Failed

The `rezzzq` ensemble member cannot be loaded reliably by a plain stock Ultralytics install.

The remote bootstrap now handles this explicitly:

1. install base server requirements
2. clone or use a bundled YOLO12 fork
3. patch the broken local `flash_attn` wheel reference
4. apply the flash-attention fallback patch
5. install the fork in editable mode on the remote host or in the Docker image

Without that sequence, the remote server can degrade to the weaker YOLOv8-only subset.

## Remote Environment Contract

Minimum important variables:

```env
REMOTE_DEPLOY_MODE=docker_vm
DETECTOR_MODE=ensemble
ENSEMBLE_ENABLED=true
ENSEMBLE_MEMBERS=rezzzq_yolo12s_rdd2022,ozair_yolov8_rdd2022,oracl4_yolov8_rdd2022
ENSEMBLE_MODEL_REZZZQ=/opt/skylink-model-server/training_pilot/weights/rdd_trained_local/yolo12s_rezzzq_v5align/best.pt
ENSEMBLE_MODEL_OZAIR=/opt/skylink-model-server/training_pilot/weights/rdd_trained_local/ozair_yolov8_custom/best.pt
ENSEMBLE_MODEL_ORACL4=/opt/skylink-model-server/training_pilot/weights/rdd_trained_local/oracl4_yolov8_custom/best.pt
YOLO12_REPO_DIR=/opt/skylink-model-server/external/yolov12
YOLO12_REPO_URL=https://github.com/sunsmarterjie/yolov12.git
```

VLM mode selection:

```env
ENABLE_VLM=true
VLM_BACKEND=local
INSTALL_LOCAL_VLM=true
```

or

```env
ENABLE_VLM=true
VLM_BACKEND=api
INSTALL_LOCAL_VLM=false
VLM_API_URL=https://your-vlm-endpoint/analyze
VLM_API_KEY=...
```

`INSTALL_LOCAL_VLM=false` is important for API mode because it keeps the remote image on the lighter YOLO-side dependency set.

## One-Shot Deployment

From Windows PowerShell:

```powershell
.\deploy\model_server\deploy_remote.ps1 `
  -Server YOUR_SSH_HOST `
  -SshPort YOUR_SSH_PORT `
  -DeploymentMode docker_vm `
  -VlmBackend api `
  -BridgeEnvFile .\app\.env
```

The deploy script now uploads:

- `model_server/`
- `deploy/model_server/`
- `training_pilot/weights/`
- optional bundled `external/yolov12/`

## Health Checks

On the remote host:

```bash
ROOT_DIR=/opt/skylink-model-server /opt/skylink-model-server/bootstrap_remote.sh status
curl -fsS http://127.0.0.1:17612/health
```

Expected:

- `status: ready`
- `detector_mode: ensemble`
- `ensemble_loaded: true`

If `rezzzq` is healthy, it should appear in the ensemble selection instead of failing at request time.

## Shutdown

To stop only the remote service and keep the VM:

```bash
ROOT_DIR=/opt/skylink-model-server /opt/skylink-model-server/bootstrap_remote.sh stop
```

To destroy the Vast contract completely:

```powershell
vastai destroy instance YOUR_INSTANCE_ID --api-key YOUR_VAST_API_KEY
```

## Before Destroying a Remote Training/Eval Box

Pull anything that does not already exist locally:

- prepared datasets
- remote-only logs
- generated artifacts not mirrored under `training_pilot/artifacts`

For the current datasyn/RDD experiment branch, the important prepared remote dataset path was:

```text
/root/SeniorProject/training_pilot/data/datasyn_rdd2022_retrain_50_20_30
```

If that tree already exists locally, the instance can be destroyed safely.

Current local state after cleanup:

- the prepared split is now mirrored locally at:
  - `training_pilot/data/datasyn_rdd2022_retrain_50_20_30`
- the earlier 3090 datasyn experiment contract `35137381` was destroyed on `2026-04-18`

## Current Caveat

This runbook fixes the remote bootstrap path in code, but the full remote smoke test still has to be re-run on a fresh Vast VM after recreation.
