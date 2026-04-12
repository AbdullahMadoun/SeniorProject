# SkyLink Remote Model Server

This path bootstraps `model_server/` onto a Linux GPU host such as Vast.ai over SSH.

It is designed for first-run model warmup. The script uploads the model server code, installs dependencies, optionally prefetches the VLM and YOLO weights, starts the API, and can expose it through a Cloudflare quick tunnel.

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
