# SkyLink Phase 0 Reconnaissance Report
_Generated: 2026-05-03_

This is a read-only ground-truth snapshot of the SkyLink companion Pi taken
before Phase 1 (Pi ↔ real Pixhawk 4 USB bring-up). No packages were
installed, no configs modified, no `/dev/tty*` opened. The Pixhawk is not
plugged in for this pass.

Hardware: Raspberry Pi 5 Model B Rev 1.1 (BCM2712), 8 GiB RAM, hostname
`skylink-pi`, user `pi`.

---

## A. Repo state

### A.1 Git status / branch / log / remote

```
$ git -C /home/pi/SeniorProject status
On branch feature/rpi5-companion-bringup
Untracked files:
        companion_video_logger/

nothing added to commit but untracked files present

$ git branch --show-current
feature/rpi5-companion-bringup

$ git log -3 --oneline
9bae3ec Merge branch feature/rpi5-companion-bringup into main
c99e27f feat(companion): implement main() orchestration (R14 Gate 2 / IS5)
410b9ae feat(companion): implement upsert_run_row (R14 Gate 2 / IS5)

$ git remote -v
origin  https://github.com/AbdullahMadoun/SeniorProject.git (fetch)
origin  https://github.com/AbdullahMadoun/SeniorProject.git (push)
```

Branch context (verifies the kickoff claim that the companion code is
merged on `origin/main`):

```
$ git log origin/main -1 --oneline
9bae3ec Merge branch feature/rpi5-companion-bringup into main

$ git log main -1 --oneline
63d00e3 1000 times better        # local 'main' is STALE — pre-companion

$ git log --oneline origin/main..feature/rpi5-companion-bringup
(empty — feature branch tip == origin/main tip)
```

So `feature/rpi5-companion-bringup` HEAD == `origin/main` HEAD == `9bae3ec`.
The local `main` ref has not been fast-forwarded; the user has been
working from the feature branch directly. Other local branches:
`pi-backup-pre-reconcile-20260419-214116`,
`pi-uncommitted-video-logger-20260419-215810`.

The single untracked path `companion_video_logger/` is a stale test-output
directory (3 files: `latest_frame.jpg`, `summary.json`, `telemetry_log.csv`,
all dated 2026-04-18). It is the default `--output-dir` of `video_logger.py`
when run from the repo root. `.gitignore` partially covers it
(`companion_video_logger/*.npy`, `companion_video_logger/*.csv`).

### A.2 Top-level directory tree (depth 2–3)

```
SeniorProject/
├── app/                              # Road-inspection web app (not in scope)
│   ├── data/{processed,raw}
│   ├── models
│   ├── scripts
│   └── src/{static,tests}
├── artifacts/                        # Curated/generated evidence; mostly gitignored
├── autonomy/                         # Drone autonomy code
│   ├── companion/                    # ⭐ Pi-side companion package (this phase)
│   │   ├── .venv-pi/                 # ⭐ Pre-built Python venv (gitignored)
│   │   ├── artifacts/
│   │   ├── calibration_assets/
│   │   ├── config/                   # hardware_profile_*.toml, hardware_config.py
│   │   ├── hal/
│   │   ├── tests/                    # 9 test_*.py files
│   │   └── tools/                    # gps_probe.py, sitl_simple_mission.py, ...
│   ├── config/
│   ├── docs/                         # 26 *.md (architecture, hardware integration)
│   ├── drone_system/                 # runtime_affinity, etc.
│   ├── fixtures/
│   ├── scripts/                      # live_px4_*, mavlink, gazebo bridge scripts
│   ├── simulation/
│   └── tests/{e2e,integration}
├── companion_video_logger/           # ⭐ untracked stale test output
├── deploy/                           # ⭐ existing deploy assets
│   ├── backend/{ssh}
│   ├── model_server/
│   └── simulation/                   # Docker-SITL Dockerfile + bootstrap
├── docs/                             # ⭐ this report lives here
├── drone_platform/                   # GitHub-facing entry for drone stack
├── examples/
├── model_server/{GUIDES}
├── tests/                            # ⭐ top-level — only 2 unrelated test files
├── training_pilot/                   # Training pilot (not in scope)
├── vendor/                           # Local PX4/ArduPilot/MAVSDK checkouts
└── (no top-level scripts/ dir)
```

### A.3 Dependency manifests

Found:

- `app/requirements.txt`, `app/requirements-backend.txt` — road-inspection app
- `model_server/requirements.txt`, `model_server/requirements-yolo.txt`
- `training_pilot/requirements.txt`, `training_pilot/requirements-guide.txt`
- `autonomy/companion/requirements-rpi.txt` — ⭐ relevant manifest

`autonomy/companion/requirements-rpi.txt` (verbatim):

```
numpy==2.4.4
pymavlink
adafruit-blinka
adafruit-circuitpython-ads1x15
psutil
MAVProxy==1.8.74
future==1.0.0
pynmeagps==1.1.2

# --- camera stack (Pi 5 / libcamera) ---
# Required apt packages (install BEFORE pip install):
#   sudo apt install -y python3-libcamera python3-picamera2
#   (python3-picamera2 pulls python3-kms++ which provides the kms/pykms C extension)
#
# ABI drift risk: _libcamera and kms are C extensions from apt exposed to the venv via
#   autonomy/companion/.venv-pi/lib/python3.13/site-packages/libcamera.pth
# If the venv Python minor version diverges from the system Python used to build those
# apt packages, imports will fail. Re-create the venv against the system Python to fix.
#
# picamera2 installed from pip here overrides the apt version; apt provides only C deps.
opencv-contrib-python-headless==4.13.0.92
picamera2==0.3.34
pidng==4.0.9
piexif==1.1.3
simplejpeg==1.9.0

# --- cloud upload (Supabase) ---
supabase==2.24.0
```

No `pyproject.toml`, `Pipfile`, `environment.yml`, or `setup.py` present
anywhere in the repo (depth ≤ 4, excluding venvs).

### A.4 README and docs/

Top-level `README.md` (94 lines) names the SkyLink dual stack (drone +
road inspection) and points to:

- `drone_platform/README.md`, `EVIDENCE.md`, `RUNBOOK.md`
- `autonomy/docs/milestone_results.md`, `reproducibility_runbook.md`
- `autonomy/companion/README.md`, `RUNBOOK.md`

`docs/` (top-level) contains only three road-inspection-related notes and
is otherwise empty:

```
docs/
├── docker-to-vast-experiment-changes.md
├── dynamic_waypoints_docker_summary.md
└── vast_project_quickstart.md
```

The companion package has its own setup/usage docs:

- `autonomy/companion/README.md` (87 lines) — module list, mock env vars,
  example commands, deployment-mode guidance ("point MAVLink at
  `/dev/ttyAMA0` or the actual serial device" — note: written before the
  USB-`/dev/ttyACM0` plan).
- `autonomy/companion/RUNBOOK.md` (214 lines) — laptop-mock validation, Pi
  bootstrap, calibration, video-logger commands. Real-hardware example
  given as `--mavlink-target /dev/ttyAMA0 --mavlink-baud 57600` and
  `--mavlink-target udp:127.0.0.1:14551 --camera-source "udpsrc port=5600 ..."`.
- `autonomy/docs/hardware_integration_directive.md` (76 lines) and
  `hardware_networking_directive.md` (36 lines) — deeper directives.

### A.5 Existing tests/, fixtures/, scripts/, tools/

```
SeniorProject/tests/                              # top-level — 2 unrelated files
├── test_managed_remote_model.py
└── test_remote_model_helpers.py

autonomy/tests/                                   # autonomy-level
├── e2e/
└── integration/

autonomy/companion/tests/                         # ⭐ companion tests
├── test_aruco_detector.py
├── test_calibrate_camera.py
├── test_generate_aruco_marker.py
├── test_generate_checkerboard.py
├── test_gpio_charging.py
├── test_mock_rpi.py
├── test_run_companion_smoke.py
├── test_video_logger.py
└── test_yolo_pothole_detect.py

autonomy/companion/tools/                         # ⭐ existing companion CLI tools
├── gps_probe.py
├── sitl_simple_mission.py
├── test_charging_gate.py
└── test_rtl_monitor.py

autonomy/scripts/                                 # autonomy-level scripts (~60 files)
   live_px4_*, run_live_px4_*, mavlink, gazebo, sitl, showcase, …

(top-level SeniorProject/scripts/ does NOT exist)
(no diagnostics/ directory anywhere in the repo)
```

### A.6 MAVProxy / mavlink-router configs in the repo

None found outside the venv. `grep` for `*.cfg` / `mavproxy*` /
`mavlink-router*` (excluding `.venv-pi/` and `.git/`) returns no
configuration files. The only references to MAVProxy in source are usage
mentions in markdown docs.

### A.7 Pre-existing systemd unit files in the repo

None. `find . -name "*.service"` in the repo returns nothing under
`deploy/`, `autonomy/`, top-level, or any subdir.

`deploy/` is structured as:

```
deploy/backend/{deploy_remote.ps1, docker-compose.server.yml, publish.ps1, README.md, ssh/}
deploy/model_server/{bootstrap_remote.sh, deploy_remote.ps1, README.md}
deploy/simulation/{Dockerfile, docker_entrypoint.sh, bootstrap_remote.sh,
                   onstart_px4_landing_demo.sh, README.md, vast_probe.py}
```

So Phase 1 systemd units would naturally land under a new
`deploy/companion/` subdir to match this convention.

### A.8 .env / config schemas (no values)

Two relevant files. Values redacted; only key lists are shown.

`SeniorProject/app/.env.example` — schema for the road-inspection app
(out of scope for Phase 1, listed for completeness):

```
SKYLINK_TARGET_CLASSES, SKYLINK_MIN_CRACK_AREA_RATIO,
SKYLINK_DEMO_GPS_IF_MISSING, SKYLINK_DEMO_CENTER_LAT,
SKYLINK_DEMO_CENTER_LON, SKYLINK_DEMO_STEP_DEG,
SKYLINK_BRIDGE_PORT, SKYLINK_VLM_API_URL, SKYLINK_VLM_API_KEY,
SKYLINK_ENABLE_QUICK_TUNNEL, SKYLINK_PUBLIC_BASE_URL,
SKYLINK_EXPOSE_VLM_API_KEY_TO_FRONTEND, SKYLINK_USE_BRIDGE_PROXY,
SKYLINK_FRONTEND_DIRECT_MODEL,
SKYLINK_REMOTE_MODEL_* (~25 keys for autonomous remote-model bring-up),
SKYLINK_VAST_* (~13 keys for Vast.ai leasing),
SKYLINK_BOARD_SHOW_LEGACY, SKYLINK_BOARD_PREFIXES, SKYLINK_BOARD_START_UTC
```

`/home/pi/.skylink_env` — runtime secrets for upload_run.py
(out-of-repo, mode `600`, owned by `pi`). Schema:

```
API_KEY                       # (purpose unclear from this file alone)
VLM_API_KEY
SKYLINK_VLM_API_KEY
SUPABASE_URL                  # ⭐ required by upload_run.py
SUPABASE_SERVICE_ROLE_KEY     # ⭐ required by upload_run.py
```

The file's banner comment says "not visible to Claude Code", but the file
is mode 600 owned by `pi` and Claude Code runs as `pi` — so it IS
readable. Values were not printed; only key names are recorded above.

---

## B. Pipeline contracts (video_logger.py, upload_run.py)

Both files live in `autonomy/companion/`. Lengths:
`video_logger.py` 676 lines, `upload_run.py` 677 lines.

### B.1 CLI invocation patterns

`video_logger.py` argparse (autonomy/companion/video_logger.py:627–645):

```python
parser = argparse.ArgumentParser(description="Threaded MAVLink + camera companion video logger")
parser.add_argument("--mavlink-target",  default=DEFAULT_MAVLINK_TARGET)   # default below
parser.add_argument("--mavlink-baud",    type=int,  default=57600)
parser.add_argument("--camera-source",   default=DEFAULT_CAMERA_SOURCE)    # default "0"
parser.add_argument("--output-dir",      type=Path, default=DEFAULT_OUTPUT_DIR)
parser.add_argument("--max-frames",      type=int,  default=30)
parser.add_argument("--frame-width",     type=int,  default=640)
parser.add_argument("--frame-height",    type=int,  default=480)
parser.add_argument("--frame-interval",  type=float,default=0.1)
parser.add_argument("--mock-mavlink",    action="store_true")
parser.add_argument("--mock-camera",     action="store_true")
parser.add_argument("--camera-backend",  choices=["cv2","picamera2","auto"], default="auto")
parser.add_argument("--stream",          action="store_true")
parser.add_argument("--stream-host",     default="127.0.0.1")
parser.add_argument("--stream-port",     type=int, default=5050)
parser.add_argument("--stream-path",     default="/stream")
parser.add_argument("--cpu-core",        type=int, default=1)
```

No CLI args are required (all optional with defaults). Default invocation
on the Pi will pick up `picamera2` automatically and use UDP MAVLink.

`upload_run.py` argparse (autonomy/companion/upload_run.py:536–566):

```python
parser.add_argument("output_dir",  type=Path)            # ⭐ positional, REQUIRED
parser.add_argument("--run-id",    type=str, default=None)
parser.add_argument("--mission-id",type=str, default=None)   # UUID FK or NULL
parser.add_argument("--dry-run",   action="store_true")
parser.add_argument("--verbose",   action="store_true")
```

### B.2 MAVLink input wiring for video_logger.py

Source of truth — `autonomy/companion/video_logger.py:30`:

```python
DEFAULT_MAVLINK_TARGET = os.environ.get("SKYLINK_MAVLINK_TARGET", "udp:127.0.0.1:14551")
```

Resolution priority (highest first):

1. `--mavlink-target` CLI arg (line 629)
2. `SKYLINK_MAVLINK_TARGET` env var (line 30)
3. Hardcoded default `"udp:127.0.0.1:14551"` (line 30)

Connection-string handling lives in `_open_mavlink_connection`
(video_logger.py:262–270): bare `/dev/...` paths and `COM*` open as
serial via `mavutil.mavlink_connection(..., baud=baud, autoreconnect=True,
source_system=250)`; otherwise the string is normalised and opened as
UDP/TCP. Baud comes from `--mavlink-baud` (default 57600).

Phase 1 implication: with MAVProxy bridging `/dev/ttyACM0 → udp:127.0.0.1:14551`,
`video_logger.py` runs **with no flag changes** — the default UDP target
matches exactly. Everywhere else `udp:127.0.0.1:14551` appears as a
default: `RUNBOOK.md` (real-hw example), `tools/gps_probe.py`.

### B.3 Output paths and file formats (video_logger.py)

`run()` writes 4 files into `config.output_dir`
(autonomy/companion/video_logger.py:528–624):

| Path | Format | Producer |
|---|---|---|
| `telemetry_log.csv` | CSV (DictWriter, 9 cols: frame_index, timestamp_utc, lat_deg, lon_deg, altitude_m, relative_altitude_m, heading_deg, fix_type, telemetry_source) | per-frame `_write_csv_row` |
| `telemetry.jsonl`   | JSON Lines, one record per frame: frame_idx, frame_ts_unix, lat/lon/alt, ground/airspeed, roll/pitch/yaw, gps/vfr/att age in ms | per-frame `_build_jsonl_entry` |
| `latest_frame.jpg`  | JPEG (cv2.imwrite, overwritten each frame) | per-frame |
| `summary.json`      | JSON (config dump + counters + camera_backend_used + frame_age_max_ms + last_telemetry_error + stream meta) | end-of-run |

`DEFAULT_OUTPUT_DIR = Path(os.environ.get("SKYLINK_VIDEO_LOGGER_OUTPUT", Path.cwd() / "companion_video_logger"))`
(video_logger.py:32) — i.e. `./companion_video_logger` relative to the
caller's CWD. The untracked stale dir at the repo root is from this default.

### B.4 Logging behavior

No file-based logger.

- Per-frame stderr line on first camera build:
  `[video_logger] camera backend selected: <picamera2|cv2|mock|injected>`
  (lines 362, 366, 373, 386).
- Telemetry-loop exceptions are swallowed into
  `_last_telemetry_error` / `_telemetry_errors_count` and surfaced only
  in `summary.json` (lines 413–415, 615–616).
- Final stdout: pretty-printed `summary` JSON (line 671).

`enforce_cpu_affinity(self.config.cpu_core, label="video_logger")` is
called at `run()` start (line 529); if `psutil` is unavailable it warns
and continues. Default core: `1`.

For `upload_run.py`:

- All progress/diagnostic output is on **stderr** (when `--verbose`).
- Final stdout contract on success (last line):
  `SUCCESS: run_id=<id> uploaded_at=<ISO8601 Z> latency_s=<float>`
  (line 668–672).
- Exit codes: 0 success, 1 missing env / CLI, 2 MissingArtifactError,
  3 TelemetryParseError|SummaryParseError, 4 ArtifactUploadError,
  5 RowUpsertError.

### B.5 Env vars / config for upload_run.py

Read from `os.environ` directly (no `.env` loading inside the script —
**caller** must `set -a; source ~/.skylink_env; set +a`):

| Var | Required? | Source line | Notes |
|---|---|---|---|
| `SUPABASE_URL` | yes | upload_run.py:569 | else exit 1 |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | upload_run.py:570 | else exit 1 |
| `SUPABASE_BUCKET` | **NO — not actually read** | docstring lines 17–18 mention it | The code uses constant `BUCKET_NAME = "skylink_runs"` (line 60). The docstring is misleading. |

Hardcoded constants (upload_run.py:60–86):

- `BUCKET_NAME = "skylink_runs"`
- `TABLE_NAME = "skylink_runs"`
- 4-artifact set: `telemetry.jsonl`, `telemetry_log.csv`, `summary.json`,
  `latest_frame.jpg` — symmetric with `video_logger.py` outputs.

Presence in current environment: `~/.skylink_env` exists with both
required keys (see A.8). Phase 1 will not need to add any new secret.

---

## C. Pi system state

### C.1 OS

```
$ cat /etc/os-release
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
VERSION_ID="13"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.4
ID=debian
```

⚠️ Trixie, not Bookworm. Trixie ships `rpicam-*` rather than
`libcamera-*` user-facing tools (see D.1).

### C.2 Kernel + arch

```
$ uname -a
Linux skylink-pi 6.12.75+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.12.75-1+rpt1 (2026-03-11) aarch64 GNU/Linux
```

### C.3 Python / pip / node

```
$ python3 --version
Python 3.13.5
$ which python3
/usr/bin/python3
$ pip3 --version
pip 25.1.1 from /usr/lib/python3/dist-packages/pip (python 3.13)
$ node --version
v20.20.2
```

### C.4 Existing virtual environments

```
$ find /home/pi -maxdepth 3 -name "pyvenv.cfg"
/home/pi/SeniorProject/autonomy/companion/.venv-pi/pyvenv.cfg
```

The single venv lives **inside the repo** (gitignored). Contents of
`pyvenv.cfg`:

```
home = /usr/bin
include-system-site-packages = false
version = 3.13.5
executable = /usr/bin/python3.13
command = /usr/bin/python3 -m venv /home/pi/SeniorProject/autonomy/companion/.venv-pi
```

A `system-lgpio.pth` and `libcamera.pth` bridge in apt-installed C
extensions (from `bootstrap_rpi_companion.sh:62–63` and the comments in
`requirements-rpi.txt`).

No `venv/`, `.venv/`, `*-venv/` directly under `$HOME`.

### C.5 MAVLink-related Python packages

```
$ pip3 list | grep -iE "mavlink|mavproxy|dronekit|pyserial"
types-pyserial                            3.5
```

System-wide `pip3` has only the type stubs. The real packages live
inside `.venv-pi`:

```
$ /home/pi/SeniorProject/autonomy/companion/.venv-pi/bin/pip list | grep -iE "..."
MAVProxy                                 1.8.74
opencv-contrib-python-headless           4.13.0.92
picamera2                                0.3.34
pymavlink                                2.4.49
pyserial                                 3.5
supabase                                 2.24.0
supabase-auth                            2.24.0
supabase-functions                       2.24.0
types-pyserial                           3.5
```

`mavproxy.py` is at `.venv-pi/bin/mavproxy.py`. Apt-installed packages
relevant to the camera path (system-wide):
`libcamera-apps`, `libcamera-ipa:arm64`, `libcamera0.7:arm64`,
`librpicam-app1:arm64`, `python3-libcamera`, `python3-picamera2`,
`rpicam-apps` (and `-core`, `-encoder`, `-lite`, `-opencv-postprocess`,
`-preview`).

### C.6 Groups for user `pi`

```
$ groups
pi adm dialout cdrom sudo audio video plugdev games users netdev gpio i2c spi render input
```

⭐ `dialout` is **already** present. Phase 1 Session 1's plan to add it
is a no-op on this machine.

### C.7 lsusb (Pixhawk currently unplugged)

```
$ lsusb
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
```

Only root hubs — nothing else attached over USB.

### C.8 Currently visible serial devices

```
$ ls /dev/ttyACM* /dev/ttyUSB*
ls: cannot access '/dev/ttyACM*': No such file or directory
ls: cannot access '/dev/ttyUSB*': No such file or directory
```

### C.9 Network

```
$ ip -brief addr
lo               UNKNOWN        127.0.0.1/8 ::1/128
eth0             DOWN
wlan0            UP             172.20.10.4/28 2a02:9b0:8017:2d3a:2ecf:67ff:feb5:bf7d/64 fe80::2ecf:67ff:feb5:bf7d/64
```

The Pi is reachable over Wi-Fi at `172.20.10.4`. Eth0 is down.

### C.10 Disk

```
$ df -h /
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2  117G  6.3G  106G   6% /
$ df -h /home/pi
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2  117G  6.3G  106G   6% /        # same partition
```

7.9 GiB RAM total, 6.2 GiB free; 2 GiB swap (unused). Plenty of headroom.

### C.11 Pre-existing related systemd services

```
$ systemctl list-unit-files --type=service | grep -iE "mavproxy|skylink|drone"
(no matches)
```

### C.12 Node version

`v20.20.2` (Claude Code-compatible).

---

## D. Hardware-side observations

### D.1 Pi Camera (CSI)

```
$ libcamera-hello --list-cameras
/bin/bash: line 1: libcamera-hello: command not found

$ rpicam-hello --list-cameras
Available cameras
-----------------
0 : ov5647 [2592x1944 10-bit GBRG] (/base/axi/pcie@1000120000/rp1/i2c@88000/ov5647@36)
    Modes: 'SGBRG10_CSI2P' : 640x480   [58.92 fps - (16, 0)/2560x1920 crop]
                             1296x972  [46.34 fps - (0, 0)/2592x1944 crop]
                             1920x1080 [32.81 fps - (348, 434)/1928x1080 crop]
                             2592x1944 [15.63 fps - (0, 0)/2592x1944 crop]
```

✅ One camera detected — **OV5647** (Camera Module 1 / "RPi Camera v1.3"
or compatible) on the CSI bus. Trixie renamed `libcamera-hello` →
`rpicam-hello`; the underlying libcamera stack is installed and working,
and `python3-picamera2` is present (so the venv's `picamera2` import will
succeed via the `libcamera.pth` bridge).

### D.2 Pixhawk

Not currently plugged in (lsusb in C.7 shows root hubs only; ttyACM*
absent in C.8). When plugged in, the Pixhawk 4 typically enumerates as
ID `26ac:0011` (3DR/Hex) or similar and presents `/dev/ttyACM0`.

### D.3 dmesg tail (last 30)

```
$ dmesg | tail -30
[    2.836958] vc4-drm axi:gpu: [drm] Cannot find any crtc or sizes        ×3 (no display)
[    2.853809] Bluetooth: hci0: BCM: chip id 107
… BCM4345C0 firmware load …
[    4.174075] Bluetooth: BNEP (Ethernet Emulation) ver 1.3
[    4.214404] Bluetooth: RFCOMM TTY layer initialized
[    4.870935] systemd-rc-local-generator[803]: /etc/rc.local is not marked executable, skipping.   ×4
[    6.486095] macb 1f00100000.ethernet eth0: PHY [...] driver [Broadcom BCM54213PE] (irq=POLL)
[    6.488918] macb 1f00100000.ethernet: gem-ptp-timer ptp clock registered.
[    6.516844] brcmfmac: brcmf_cfg80211_set_power_mgmt: power save enabled
[   91.856798] brcmfmac: brcmf_cfg80211_set_power_mgmt: power save disabled
[   91.996449] ieee80211 phy0: brcmf_cfg80211_reg_notifier: Firmware rejected country setting
```

Boot messages only. Nothing recent. No USB events. The `rc.local`
"not marked executable" lines are cosmetic. The "Firmware rejected
country setting" is a benign Wi-Fi locale warning. Pi has been up 25
minutes. No Pixhawk insertion event would appear here yet.

---

## E. Concerns and pre-Phase-1 recommendations

The following items are worth flagging to chat-Claude before starting
Session 1. None block progress; several reduce planned work.

1. **OS is Trixie (Debian 13), not Bookworm.** Plan documents that
   reference `libcamera-hello` should use `rpicam-hello` instead. The
   underlying camera stack (libcamera + Picamera2) is installed and
   working (`rpicam-hello --list-cameras` confirms an OV5647 sensor at
   index 0). No action needed for the pipeline itself — only for any
   diagnostic script that invokes the user-facing tool by name.

2. **`dialout` already in user `pi`'s groups.** Phase 1 Session 1's
   plan to add it is a no-op. Skip the `usermod -aG dialout pi` step
   (and the logout-required reboot it implies).

3. **MAVProxy already installed in `.venv-pi`** (1.8.74), not
   system-wide. Phase 1 should explicitly choose:
   - run the bridge from `.venv-pi/bin/mavproxy.py` (preferred — pinned
     version, reproducible, matches `requirements-rpi.txt`), or
   - install MAVProxy system-wide (would duplicate; not recommended).
   Any systemd unit should use the venv path.

4. **Local `main` ref is stale** (`63d00e3` "1000 times better"), while
   `origin/main` and the active feature branch are at `9bae3ec`. The
   kickoff context that "the code is merged on origin/main" is correct.
   Phase 1 should decide: keep working on
   `feature/rpi5-companion-bringup` (current state) or fast-forward
   local `main` and switch. Either is fine; the diff is empty.

5. **No `scripts/diagnostics/` directory exists yet** anywhere in the
   repo (top-level `scripts/` itself is absent). The kickoff naming
   `scripts/diagnostics/` would create a new top-level convention. The
   alternative — `autonomy/companion/scripts/diagnostics/` — keeps
   diagnostics co-located with the code under test (and matches existing
   subtree conventions like `app/scripts/`, `autonomy/scripts/`,
   `training_pilot/scripts/`). **Recommendation: confirm with chat-Claude
   which placement is intended before Session 1 lands the first probe.**

6. **No systemd unit files anywhere in the repo, no MAVProxy/mavlink-
   router configs.** Phase 1 will introduce both. To match the existing
   `deploy/` convention, a new `deploy/companion/` subdirectory is the
   natural home for the systemd unit and any MAVProxy config (alongside
   `deploy/{backend,model_server,simulation}/`). The Pi-side venv path
   `/home/pi/SeniorProject/autonomy/companion/.venv-pi/bin/mavproxy.py`
   should be parameterised in the unit file.

7. **`upload_run.py` docstring claims `SUPABASE_BUCKET` is read from
   the environment, but the code uses a hardcoded constant
   `BUCKET_NAME = "skylink_runs"` (autonomy/companion/upload_run.py:60).**
   This is a pre-existing minor doc inconsistency — flag for a future
   doc cleanup, do not fix in Phase 1 (read-only intent for the pipeline
   modules).

8. **`~/.skylink_env` banner says "not visible to Claude Code", but
   the file is mode `600` owned by `pi` and Claude Code runs as `pi`.**
   The file IS readable by this agent. No values were printed in this
   report (only key names in A.8). If invisibility was intended, the
   project should either (a) update the comment, or (b) restrict the
   file via a different mechanism (e.g. a separate user). Flag for
   chat-Claude.

9. **Companion `RUNBOOK.md` and `README.md` describe the real-hardware
   MAVLink target as `/dev/ttyAMA0` (Pi onboard UART) in the
   "Deployment Modes" section** but the Phase 1 plan uses `/dev/ttyACM0`
   (USB-CDC over the Pixhawk USB-C port) bridged via MAVProxy to UDP.
   The pipeline code itself is agnostic — it accepts any MAVLink target
   via `--mavlink-target` — but the docs should be updated when Phase 1
   lands the USB path so future readers don't follow the older UART
   guidance. Track as a Phase 1 doc-update task; do not modify in
   Phase 0.

10. **Untracked `companion_video_logger/` directory at the repo root**
    contains stale test-run artifacts (frame, summary, csv) from
    2026-04-18. Mostly gitignored by pattern. Not a concern; suggest
    removing or moving in a later cleanup pass.

11. **No concerns around disk, RAM, network, Python version, Node
    version, picamera2 import surface, or `pymavlink`/`pyserial`
    install state** beyond what is noted above. The Pi is materially
    ready to receive a Pixhawk on USB.

The single thing the user must physically do before Session 1 is plug
in the Pixhawk 4 over USB — at which point a probe (not yet written)
should observe `/dev/ttyACM0` and a vendor/product pair in `lsusb`.
