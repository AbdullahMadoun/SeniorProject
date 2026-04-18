# SkyLink Backend Container Deployment

This path containerizes the FastAPI bridge in `app/src/server.py`.

For the verified local bridge + quick-tunnel path, see [WORKING_LOCAL_SERVER_RUNBOOK.md](./WORKING_LOCAL_SERVER_RUNBOOK.md).

The bridge can now operate in three modes:

1. Static external model URL via `SKYLINK_VLM_API_URL`
2. SSH-managed remote model host via `SKYLINK_REMOTE_MODEL_*`
3. Fully autonomous Vast.ai leasing plus SSH bootstrap via `SKYLINK_VAST_*`

The container starts a Cloudflare quick tunnel by default and reports the public bridge URL to the frontend runtime. When autonomous model startup is enabled, the same bridge also publishes model bootstrap state and, once ready, can switch the frontend into a direct model connection automatically.

For campus or enterprise Wi-Fi that blocks direct browser access to the remote GPU host, keep the frontend behind the bridge:

- `SKYLINK_USE_BRIDGE_PROXY=true`
- `SKYLINK_FRONTEND_DIRECT_MODEL=false`
- `SKYLINK_ENABLE_QUICK_TUNNEL=true` or provide a stable `SKYLINK_PUBLIC_BASE_URL`

In that mode the browser only talks to the bridge over normal HTTPS, and the bridge performs the upstream model call server-side.

## Local Docker Run

1. Start Docker Desktop.
2. Either set `SKYLINK_VLM_API_URL` and `SKYLINK_VLM_API_KEY`, or enable `SKYLINK_REMOTE_MODEL_AUTOSTART=true` and provide the SSH/Vast settings in `app/.env`.
3. Run:

```powershell
docker compose --env-file .\app\.env -f .\docker-compose.backend.yml up --build -d
```

4. Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
Invoke-RestMethod http://127.0.0.1:8001/api/runtime-config
```

The frontend served at `http://127.0.0.1:8001/` now shows:

- the active bridge URL
- the Cloudflare quick-tunnel URL once published
- model endpoint/key configuration status
- managed remote model bootstrap status and errors

5. Stop:

```powershell
docker compose -f .\docker-compose.backend.yml down
```

## Publish An Image

```powershell
.\deploy\backend\publish.ps1 -Registry ghcr.io/your-org -PushLatest
```

Recommended registries:

- `ghcr.io/<owner-or-org>`
- `docker.io/<namespace>`
- your private registry hostname

## Remote Server Deployment

Server prerequisites:

- Docker Engine with Compose plugin installed
- registry login already completed on the server if the image is private
- port `8001` open or reverse-proxied
- if `SKYLINK_REMOTE_MODEL_AUTOSTART=true`, provide an SSH keypair under `deploy/backend/ssh/` or copy one to the remote `ssh/` directory with `deploy_remote.ps1 -SshDir`

If the backend should lease and bootstrap a Vast.ai instance automatically at startup, the server env file must also include:

- `SKYLINK_VAST_API_KEY`
- `SKYLINK_REMOTE_MODEL_SSH_KEY_FILE`
- `SKYLINK_REMOTE_MODEL_SSH_PUBLIC_KEY_FILE`
- `SKYLINK_REMOTE_MODEL_PROVIDER=vastai`
- `SKYLINK_REMOTE_MODEL_AUTOSTART=true`

The bridge now fails before leasing anything if those SSH prerequisites are missing.

For cheap first-pass validation, set:

- `SKYLINK_REMOTE_MODEL_ENABLE_VLM=false`
- `SKYLINK_VAST_MIN_GPU_RAM_GB=10`
- `SKYLINK_VAST_PREFERRED_GPU_NAMES=RTX 3060,RTX 4060 Ti,RTX 3070,RTX A4000,T4`
- a lower `SKYLINK_VAST_MAX_HOURLY_USD`

If you do not want a temporary Cloudflare quick tunnel on the server, set `SKYLINK_ENABLE_QUICK_TUNNEL=false` and provide a stable `SKYLINK_PUBLIC_BASE_URL` instead.

Create a server env file from `deploy/backend/.env.server.example`, then deploy:

```powershell
.\deploy\backend\deploy_remote.ps1 `
  -Registry ghcr.io/your-org `
  -Server 203.0.113.10 `
  -RemoteUser ubuntu `
  -EnvFile .\deploy\backend\.env.server `
  -SshDir .\deploy\backend\ssh `
  -Tag latest
```

To build, push, and deploy in one step:

```powershell
.\deploy\backend\deploy_remote.ps1 `
  -Registry ghcr.io/your-org `
  -Server 203.0.113.10 `
  -RemoteUser ubuntu `
  -EnvFile .\deploy\backend\.env.server `
  -Tag latest `
  -BuildAndPush `
  -PushLatest
```

## Deployment Plan

1. Keep the bridge container separate from `model_server/`. The bridge is lightweight and portable; the VLM service should live on a Linux GPU host or remain an external managed endpoint.
2. Publish immutable tags for every rollout and optionally also update `latest`.
3. Store runtime history and tunnel state in the Docker volume mounted at `/var/lib/skylink`.
4. The frontend reads runtime-generated `/config.js` and `/api/runtime-config`, so tunnel state and public bridge URL are communicated automatically when the page loads.
5. When `SKYLINK_FRONTEND_DIRECT_MODEL=true`, the frontend automatically flips to the direct model endpoint once the bridge has provisioned it and has a usable URL.
6. Add health checks and restart policies first, then add CI/CD once the image and remote rollout path are stable.
