# Working Local Server Runbook

This is the verified local bridge + model-server path that worked on `2026-04-17`.

It is the correct fallback when:

- direct browser access to Vast is blocked by campus Wi-Fi
- the frontend should only talk to a normal HTTPS endpoint
- the bridge should proxy `/api/analyze` server-side

## What Worked

1. Local model server on `127.0.0.1:17612`
2. Local bridge/dashboard on `127.0.0.1:8001`
3. Anonymous Cloudflare quick tunnel published by the bridge
4. Frontend talking only to the bridge, not directly to the GPU endpoint
5. `/api/runtime-config` and `/api/health` through the public tunnel
6. `/api/analyze` through the bridge using JSON `image_b64` payloads
7. The direct model server and the bridge both return the analysis payload nested under `report`

## Start

From repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_local_stack.ps1 -SkipInstall -EnableQuickTunnel
```

If `cloudflared.exe` is already downloaded, pin it explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_local_stack.ps1 `
  -SkipInstall `
  -EnableQuickTunnel `
  -CloudflaredBin .\artifacts\local_runtime\cloudflared\cloudflared.exe
```

## Stop

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop_local_stack.ps1
```

## Health Checks

```powershell
Invoke-RestMethod http://127.0.0.1:17612/health
Invoke-RestMethod http://127.0.0.1:8001/api/health
Invoke-RestMethod http://127.0.0.1:8001/api/runtime-config
```

The current public tunnel URL is always written to:

- `artifacts/runtime_state/stack_state.json`
- `artifacts/runtime_state/tunnel_info.json`

## Request Shape

Preferred path:

- browser or API client -> bridge `/api/analyze`
- bridge -> model server `/analyze`

Preferred request body:

```json
{
  "image_b64": "<raw base64 image bytes>",
  "location": [26.305, 50.146],
  "vlm_mode": "disabled"
}
```

Notes:

- The dashboard already sends raw base64, not a `data:` URI.
- The bridge now also accepts multipart uploads and converts them into the model server's JSON contract.
- `vlm_mode=disabled` is the fastest path to validate detector-only serving.
- The model server response shape is:

```json
{
  "report": {
    "summary": "...",
    "boxes": [],
    "report_markdown": "...",
    "annotated_image_b64": "...",
    "detector_debug": {}
  }
}
```

## Frontend Routing Mode

The working bridge mode is:

```text
SKYLINK_USE_BRIDGE_PROXY=true
SKYLINK_FRONTEND_DIRECT_MODEL=false
SKYLINK_ENABLE_QUICK_TUNNEL=true
```

That keeps the browser off the remote/Vast host entirely.

## Current Serving Caveat

The local Windows runtime cannot execute the `rezzzq_yolo12s_rdd2022` member correctly right now.

Observed failure:

```text
'AAttn' object has no attribute 'qkv'
```

Because of that, the ensemble runtime was patched to:

- skip failing members instead of crashing the whole API
- continue serving with surviving members
- expose the failed member in `detector_debug.failed_members`

The local launcher also now relaxes serving-time fusion defaults for this degraded fallback:

```text
ENSEMBLE_WBF_SKIP=0.01
ENSEMBLE_FINAL_THRESHOLD=0.03
ENSEMBLE_MIN_SUPPORT=1
```

These are serving-only defaults for the local stack so it does not silently return zero boxes when the strongest member is unavailable.

## Current Verified Detector Behavior

After lowering the local serving thresholds, the following was re-verified:

- direct model server `/analyze`: working
- bridge `/api/analyze`: working
- current degraded ensemble members: `ozair + oracl4`

On the local sample `app/src/static/history_images/thumb_483abe8b7890.jpg`, both endpoints returned:

- `2` boxes
- `summary = "2 defect(s) detected."`
- `resolved_vlm_mode = "disabled"`

This is only a serving sanity check, not a benchmark claim.

## Supabase Status

Supabase is **not configured in the current running stack**.

Reason:

- `.env` only contains a project ref-like value for `SUPABASE_URL`
- no `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY` is present in the runtime env

The server checks this explicitly in `app/src/server.py` and only reports Supabase as configured when both are present.

To enable it, set:

```text
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-side secret key>
```

Then restart the stack.

`deploy/backend/.env.server.example` now includes these placeholders.

Important key type note:

- use the server-side Supabase secret key for the backend
- do not use the `sb_publishable_...` key for backend writes

## Quick Tunnel Caveat

Cloudflare anonymous quick tunnels are fine for testing and demo access, but they are not stable production ingress.

Known caveats:

- the URL changes on restart
- large or slow requests can hit `524` timeouts
- health/runtime endpoints are the most reliable validation path
- local bridge and direct local model requests are more reliable than the anonymous public tunnel for larger images

If you need a stable public endpoint later, move to a named Cloudflare tunnel or a normal reverse proxy.

## Logs

Current run logs live under:

- `artifacts/runtime_state/model_server_*.log`
- `artifacts/runtime_state/model_server_*.err.log`
- `artifacts/runtime_state/bridge_server_*.log`
- `artifacts/runtime_state/bridge_server_*.err.log`
- `artifacts/runtime_state/cloudflared.log`

## Repeatability Note

For the current local path, stopping the Vast server does not block repeatability.

The verified working path is:

- local model server
- local bridge/dashboard
- Cloudflare anonymous quick tunnel
- VLM via API

So you can repeat the current demo path without Vast, using the same local start command.

What is still not fully smooth:

- YOLO12 is still incompatible in the current local runtime, so the local ensemble may degrade to `ozair + oracl4`
- the anonymous tunnel URL changes on every restart

## Bottom Line

The bridge + dashboard + anonymous tunnel path is working.

The remaining quality issue is not tunneling; it is model-serving quality under a degraded 2-member fallback because YOLO12 is incompatible in the current local runtime.
