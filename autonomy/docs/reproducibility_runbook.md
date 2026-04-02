# SkyLink Reproducibility Runbook

This runbook captures the exact environment and commands needed to reproduce the autonomy stack setup, tests, and PX4 simulation path on this project.

It should be updated whenever the installation path, runtime dependencies, or validation commands change.

## Repo Paths

- Project root: `D:\downloads\SeniorProject\Skylink2`
- Autonomy subsystem: `D:\downloads\SeniorProject\Skylink2\autonomy`
- PX4 repo: `D:\downloads\SeniorProject\Skylink2\vendor\PX4-Autopilot`
- MAVSDK Python repo: `D:\downloads\SeniorProject\Skylink2\vendor\MAVSDK-Python`
- Installation log: [installation_log.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/installation_log.md)

## Windows Host Setup

### Python Virtual Environment

Create the isolated autonomy environment:

```powershell
python -m venv D:\downloads\SeniorProject\Skylink2\autonomy\.venv
```

Install MAVSDK plus the runtime dependencies used by the API, affinity isolation, and MAVLink tools into that environment:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m pip install mavsdk pymavlink psutil
```

### Validation On Host

Run the full autonomy test suite:

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

Generate safety scenario artifacts:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_safety_scenarios.py
```

Generate precision-landing scenario artifacts:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_precision_landing_scenarios.py
```

Build the latest replay bundle:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
```

Generate weather gate scenario artifacts:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_weather_gate_scenarios.py
```

Build the rendered showcase:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

Run the interactive mission API:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py --cpu-core 0
```

Planner URL:

```text
http://127.0.0.1:8625/planner/index.html
```

Serve the rendered showcase locally:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_showcase.ps1
```

Check runtime readiness:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\check_runtime_readiness.py
```

Attempt a live PX4 snapshot after SITL is running:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\check_live_px4_snapshot.py
```

## WSL Setup

### Verify WSL

```powershell
wsl -l -v
```

Expected baseline:
- Ubuntu on WSL2

### PX4 Simulator Dependencies

From Ubuntu WSL:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
bash ./Tools/setup/ubuntu.sh --no-nuttx
```

This installs:
- PX4 general build dependencies
- Python dependencies
- Gazebo Harmonic simulation dependencies

Verify Gazebo:

```bash
gz sim --versions
```

Observed validated result on this workstation:
- `8.11.0`

### PX4 Submodules

Bootstrap PX4 submodules:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
git submodule sync --recursive
git submodule update --init --recursive
```

If the simulator models submodule becomes mismatched or dirty, repair it with:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
git submodule update --init --force Tools/simulation/gz
```

If the build cache is stale after simulator changes:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
make distclean
```

Then rerun the recursive submodule update.

## PX4 SITL Commands

### Direct WSL Launch

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
env HEADLESS=1 make px4_sitl gz_x500
```

Windy world:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
PX4_GZ_WORLD=windy env HEADLESS=1 make px4_sitl gz_x500
```

### PowerShell Wrapper

Default:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_px4_sitl_wsl.ps1
```

Specific model and world:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_px4_sitl_wsl.ps1 -Model gz_x500 -World windy
```

## WSL MAVLink Bridge

PX4 SITL runs inside WSL2, so its MAVLink localhost ports are not directly visible to Windows-host tools.

Use the bridge below to forward both channels to the Windows host:

```powershell
wsl bash -lc "python3 /mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/wsl_mavlink_bridge.py"
```

The bridge auto-detects the Windows host IP from the WSL default gateway and forwards:
- offboard `14540 <-> 14580`
- GCS `14550 <-> 18570`

### Background Launch

Start PX4 SITL in the background with logs:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\start_px4_sitl_wsl_background.ps1
```

Stop PX4 SITL and Gazebo processes in WSL:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\stop_px4_sitl_wsl.ps1
```

### One-Command Live Probe

Canonical local validation path on this workstation:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_probe.ps1
```

Direct WSL equivalent:

```bash
bash /mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/live_px4_probe.sh
```

This command:
- kills stale host-side `mavsdk_server` processes
- launches PX4 SITL in WSL
- starts the WSL MAVLink bridge
- captures a live Windows-host MAVSDK snapshot
- writes logs and artifacts

### One-Command Live Mission Validation

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
```

This command reuses the same bridge-backed launch path and validates:
- live connection
- geofence upload
- mission upload
- artifact generation at [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)

### One-Command Live Execution Validation

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_execution_validation.ps1
```

This command reuses the same bridge-backed launch path and validates:
- live connection
- geofence upload
- mission upload
- arm
- mission start
- live mission-mode snapshot
- RTL
- artifact generation at [latest_execution_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_execution_validation.json)

### One-Command Live Precision Landing Profile

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_precision_landing_profile.ps1
```

This command reuses the bridge-backed launch path and validates:
- live PX4 connection
- precision-landing parameter application
- read-back verification
- artifact generation at [latest_precision_landing_profile.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_precision_landing_profile.json)

### One-Command Live LANDING_TARGET Stream

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_stream.ps1
```

This command reuses the bridge-backed launch path and validates:
- MAVLink 2 `LANDING_TARGET` sample generation
- projected-approach source generation from simulated pose plus vision/range observation
- auto-detection of the WSL bridge IP from the Windows host
- live packet transmission into the PX4 GCS bridge port
- artifact generation at [latest_landing_target_stream.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_stream.json)
- bridge-log evidence of GCS `host->px4` traffic

### One-Command Live LANDING_TARGET Consumption Proof

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_consumption.ps1
```

This command launches PX4 SITL plus the WSL MAVLink bridge, then validates:
- host-side GCS-link priming
- host-side heartbeat reception on `14550`
- `MAV_CMD_SET_MESSAGE_INTERVAL` ack for `LANDING_TARGET`
- live `LANDING_TARGET` injection on the GCS bridge path
- receiver-side decode evidence inside PX4
- artifact generation at [latest_landing_target_consumption.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_consumption.json)

Current caveat:
- the proof currently depends on temporary receiver instrumentation in [mavlink_receiver.cpp](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/mavlink/mavlink_receiver.cpp)
- this is intentional until the logging/replay path exposes the same publication cleanly without instrumentation

### One-Command Live Dock Approach Validation

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
```

This command launches PX4 SITL plus the WSL MAVLink bridge, then validates:
- live mission upload and arm/start path
- mission departure away from the configured dock origin
- RTL return into the configured dock-approach window
- live MAVSDK local-NED pose plus yaw capture
- projection of the configured dock target into live `LANDING_TARGET` messages
- receiver-side decode evidence in PX4 from the same run
- artifact generation at [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json)

Current caveats:
- the evidence path still depends on temporary receiver instrumentation in [mavlink_receiver.cpp](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/mavlink/mavlink_receiver.cpp)
- the dock target is currently the configured home-origin dock, not a live marker detector output

### One-Command Interactive Mission Execution

This path is used by the planner UI and can also be run directly:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_interactive_mission.py --mission-spec D:\downloads\SeniorProject\Skylink2\artifacts\planner\job_cache\<job-id>\mission_request.json
```

This command launches PX4 SITL plus the WSL MAVLink bridge, then:
- uploads planner-defined waypoints
- validates preflight weather against the baseline
- injects a time-varying live weather profile during flight
- proves weather-triggered RTL
- waits for dock-safe weather recovery
- runs projected `LANDING_TARGET` streaming for the dock approach
- rebuilds the replay bundle
- rebuilds the showcase output

## Artifacts And Evidence

### Scenario Evidence

- Directory: [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest)
- Files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest/summary.md)

### Runtime Checks

- Directory: [runtime_checks](/D:/downloads/SeniorProject/Skylink2/artifacts/runtime_checks)
- Latest report: [latest.md](/D:/downloads/SeniorProject/Skylink2/artifacts/runtime_checks/latest.md)

### SITL Logs

- Directory: [sitl_logs](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs)

### PX4 Bootstrap Logs

- Directory: [px4_bootstrap](/D:/downloads/SeniorProject/Skylink2/artifacts/px4_bootstrap)

### Live PX4 Snapshot

- Output target: [latest_snapshot.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_snapshot.json)
- Mission/geofence validation target: [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)
- Mission execution validation target: [latest_execution_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_execution_validation.json)
- Live weather validation target: [latest_live_weather_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_live_weather_validation.json)
- Precision landing profile target: [latest_precision_landing_profile.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_precision_landing_profile.json)
- LANDING_TARGET stream target: [latest_landing_target_stream.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_stream.json)
- LANDING_TARGET consumption proof target: [latest_landing_target_consumption.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_consumption.json)
- Dock-approach validation target: [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json)
- Latest validated live probe log: [live_probe_20260401_152903.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_152903.log)
- Latest validated bridge log: [live_probe_20260401_152903_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_152903_bridge.log)

### Precision Landing Evidence

- Directory: [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest)
- Files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest/summary.md)

### Replay Bundle Evidence

- Directory: [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest)
- Files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/summary.md)
  - [dock_approach_timeline.csv](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/dock_approach_timeline.csv)

### Rendered Showcase Evidence

- Directory: [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest)
- Files:
  - [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html)
  - [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json)

### Planner Artifact

- Planner page: [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/planner/index.html)

### Mega-Dashboard Artifact

- Dashboard page: [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/dashboard/index.html)
- Dashboard data: [dashboard_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/dashboard/dashboard_data.json)

### Optional Media Bindings

- Drop zone: [README.md](/D:/downloads/SeniorProject/Skylink2/artifacts/media/latest/README.md)

### Weather Scenario Evidence

- Directory: [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest)
- Files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest/summary.md)

## Known Reproduction Hazards

### 1. Dirty `Tools/simulation/gz` Submodule

Symptom:
- `ninja: error: unknown target 'gz_x500'`

Cause:
- PX4 simulator models submodule at the wrong revision or in a dirty state

Fix:
- force-update `Tools/simulation/gz`
- if needed, `make distclean`
- rerun recursive submodule bootstrap

### 2. Long First-Time PX4 Build

Symptom:
- first `make px4_sitl gz_x500` can exceed normal interactive timeout budgets

Fix:
- treat first build as a long-running bootstrap step
- keep logs
- rerun once the build directory exists and simulator targets are visible in `ninja -t targets`

### 3. Host Python Pollution

Rule:
- use `autonomy/.venv` for `mavsdk`
- do not rely on global Python packages for PX4 gateway validation

### 4. Windows To WSL UDP Boundary

Symptom:
- Windows-host MAVSDK probe can fail to bind or connect even when PX4 SITL is healthy inside WSL

Fix:
- run [wsl_mavlink_bridge.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/wsl_mavlink_bridge.py)
- or use [run_live_px4_probe.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_probe.ps1), which starts the bridge automatically

## Current Baseline Validation Commands

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_safety_scenarios.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_precision_landing_scenarios.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_weather_gate_scenarios.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\check_runtime_readiness.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_dashboard.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_probe.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_execution_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_precision_landing_profile.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_stream.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_consumption.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
```

## Reproducing The Live Mega-Dashboard

### 1. Start The API And Unified Dashboard

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py
```

Open:

- `http://127.0.0.1:8625/`

The root route redirects to the live Mega-Dashboard at:

- `/dashboard/index.html`

### 1a. CPU Core Isolation Defaults

The validated default topology on this workstation is:

- API / Uvicorn:
  - Core `0`
- companion FPV logger:
  - Core `1`
- live execution / PX4 orchestration:
  - Cores `2,3`

Direct examples:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py --cpu-core 0
python D:\downloads\SeniorProject\Skylink2\autonomy\companion\video_logger.py --mock-mavlink --mock-camera --stream --cpu-core 1
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_interactive_mission.py --mission-spec D:\downloads\SeniorProject\Skylink2\artifacts\planner\job_cache\<job-id>\mission_request.json --cpu-cores 2,3
```

Graceful fallback rule:

- if `psutil` or host affinity support is unavailable, the runtime prints an `[AFFINITY] warning ...` line and continues unpinned instead of aborting execution

### 2. Planner / Dashboard Payload Contract

`POST /api/mission/execute` accepts:

- waypoint list
- cruise speed
- `environment.wind_speed_mps`
- `environment.wind_direction_deg`
- `environment.gust_multiplier`
- `battery.initial_battery_percent`
- `battery.rtl_battery_threshold_percent`

These values are translated into the live PX4 SITL override plan before launch.

### 3. SSE Streams

- `/api/system/logs`
  - raw runner, PX4, bridge, and validator log stream for the terminal HUD
- `/api/telemetry/live`
  - live `gps_info`, `local_pose`, `attitude_euler`, and battery data for the Leaflet map and Three.js scene

Implementation note:

- the API now preserves telemetry even when upstream runner lines are label-prefixed
- log and telemetry buffers are bounded in memory so long live runs do not retain unbounded event history

### 4. HTTP Smoke Test Reference

The latest verified API smoke result is stored at:

- [mission_api_http_smoke_result.json](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/mission_api_http_smoke_result.json)

It proves:

- `/api/mission/validate` accepts live environment and battery overrides
- `/api/mission/execute` launches a real PX4 SITL validation run
- `/api/system/logs` emits metadata immediately
- `/api/telemetry/live` emits real telemetry frames before job completion
- the live run finishes successfully and rebuilds replay/showcase/dashboard artifacts

## Simulation Launcher and Full-Trip Calibration

### One-command simulation stack

To restore the pre-dashboard “bring the sim back” path, run:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_simulation.ps1 `
  -Host 127.0.0.1 -Port 8625 `
  -StartMockFpv `
  -FpvPort 5050 `
  -ApiCpuCore 0 `
  -VideoCpuCore 1
```

This script:
- starts the companion MJPEG logger in mock mode pinned to Core 1
- launches `mission_api.py` pinned to the chosen API core
- optionally opens the dashboard in your default browser

### Battery / weather controls

The planner/dashboard buttons now expose the entire battery chain that also feeds PX4:

- `battery.initial_battery_percent`
- `battery.warn_battery_threshold_percent`
- `battery.rtl_battery_threshold_percent`
- `battery.emergency_battery_threshold_percent`
- `battery.low_battery_action` (`warning`, `land`, `return`)

These values flow through `interactive_mission.py` into both the validation rules and `px4_sim_overrides.py` via `BAT_LOW_THR`, `BAT_CRIT_THR`, and `BAT_EMERGEN_THR`. Launch tests now enforce strict ordering (initial &gt; warn &gt; RTL &gt; emergency) so the dashboard mirrors the simulator limits.

### Full trip mode

The new planner toggle posts `weather_profile_mode = "full_trip"` instead of the default `proof` mode. In this mode, the live SITL runner generates a gentle weather waveform that stays safely below the abort threshold, so you can simulate full missions without the forced RTL that the proof mode uses to demonstrate weather-triggered recovery. Drop the toggle back to `Proof RTL` when you want to show the safety-carrier abort behavior again.

## Refreshing Judge-Facing 3D Showcase Inputs

Use this sequence whenever the 3D showcase needs fresh live mission geometry or fresh aircraft attitude:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

Expected artifacts after refresh:
- [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)
- [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json)
- [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/manifest.json)
- [dock_approach_timeline.csv](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/dock_approach_timeline.csv)
- [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html)
- [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json)

Validation expectation:
- `showcase_data.json` should contain a top-level `flight_telemetry` array
- mission artifact should contain `mission.waypoints_local`
- dock artifact should contain `attitude_euler`

## Source Documents

- [system_baseline.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/system_baseline.md)
- [execution_model.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/execution_model.md)
- [architecture_decisions.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/architecture_decisions.md)
- [installation_log.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/installation_log.md)
- [milestone_results.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/milestone_results.md)
