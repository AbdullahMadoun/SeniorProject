# Vast Remote Server Runbook

This is the repeatable remote-only path for the current `model_server` deployment.

Scope:

- remote GPU host on Vast.ai
- standard container deployment on Vast.ai
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

## Fast Standard Path — Native Container Mode (Recommended)

The standard approach is **native container mode** with Cloudflare quick tunnel. **VMs were too slow to boot and are not used.**

Key characteristics:

- **No KVM VM** — the server runs directly on the bare GPU host via a standard container
- **Cloudflare quick tunnel** — provides a public `*.trycloudflare.com` URL immediately at startup without manual tunnel setup
- **Boot speed** — containers start in seconds vs. the multi-minute VM boot penalty observed during early testing
- **DeploymentMode** — `native` (not `docker_vm`)

```
DeploymentMode = "native"
EnableTunnel   = true   (Cloudflare quick tunnel via cloudflared)
```

This is the fastest path from Vast contract start to a live, publicly reachable API.

## Methods That Worked

These methods were re-verified on `2026-04-18`.

1. Vast standard container instance, not a KVM VM
2. Remote deploy in `native` mode
3. Cloudflare quick tunnel started on the remote model server
4. Local bridge on Windows pointing to the remote Cloudflare model URL
5. Dashboard using `bridge proxy active`
6. Remote ensemble detector with:
   - `rezzzq_yolo12s_rdd2022`
   - `ozair_yolov8_rdd2022`
   - `oracl4_yolov8_rdd2022`
7. Detector-only remote serving with permissive recall-oriented thresholds

The currently verified live pattern is:

- remote model API on Vast:
  - `/health`
  - `/analyze`
- public remote model URL via quick tunnel:
  - `https://<random>.trycloudflare.com`
- local dashboard bridge:
  - `http://127.0.0.1:8001`
- optional local public bridge URL via quick tunnel:
  - `https://<random>.trycloudflare.com`

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
REMOTE_DEPLOY_MODE=native
DETECTOR_MODE=ensemble
ENSEMBLE_ENABLED=true
ENSEMBLE_MEMBERS='["rezzzq_yolo12s_rdd2022","ozair_yolov8_rdd2022","oracl4_yolov8_rdd2022"]'
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

Important:

- `vlm_mode=api` on requests only works if the remote server was started with `ENABLE_VLM=true` and `VLM_API_URL` set.
- If the remote server is running detector-only (`ENABLE_VLM=false`), the server now degrades cleanly to detector-only instead of throwing an API VLM error.

## One-Shot Deployment

From Windows PowerShell:

```powershell
.\deploy\model_server\deploy_remote.ps1 `
  -Server YOUR_SSH_HOST `
  -SshPort YOUR_SSH_PORT `
  -DeploymentMode native `
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

For detector-only bring-up, a healthy response may still report:

- `enable_vlm: false`
- `vlm_backend: disabled`

That is acceptable for the fast serving path.

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

## Current Caveats

1. The current verified fast path is detector-only on the remote model server.
2. API VLM mode requires a real external VLM endpoint and credentials in the remote `.env`.
3. The Cloudflare quick-tunnel URL changes every restart.
4. Standard containers are the correct path here; KVM VMs were too slow to justify.
5. The current live box is an `RTX 3060 12 GB`. That is acceptable for ensemble detector serving and API-VLM forwarding, but it is not the right target for hosting local Qwen VLM on the same server.
