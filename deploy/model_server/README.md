# SkyLink Remote Model Server

This path bootstraps `model_server/` onto a Linux GPU host such as Vast.ai over SSH.

For the current remote-only ensemble path, use [VAST_REMOTE_SERVER_RUNBOOK.md](./VAST_REMOTE_SERVER_RUNBOOK.md).

It is designed for first-run model warmup. The script uploads the model server code, installs dependencies, optionally prefetches the VLM and YOLO weights, starts the API, and can expose it through a Cloudflare quick tunnel.

Two remote execution modes are supported:

- `native`: installs Python dependencies directly on the host and runs `model_server/run.sh`
- `docker_vm`: installs Docker/Compose on the remote VM, builds `deploy/model_server/Dockerfile`, and runs the API through `docker-compose.vm.yml`

## Remote Host Expectations

- Ubuntu or another Linux distribution with `bash`
- NVIDIA driver/CUDA runtime already present for vLLM workloads
- inbound SSH access
- enough VRAM for the selected VLM

## One-Shot Deployment From Windows

Create or edit a bridge env file first if you want the backend bridge updated automatically:

```powershell
Copy-Item .\app\.env.example .\app\.env
```

Deploy to the GPU host:

```powershell
.\deploy\model_server\deploy_remote.ps1 `
  -Server 198.51.100.10 `
  -RemoteUser root `
  -DeploymentMode docker_vm `
  -BridgeEnvFile .\app\.env `
  -HuggingFaceToken hf_xxx
```

The script returns the public analyze URL and API key. If `-BridgeEnvFile` is provided it also writes:

- `SKYLINK_VLM_API_URL`
- `SKYLINK_VLM_API_KEY`

## Important Options

- `-DisableTunnel`: do not start a remote quick tunnel
- `-DisableVlm`: run the remote server in YOLO-only mode and skip VLM install/prefetch
- `-EnableYoloV8`: keep dual-YOLO startup when `-DisableVlm` is used
- `-DeploymentMode docker_vm`: provision Docker/Compose on the remote VM and run the server in a GPU container
- `-SkipInstall`: skip `pip install` on the remote host
- `-SkipPrefetch`: skip first-run model downloads
- `-SkipLaunch`: upload only
- `-SkipWaitForHealth`: do not block on `/health`
- `-SkipWaitForTunnel`: do not block on a tunnel URL
- `-PublicBaseUrl`: use a stable public URL instead of a quick tunnel
- `-PublicHost`: fallback host/IP if the port is already publicly reachable

## Remote Script

The remote bootstrap entrypoint is `deploy/model_server/bootstrap_remote.sh`. Supported commands:

- `bootstrap`
- `install`
- `prefetch`
- `start`
- `tunnel`
- `stop`
- `status`

`status` prints a JSON object with the resolved analyze URL, tunnel URL, and health state. The bridge uses the same contract for autonomous remote startup.

In `docker_vm` mode, the JSON contract is preserved and augmented with:

- `deployment_mode`
- `docker_container`
- `docker_image`

The existing keys such as `status`, `analyze_url`, `reachable_base_url`, `server_pid`, and `health` are unchanged so existing callers can continue polling without modification.
