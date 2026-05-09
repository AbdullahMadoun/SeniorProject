# quickrecord

Ad-hoc tool for triggering Pi camera recordings from a laptop GUI and
pulling the resulting MP4 back over the LAN. Independent of the
SkyLink companion pipeline — the two cannot run concurrently because
the Pi camera is a single-consumer resource.

## Architecture

```
  Laptop                          Pi (over WiFi)
  ┌──────────────┐  POST /start   ┌──────────────────────────┐
  │  Tkinter     │ ─────────────▶ │  FastAPI service         │
  │  window with │  POST /stop    │  on port 8765            │
  │  Start/Stop  │ ─────────────▶ │                          │
  │  button      │  GET  /file/X  │  Picamera2 H264 encoder  │
  │              │ ◀───────────── │  writes /tmp/.../X.mp4   │
  └──────────────┘                └──────────────────────────┘
```

## Components

- [`pi_service/`](pi_service/README.md) — FastAPI service that owns
  the camera and serves MP4 files over HTTP.
- [`laptop_app/`](laptop_app/README.md) — Tkinter GUI that drives the
  Pi service and downloads recordings.

Each subdirectory has its own README with install + run instructions.
The Pi side and laptop side are installed independently into separate
venvs.

## Quick start

On the Pi:

```bash
cd tools/quickrecord/pi_service
.venv-quickrecord/bin/python -m pi_service
```

On the laptop:

```bash
cd tools/quickrecord
.venv-laptop/bin/python -m laptop_app --pi-url http://<pi-ip>:8765
```

## Known limitations

- **Camera is single-consumer.** Cannot run alongside
  `autonomy/companion/video_logger.py` — the second consumer's
  `/start` returns HTTP 503 with
  `{"error": "camera unavailable; another process likely holds it"}`.
  Stop one before running the other.
- **`/tmp` storage means recordings are lost on Pi reboot.** The
  in-memory recording registry is also reset on each service
  restart; files left on disk after a restart become orphans that
  `DELETE /file/{id}` cannot find. Reboot or `rm /tmp/quickrecord/*`
  to clean up.
- **No authentication.** The service binds to `0.0.0.0:8765` so the
  laptop can reach it. Only run on a trusted network (a dev hotspot,
  not an open / shared network).
- **No retry on flaky WiFi mid-download.** A failed download leaves
  the file on the Pi, so it can be retried manually:
  ```bash
  curl -O http://<pi-ip>:8765/file/<recording_id>
  ```
- **Dynamic Pi IP.** The hotspot may DHCP a new address at each
  reconnect; pass the current one via `--pi-url`. Find it on the Pi
  with `ip -brief addr`.
- **MP4 seekability at low bitrates.** H264 keyframe interval needs
  to be ≤ ~2 s for most viewers to seek smoothly. The default 10 Mbps
  is comfortably above that threshold; lower bitrates may produce
  files that play but won't seek in some viewers.
