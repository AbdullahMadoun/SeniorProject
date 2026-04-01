# SkyLink Installation Log

This file records the actual setup and validation commands executed on this workstation.

## 2026-03-31

### WSL And PX4 Dependencies

Executed in Ubuntu WSL:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot
bash ./Tools/setup/ubuntu.sh --no-nuttx
git submodule sync --recursive
git submodule update --init --recursive
```

Observed result:
- Gazebo Harmonic available via `gz sim --versions`
- PX4 submodules bootstrapped

### Host Python Environment

Executed on Windows host:

```powershell
python -m venv D:\downloads\SeniorProject\Skylink2\autonomy\.venv
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m pip install mavsdk
```

Observed result:
- host-side `mavsdk` available for probe and gateway scripts

### Runtime Readiness

Executed on Windows host:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\check_runtime_readiness.py
```

Observed result:
- WSL2 available
- Gazebo Harmonic `8.11.0` detected
- PX4 build directory present
- PX4 SITL binary present

### PX4 SITL Build

Executed in WSL:

```bash
cd /mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/build/px4_sitl_default
ninja -j2 px4
```

Observed result:
- `build/px4_sitl_default/bin/px4` produced successfully

### Live PX4 Probe

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_probe.ps1
```

Observed result:
- PX4 SITL launched in WSL
- WSL bridge forwarded:
  - offboard `14540 <-> 14580`
  - GCS `14550 <-> 18570`
- live snapshot written to [latest_snapshot.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_snapshot.json)
- live logs written to [sitl_logs](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs)

### Full Test Suite

Executed on Windows host:

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

Observed result:
- `Ran 23 tests ... OK`

## 2026-04-01

### Live Mission Validation Through Windows Host

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
```

Observed result:
- PX4 SITL launched through the WSL bridge-backed harness
- live mission validation artifact refreshed at [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)

### Live Mission Execution Validation Through Windows Host

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_execution_validation.ps1
```

Observed result:
- live execution artifact written to [latest_execution_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_execution_validation.json)
- validated stages:
  - connect
  - initial snapshot
  - geofence upload
  - mission upload
  - arm
  - mission start
  - mission snapshot
  - RTL

### Precision Landing Simulation Evidence

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_precision_landing_scenarios.py
```

Observed result:
- precision landing artifacts written to [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest)
- summary written to [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest/summary.md)
- current scenario result:
  - `2/3` scenarios passed
  - nominal touchdown and short target-loss recovery passed
  - sustained target loss correctly aborted

### Live PX4 Precision Landing Profile

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_precision_landing_profile.ps1
```

Observed result:
- live PX4 precision-landing profile written to [latest_precision_landing_profile.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_precision_landing_profile.json)
- verified applied/read-back parameters include:
  - `RTL_PLD_MD = 2`
  - `LTEST_MODE = 1`
  - `PLD_HACC_RAD = 0.4`
  - `PLD_BTOUT = 2.0`
  - `PLD_FAPPR_ALT = 1.2`
  - `PLD_MAX_SRCH = 3`

### Additional Host Python Dependencies

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m pip install pymavlink
```

Observed result:
- `pymavlink` installed for MAVLink 2 `LANDING_TARGET` publishing

### Live LANDING_TARGET Stream

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_stream.ps1
```

Observed result:
- live stream artifact written to [latest_landing_target_stream.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_stream.json)
- stream used the detected WSL bridge endpoint instead of localhost:
  - `udpout:172.23.68.199:14550`
- stream now defaults to the projected-approach source mode and records the projection preview in the artifact
- bridge log confirmed live GCS-path `host->px4` traffic carrying the MAVLink 2 `LANDING_TARGET` stream
- validated sample rate:
  - `10 Hz` for `5 s`

### Live LANDING_TARGET Consumption Proof

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_landing_target_consumption.ps1
```

Observed result:
- proof artifact written to [latest_landing_target_consumption.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_consumption.json)
- host observer successfully:
  - received PX4 heartbeat on `14550`
  - received `COMMAND_ACK result=0` for `MAV_CMD_SET_MESSAGE_INTERVAL`
- receiver-side proof recorded:
  - `50` decoded `LANDING_TARGET` packets in PX4 SITL
  - first decoded values matched the injected target:
    - `position_valid = 1`
    - `frame = 1`
    - `x = 1.25`
    - `y = -0.75`
    - `z = 0.0`
- current caveat:
  - this proof currently depends on temporary receiver instrumentation in vendored PX4 because `landing_target_pose` still does not surface in the ULog artifact path

### Live Dock Approach Validation

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
```

Observed result:
- live dock-approach artifact written to [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json)
- validated end-to-end live sequence:
  - mission upload
  - arm and mission start
  - departure beyond the dock area
  - RTL approach to the configured dock origin
  - live local-pose-derived `LANDING_TARGET` streaming
  - receiver-side decode evidence in PX4
- validated run summary:
  - `proof_status = consumed_from_live_telemetry_projection`
  - `record_count = 8`
  - `receiver_count = 8`
  - `gcs_host_to_px4_count = 8`
  - final live stream record on ground at about `0.385 m` horizontal distance from dock center
- implementation note:
  - the first dock-approach run exposed a log-parser issue caused by wrapped PX4 terminal output
  - the parser was hardened and the final artifact was refreshed from the same validated run logs without changing the vehicle-side run

### Replay Bundle Packaging

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
```

Observed result:
- replay bundle written to [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest)
- generated files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/summary.md)
  - [dock_approach_timeline.csv](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/dock_approach_timeline.csv)
- bundle summary captured:
  - mission waypoint count `6`
  - dock proof status `consumed_from_live_telemetry_projection`
  - dock receiver count `8`
  - final dock horizontal distance about `0.385 m`
  - precision profile `RTL_PLD_MD = 2`

### Weather Gate Scenario Evidence

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_weather_gate_scenarios.py
```

Observed result:
- weather scenario artifacts written to [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest)
- summary written to [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest/summary.md)
- validated scenario set:
  - `nominal_weather_ready`
  - `gust_abort_launch`
  - `inflight_wind_excursion_rtl`
  - `nominal_dock_weather_ready`
- pass count:
  - `4/4`
- replay bundle refreshed afterward so the weather evidence is included in [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/summary.md)

### Rendered Showcase Build

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

Observed result:
- rendered showcase written to [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest)
- generated files:
  - [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html)
  - [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json)
- current showcase includes:
  - executive proof snapshot
  - mission lifecycle stages
  - dock approach replay
  - precision landing behavior summary
  - weather gate evidence
  - PX4 parameter/proof chain tables
- rendered data reflects the current validated bundle:
  - dock proof `consumed_from_live_telemetry_projection`
  - final dock error about `0.385 m`
  - weather pass count `4/4`

### Full Test Suite

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

Observed result:
- `Ran 51 tests ... OK`

### Live Showcase Telemetry Refresh

Executed on Windows host:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

Observed result:
- [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json) refreshed with `waypoints_local`
- [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json) refreshed with per-frame `attitude_euler`
- [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json) rebuilt with:
  - `13` flight telemetry frames
  - non-zero `roll_deg` and `pitch_deg`
  - actual waypoint marker coordinates
- [dock_approach_timeline.csv](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/dock_approach_timeline.csv) rebuilt with attitude columns
