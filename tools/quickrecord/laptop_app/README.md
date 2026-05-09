# quickrecord — Laptop GUI

A small Tkinter window with a Start/Stop button that drives the
quickrecord Pi service in `../pi_service/`. Health-polls the Pi every
2 s, downloads the MP4 to a local folder when you stop the recording.

## One-time install on the laptop

```bash
cd /path/to/SeniorProject/tools/quickrecord/laptop_app
python3 -m venv .venv-laptop
.venv-laptop/bin/pip install -r requirements.txt
```

Tkinter ships with the system Python. If `python -c "import tkinter"`
fails:

- macOS (Homebrew Python): `brew install python-tk@3.12`
  (substitute your Python minor version)
- Debian / Ubuntu: `sudo apt install python3-tk`
- Fedora: `sudo dnf install python3-tkinter`

## Running the GUI

```bash
cd /path/to/SeniorProject/tools/quickrecord
.venv-laptop/bin/python -m laptop_app \
    --pi-url http://172.20.10.4:8765 \
    --save-folder ~/Videos/quickrecord
```

Both flags are optional. Defaults: `http://172.20.10.4:8765` for the
Pi URL and `~/Videos/quickrecord` for the save folder.

## How to use it

1. Start the Pi service first (see `../pi_service/README.md`).
2. Launch the GUI. The header strip turns green and reads
   "Connected" once the health probe sees the Pi.
3. Click **Start Recording**. The button becomes "Stop Recording" and
   the status box logs the assigned recording id.
4. Click **Stop Recording** when done. The GUI immediately downloads
   the MP4 to the save folder, showing progress in the status box,
   then re-enables the button for the next recording.

## Discovering the Pi's IP

The hotspot DHCPs different addresses to the Pi at different times.
On the Pi:

```bash
ip -brief addr
```

Pass that address via `--pi-url http://<addr>:8765`.

## Troubleshooting

- **"Disconnected" never goes green** — the Pi service isn't reachable.
  Check that it's running, that the laptop and Pi are on the same
  network, and that no firewall is dropping port 8765.
- **"Recording" stuck on the indicator** — the Pi service thinks a
  recording is in progress. Use `curl -X POST <pi-url>/stop` to clear
  it, or restart the Pi service (which resets in-memory state but
  leaves the on-disk file as an orphan in `/tmp/quickrecord/`).
- **Download fails partway** — the GUI does not auto-retry. Re-pull
  manually:
  ```bash
  curl -O http://<pi>:8765/file/<recording_id>
  ```
- **GUI freezes** — should not happen; all HTTP I/O runs on worker
  threads. If it does, the most likely cause is a Tk widget being
  touched from a worker thread; file an issue with the traceback.
