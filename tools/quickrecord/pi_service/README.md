# quickrecord — Pi service

A small FastAPI service that exposes the Pi camera as four HTTP
endpoints (`/start`, `/stop`, `/file/{id}`, `/health`, plus a
`DELETE /file/{id}` for cleanup). Designed to be paired with the
laptop GUI in `../laptop_app/`.

## One-time install on the Pi

The SkyLink companion uses a venv at `autonomy/companion/.venv-pi/`
that has a carefully wired libcamera.pth bridge into the system
`python3-picamera2` package. **Do not install quickrecord into that
venv** — keep the SkyLink venv clean. Use a separate venv just for
this tool.

```bash
# System packages (only if not already installed by the SkyLink bootstrap):
sudo apt install -y python3-picamera2 ffmpeg python3-venv

# Create the quickrecord venv next to this README:
cd ~/path/to/SeniorProject/tools/quickrecord/pi_service
python3 -m venv --system-site-packages .venv-quickrecord

# `--system-site-packages` lets the venv see python3-picamera2 from apt
# without needing the libcamera.pth bridge dance. If that flag doesn't
# work for you (e.g. picamera2 still ImportErrors), copy the libcamera
# bridge from .venv-pi:
#
#   cp ../../../autonomy/companion/.venv-pi/lib/python*/site-packages/libcamera.pth \
#      .venv-quickrecord/lib/python*/site-packages/
#
# See autonomy/companion/bootstrap_rpi_companion.sh:62-63 for the
# original bridge wiring.

.venv-quickrecord/bin/pip install -r requirements.txt
```

Verify the camera is reachable:

```bash
.venv-quickrecord/bin/python -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
```

## Running the service

```bash
cd ~/path/to/SeniorProject/tools/quickrecord
.venv-quickrecord/bin/python -m pi_service
```

Or from inside `pi_service/` itself:

```bash
cd ~/path/to/SeniorProject/tools/quickrecord/pi_service
PYTHONPATH=.. .venv-quickrecord/bin/python -m pi_service
```

The service prints `quickrecord service ready, storage=/tmp/quickrecord`
on startup. If `ffmpeg` is missing it will fail fast with a clear error
message — install ffmpeg and restart.

**Do not run as a systemd service.** This is an ad-hoc tool; bring it
up by hand when you want to record, and Ctrl-C it when you're done.

## Discovering the Pi's IP

The hotspot DHCPs different IPs to the Pi at different times. To find
the current address from the Pi itself:

```bash
ip -brief addr
```

(Confirmed working in the Phase 0 baseline notes, §C.9.)

## Coexistence with the SkyLink companion

The Pi camera is a single-consumer resource. If
`autonomy/companion/video_logger.py` is running, it owns the camera
and quickrecord's `/start` will return HTTP 503 with
`{"error": "camera unavailable; another process likely holds it"}`.
Stop `video_logger.py` first, or accept that the two tools are
mutually exclusive.

## Storage and persistence

Recordings live at `/tmp/quickrecord/{recording_id}.mp4`. On
Raspberry Pi OS, `/tmp` is backed by the SD card (not tmpfs by
default), so you have whatever free space the SD card has — but the
service still rejects new recordings with HTTP 507 if free space drops
below 2 GiB.

`/tmp` is wiped on Pi reboot, so recordings do not persist across a
reboot. The in-memory recording registry is also reset on each service
restart, which means files left on disk after a service restart become
orphans (still on disk, but `DELETE /file/{id}` won't find them in the
registry). Clean up by hand if it bothers you, or just reboot.

## Endpoint reference

### `POST /start`

Request body (JSON, all fields optional):

```json
{"resolution": [1920, 1080], "bitrate_bps": 10000000}
```

Defaults: 1920×1080 at 10 Mbps. Lower bitrates may produce
non-seekable MP4s in some viewers — the H264 keyframe interval needs
to be ≤ 2 s for most players to seek smoothly.

- `200 OK` → `{"recording_id": "<uuid>", "started_at": "<ISO8601>"}`
- `409 Conflict` → already recording, with `current_recording_id`
- `503 Service Unavailable` → camera busy (another process holds it)
- `507 Insufficient Storage` → free disk below 2 GiB

### `POST /stop`

No body.

- `200 OK` → `{"recording_id", "stopped_at", "size_bytes", "duration_s"}`
- `409 Conflict` → not recording

### `GET /file/{recording_id}`

Streams the MP4 back with `Content-Type: video/mp4` and
`Content-Disposition: attachment; filename="{id}.mp4"`. The file is
NOT deleted on download.

- `200 OK` → MP4 bytes
- `404 Not Found` → unknown id, or file is gone from disk

### `DELETE /file/{recording_id}`

Explicit cleanup.

- `200 OK` → `{"recording_id": ..., "deleted": true}`
- `404 Not Found` → unknown id

### `GET /health`

```json
{"status": "ok", "recording": false, "current_recording_id": null,
 "free_disk_bytes": 106000000000}
```
