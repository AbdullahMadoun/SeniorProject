dfd# SkyLink Milestone Results

This file is the running communication and showcase record for implementation progress.

It captures each milestone with:

- objective
- implemented files
- validation evidence
- current gaps
- next step

## Milestone 1: Vehicle Interface Foundation

Date:
- `2026-03-31`

Objective:
- establish the first real control-layer foundation for the project
- stop the codebase from coupling mission logic directly to one-off scripts
- create a single interface that can target emulator now and PX4/MAVSDK next

Implemented:
- typed baseline loader in [config.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/config.py)
- mission request definition and validation in [mission_control.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/mission_control.py)
- typed vehicle state models in [models.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/models.py)
- abstract vehicle gateway plus emulator and MAVSDK adapter in [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py)

What works now:
- project config loads from the frozen baseline instead of ad hoc constants
- mission requests are validated against the frozen radius, altitude, and speed limits
- an in-memory vehicle can execute the nominal control flow:
  - connect
  - upload mission
  - arm
  - start mission
  - advance mission
  - RTL
  - land
- MAVSDK/PX4 adapter is scaffolded around the real upstream plugin flow instead of a fake custom protocol

Validation evidence:
- unit and contract tests cover:
  - config loading
  - nominal mission validation
  - speed rejection
  - mission-radius rejection
  - in-memory vehicle command flow
- full autonomy suite status:
  - `python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 10 tests ... OK`

Result:
- vehicle-interface foundation is in place and testable
- mission and safety logic can now be written against this contract instead of directly against simulator-specific code

Known gaps:
- MAVSDK adapter has not yet been exercised against a live PX4 SITL instance
- geofence upload is not wired yet
- snapshot coverage does not yet include rich mission progress from PX4
- no scenario runner exists yet

Next milestone:
- build the mission and safety engine on top of this interface
- add geofence handling, battery/RTL policy logic, and preflight mission validation rules

## Milestone 2: Mission And Safety Engine

Date:
- `2026-03-31`

Objective:
- move from simple control plumbing to enforceable flight-policy logic
- make launch, continue, RTL, and emergency-land decisions deterministic and testable

Implemented:
- safety policy engine in [safety_engine.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/safety_engine.py)

What works now:
- preflight assessment checks:
  - vehicle connectivity
  - mission validity
  - wind operating limit
  - battery telemetry presence
  - battery launch readiness
- in-flight assessment checks:
  - wind excursion
  - battery warning threshold
  - battery RTL threshold
  - battery emergency-land threshold
- gateway-aware enforcement can now:
  - command RTL when policy requires it
  - command immediate landing on emergency battery state

Validation evidence:
- policy tests cover:
  - preflight high-wind rejection
  - preflight low-battery warning
  - in-flight RTL at the configured threshold
  - in-flight emergency landing at the configured threshold
  - actual emulator mode transition when enforcement triggers RTL

Result:
- the project now has a deterministic safety core instead of informal threshold handling
- mission execution can be built on top of policy decisions with explicit reason codes

Known gaps:
- geofence upload and enforcement are not wired yet
- telemetry-loss policy still needs a dedicated connection-failure scenario harness
- wind currently enters as a scenario input, not a live SITL subscription

Next milestone:
- bind this control and safety path to a live PX4 SITL run
- add geofence generation/upload and scenario-runner infrastructure

## Milestone 3: Geofence And Scenario Evidence Harness

Date:
- `2026-03-31`

Objective:
- move from isolated policy tests to reproducible scenario evidence
- encode the 100 m operating boundary as a real control-layer artifact
- produce showcase-grade summaries from scripted runs

Implemented:
- geofence model in [geofence.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/geofence.py)
- geofence upload support in [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py)
- scenario harness in [scenario_runner.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/scenario_runner.py)
- scenario execution script in [run_safety_scenarios.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_safety_scenarios.py)

What works now:
- the vehicle contract can store or upload a home-centered geofence
- scripted scenarios can run against the emulator and emit evidence artifacts
- the current harness proves three concrete cases:
  - nominal preflight readiness
  - high-wind launch rejection
  - low-battery RTL transition

Validation evidence:
- full autonomy suite status:
  - `python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 18 tests ... OK`
- artifact generation status:
  - `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_safety_scenarios.py`
  - wrote artifacts to [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest)
- generated files:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest/manifest.json)
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/scenario_runs/latest/summary.md)

Observed results:
- `scenario_count = 3`
- `passed_count = 3`
- `high_wind_abort_launch` correctly produced `wind_limit_exceeded`
- `low_battery_rtl` correctly produced `battery_rtl_threshold`

Result:
- the project now has a repeatable evidence path, not just raw tests
- milestone output can already be shown to reviewers as a proof artifact for core safety behavior

Known gaps:
- scenarios are still emulator-backed, not yet PX4 SITL-backed
- geofence upload is integrated in code but not yet validated against live PX4 SITL
- landing and docking scenarios are not part of the harness yet

Next milestone:
- bind the current vehicle, safety, and geofence path to live PX4 SITL
- add scenario coverage for landing, precision-landing preparation, and richer mission progress logging

## Milestone 4: PX4 Runtime Readiness And Live-Binding Blocker Isolation

Date:
- `2026-03-31`

Objective:
- determine whether this workstation can move from emulator-backed proof into live PX4 SITL binding
- avoid pretending SITL integration is ready when the runtime is not

Implemented:
- runtime probe script in [check_runtime_readiness.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/check_runtime_readiness.py)
- WSL PX4 launcher wrapper in [run_px4_sitl_wsl.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_px4_sitl_wsl.ps1)
- isolated autonomy virtual environment at `autonomy/.venv`

Observed environment results:
- WSL2 is available
- Ubuntu is available
- PX4 vendored repo is accessible from WSL
- WSL has:
  - `python3`
  - `make`
  - `cmake`
- host-side autonomy virtual environment now has `mavsdk`
- Gazebo Harmonic is installed in WSL:
  - `gz sim --versions -> 8.11.0`
- PX4 SITL build directory is present
- PX4 SITL binary is present:
  - `build/px4_sitl_default/bin/px4`

Validation evidence:
- runtime report generated at [latest.md](/D:/downloads/SeniorProject/Skylink2/artifacts/runtime_checks/latest.md)
- report confirms:
  - `venv_mavsdk = yes`
  - `wsl_available = yes`
  - `px4_repo_in_wsl = present`
  - `gazebo_status = harmonic`
  - `px4_target_status = present`
  - `px4_binary_status = present`

Result:
- the Python and WSL sides are prepared for live binding
- the repo now has a truth-based runtime probe instead of a stale environment assumption
- the remaining work moved from environment bootstrap into live SITL validation

Known gaps:
- no live PX4 SITL session has been launched yet
- no live MAVSDK snapshot has been taken yet
- no Gazebo-based precision-landing scenario has been executed yet

Next milestone:
- launch PX4 SITL from WSL
- connect the existing MAVSDK gateway to the live vehicle endpoint
- record the first live artifact and document the remaining transport constraints

## Milestone 5: Live PX4 SITL Launch And First Snapshot

Date:
- `2026-03-31`

Objective:
- move from “runtime is ready” to “live simulator is running and emitting telemetry”
- prove the existing gateway can read from a real PX4 SITL instance without changing the control abstractions
- capture the first artifact that can be shown as evidence

Implemented:
- corrected battery normalization and connection-timeout handling in [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py)
- extended snapshot probe in [check_live_px4_snapshot.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/check_live_px4_snapshot.py)
- improved WSL launcher in [run_px4_sitl_wsl.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_px4_sitl_wsl.ps1)
- added background launcher in [start_px4_sitl_wsl_background.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/start_px4_sitl_wsl_background.ps1)
- added WSL snapshot wrapper in [run_live_px4_snapshot_wsl.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_snapshot_wsl.ps1)
- added WSL stop wrapper in [stop_px4_sitl_wsl.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/stop_px4_sitl_wsl.ps1)

What works now:
- PX4 SITL launches headless from the repo through the WSL wrapper
- Gazebo launches with the default world and `gz_x500`
- PX4 exposes the expected SITL UDP sockets in WSL:
  - `14580` offboard local
  - `18570` GCS local
  - `14280` onboard payload local
  - `13030` gimbal local
- the WSL-side MAVSDK probe connects to the live PX4 instance and writes a real snapshot artifact
- the live snapshot now reports sane battery units after adapter correction

Validation evidence:
- runtime report:
  - [latest.md](/D:/downloads/SeniorProject/Skylink2/artifacts/runtime_checks/latest.md)
- live snapshot artifact:
  - [latest_snapshot.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_snapshot.json)
- latest validated SITL launcher log directory:
  - [20260331_220715](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/20260331_220715)
- latest generated PX4 ULog:
  - [18_58_46.ulg](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/build/px4_sitl_default/rootfs/log/2026-03-31/18_58_46.ulg)
- live-path tests:
  - `python -m unittest D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_vehicle_interface.py D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_runtime_readiness.py`
  - `Ran 8 tests ... OK`

Observed live results:
- snapshot system address: `udpin://0.0.0.0:14540`
- connected: `true`
- armed: `false`
- in_air: `false`
- mode: `hold`
- battery_percent: `100.0`
- position populated from live telemetry

Result:
- live PX4 SITL proof is now in the repo
- the mission/safety stack has crossed from emulator-only validation into real simulator telemetry
- the repo now contains reproducible commands to start, stop, and probe the live stack

Known gaps:
- the canonical successful live probe is currently WSL-local, not Windows-local
- the Windows-side probe can still hit UDP bind/connect issues across the WSL boundary
- mission upload/start has not yet been validated against the live SITL instance
- geofence upload has not yet been validated against the live SITL instance
- precision-landing behavior has not yet been simulated end-to-end

Next milestone:
- validate mission upload and start against live PX4 SITL
- validate live geofence upload and policy-triggered RTL
- formalize the precision-landing simulation path on top of the live SITL backbone

## Milestone 6: Live Mission And Geofence Upload Smoke Validation

Date:
- `2026-03-31`

Objective:
- prove that the live SITL path supports control-plane writes, not only telemetry reads
- upload a real geofence and a bounded survey mission through the existing abstraction layer
- record the result as a repeatable artifact

Implemented:
- live mission validation script in [validate_live_px4_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_mission.py)
- WSL wrapper in [run_live_px4_mission_validation_wsl.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_mission_validation_wsl.ps1)
- live snapshot mission-progress support in [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py)

What works now:
- a 100 m home-centered geofence uploads to the live PX4 SITL instance
- a six-waypoint lawnmower survey mission uploads to the live PX4 SITL instance
- the upload script uses the live simulator home position instead of assuming the report baseline home
- survey area validation now uses a real boundary polygon instead of the zig-zag path itself

Validation evidence:
- live mission validation artifact:
  - [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)
- validated command:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation_wsl.ps1`
- test status:
  - `python -m unittest D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_vehicle_interface.py D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_runtime_readiness.py D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_geofence.py`
  - `Ran 11 tests ... OK`

Observed live results:
- mission id: `live-sitl-smoke`
- waypoint count: `6`
- cruise speed: `5.0 m/s`
- validated survey area: about `400.0 m^2`
- validated spans:
  - north: about `20.0 m`
  - east: about `20.0 m`
- post-upload live state:
  - connected: `true`
  - armed: `false`
  - mode: `hold`

Result:
- the live stack now proves both read-path and write-path connectivity to PX4 SITL
- geofence and mission upload are no longer emulator-only capabilities
- the repo contains a repeatable artifact for live mission configuration against the simulator

Known gaps:
- arm/start/execute has not yet been validated against the uploaded mission
- live mission progress remains `0/0` until active mission execution is exercised
- policy-triggered RTL against live SITL is not yet proven
- precision landing still needs its dedicated simulation path

Next milestone:
- validate arm and mission start against live PX4 SITL
- validate policy-triggered RTL against the live stack
- begin the precision-landing simulation implementation path

## Milestone 7: WSL MAVLink Bridge And Windows-Host Live Probe

Date:
- `2026-03-31`

Objective:
- remove the unstable WSL2 networking assumptions from the live validation path
- make the Windows-host MAVSDK probe reproducible against PX4 SITL
- collapse SITL launch, MAVLink routing, and live snapshot capture into one command

Implemented:
- WSL MAVLink bridge in [wsl_mavlink_bridge.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/wsl_mavlink_bridge.py)
- end-to-end live probe in [live_px4_probe.sh](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/live_px4_probe.sh)
- Windows wrapper in [run_live_px4_probe.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_probe.ps1)
- installation history log in [installation_log.md](/D:/downloads/SeniorProject/Skylink2/autonomy/docs/installation_log.md)

What works now:
- PX4 SITL can be launched from a clean state with one command
- a WSL-side UDP bridge forwards:
  - offboard `14540 <-> 14580`
  - GCS `14550 <-> 18570`
- the Windows-host MAVSDK probe succeeds on the default `udpin://0.0.0.0:14540` address once the bridge is up
- the live probe script now handles:
  - stale host MAVSDK server cleanup
  - stale SITL process cleanup
  - SITL launch
  - bridge launch
  - snapshot capture

Validation evidence:
- one-command probe:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_probe.ps1`
- live SITL log:
  - [live_probe_20260331_221838.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260331_221838.log)
- bridge traffic log:
  - [live_probe_20260331_221838_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260331_221838_bridge.log)
- live snapshot:
  - [latest_snapshot.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_snapshot.json)
- full regression status:
  - `python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 23 tests ... OK`

Observed live results:
- `connected = true`
- `mode = hold`
- `battery_percent = 100.0`
- `position.lat = 47.3979711`
- `position.lon = 8.5461637`
- `position.alt_m = 0.030000001192092896`
- bridge logs show active MAVLink packets on both offboard and GCS channels

Result:
- the live SITL path is now reproducible from the Windows host, not only from inside WSL
- the repo contains the exact routing code needed to make host-side MAVSDK and later QGroundControl feasible on WSL2
- the project can move forward into live mission execution and geofence enforcement without revisiting baseline setup

Known gaps:
- QGroundControl still needs a manual connection validation through the bridge
- live arm/start/execute is not yet part of the one-command probe
- precision landing is still pending on the live stack

Next milestone:
- validate QGroundControl through the bridge
- validate live arm/start and mission progress
- begin the precision-landing simulation implementation on the live path

## Milestone 8: Live Mission Execution And RTL Smoke Validation

Date:
- `2026-04-01`

Objective:
- prove that the bridge-backed Windows-host path can do more than upload mission state
- validate live arm, mission start, active mission mode, and RTL on PX4 SITL
- record the result as a reproducible artifact instead of a one-off console session

Implemented:
- Windows-host mission validation wrapper in [run_live_px4_mission_validation.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_mission_validation.ps1)
- Windows-host execution validation wrapper in [run_live_px4_execution_validation.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_execution_validation.ps1)
- live execution validator in [validate_live_px4_execution.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_execution.py)

What works now:
- one command launches PX4 SITL in WSL, starts the MAVLink bridge, and executes the live validation on the Windows host
- the live stack now proves:
  - connect
  - geofence upload
  - mission upload
  - arm
  - mission start
  - live `mission` mode
  - RTL command acceptance
- the execution path reuses the same vehicle abstraction used by emulator and earlier SITL probes

Validation evidence:
- mission upload artifact:
  - [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json)
- live execution artifact:
  - [latest_execution_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_execution_validation.json)
- latest validated SITL execution log:
  - [live_probe_20260401_112126.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_112126.log)
- latest validated bridge log:
  - [live_probe_20260401_112126_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_112126_bridge.log)

Observed live results:
- initial state:
  - `connected = true`
  - `armed = false`
  - `mode = hold`
- mission-phase snapshot:
  - `armed = true`
  - `in_air = true`
  - `mode = mission`
  - `battery_percent = 98.0`
- post-RTL snapshot:
  - `mode = return_to_launch`
  - `in_air = true`
  - altitude above home consistent with climb-out during RTL

Result:
- live PX4 SITL execution is now proven from the Windows host through the bridge-backed path
- the project has crossed from read/upload-only SITL validation into real mission-state transitions
- the repo now contains a repeatable artifact for arm, mission start, and RTL

Known gaps:
- QGroundControl still needs explicit bridge validation
- mission progress remains coarse in the current smoke validator
- precision landing is not yet connected to the live SITL stack

Next milestone:
- implement the precision-landing control subsystem
- generate deterministic landing evidence with target-loss safety cases
- prepare the adapter path toward PX4 `LANDING_TARGET`

## Milestone 9: Precision Landing Controller And Scenario Evidence

Date:
- `2026-04-01`

Objective:
- turn precision landing into an implemented subsystem instead of a baseline statement
- model the final docking segment around camera-marker observations plus range sensing
- produce replayable evidence for nominal touchdown and target-loss safety behavior

Implemented:
- precision-landing controller and simulator in [precision_landing.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/precision_landing.py)
- artifact generator in [run_precision_landing_scenarios.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_precision_landing_scenarios.py)
- controller and artifact tests in [test_precision_landing.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_precision_landing.py)

What works now:
- the controller converts camera angular error plus range into a relative landing-target estimate
- touchdown logic is staged across:
  - align
  - descend
  - flare
  - touchdown
- marker loss is treated as a real safety condition:
  - short loss causes hold/reacquire
  - sustained loss causes abort
- the simulator emits scenario steps that can later feed judge-facing replay views

Validation evidence:
- precision-landing artifact directory:
  - [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest)
- summary:
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest/summary.md)
- manifest:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/precision_landing/latest/manifest.json)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 29 tests ... OK`

Observed results:
- `scenario_count = 3`
- `passed_count = 2`
- `nominal_precision_touchdown` passed with touchdown phase reached
- `short_target_loss_reacquire` passed after reacquiring the marker
- `sustained_target_loss_abort` failed intentionally with `target_lost_timeout`

Result:
- precision landing is now represented by real code and deterministic evidence, not only by documentation
- the subsystem is structured to stay compatible with a future PX4 `LANDING_TARGET` adapter while remaining honest about the current simulator boundary
- the repo now has a dedicated landing-safety artifact path for showcase and regression use

Known gaps:
- the current simulator models the landing-target estimate and vehicle response, but does not yet inject `LANDING_TARGET` into live PX4 SITL
- the tag family and camera calibration path are not frozen yet
- the judge-facing replay UI for landing evidence is still pending

Next milestone:
- build the PX4 precision-landing adapter path around `LANDING_TARGET`
- connect landing evidence to live SITL or a higher-fidelity simulated landing world
- add replay packaging for mission + landing in one bundle

## Milestone 10: Live PX4 Precision Landing Profile Validation

Date:
- `2026-04-01`

Objective:
- connect the simulated landing subsystem to real PX4 precision-landing configuration
- make the required PX4 parameters reproducible and verified against live SITL
- avoid a gap between controller tuning in repo code and autopilot configuration on the vehicle side

Implemented:
- PX4 precision-landing profile builder in [precision_landing_px4.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/precision_landing_px4.py)
- live profile configurator in [configure_live_px4_precision_landing.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/configure_live_px4_precision_landing.py)
- bridge-backed wrapper in [run_live_px4_precision_landing_profile.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_precision_landing_profile.ps1)
- unit tests in [test_precision_landing_px4.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_precision_landing_px4.py)

What works now:
- the repo can derive a PX4 precision-landing parameter profile from the frozen docking baseline and current landing-controller tuning
- the profile can be applied to live PX4 SITL from the Windows host through the existing WSL bridge path
- every applied parameter is read back and written to an artifact for auditability

Validation evidence:
- live precision-landing profile artifact:
  - [latest_precision_landing_profile.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_precision_landing_profile.json)
- latest validated SITL profile log:
  - [live_probe_20260401_113645.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_113645.log)
- latest validated bridge log:
  - [live_probe_20260401_113645_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_113645_bridge.log)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 31 tests ... OK`

Observed live results:
- `RTL_PLD_MD = 2`
- `LTEST_MODE = 1`
- `PLD_HACC_RAD = 0.4`
- `PLD_BTOUT = 2.0`
- `PLD_FAPPR_ALT = 1.2`
- `PLD_MAX_SRCH = 3`

Result:
- the precision-landing stack now spans:
  - frozen requirement baseline
  - controller logic
  - deterministic simulator evidence
  - live PX4 parameter configuration
- the repo now has a credible bridge from simulated landing behavior toward PX4-native precision landing

Known gaps:
- the live path still configures PX4 but does not yet stream `LANDING_TARGET` messages into SITL
- landing-marker detection and vehicle-local-frame conversion are not yet wired into the live simulator
- a combined mission-plus-landing replay package is still pending

Next milestone:
- implement the `LANDING_TARGET` publisher path for live SITL
- validate target visibility loss and recovery behavior against PX4 precision-landing modes
- package mission execution and docking evidence into one replay bundle

## Milestone 11: Live MAVLink 2 LANDING_TARGET Publisher Path

Date:
- `2026-04-01`

Objective:
- move from PX4 precision-landing parameter configuration into live landing-target message injection
- prove the repo can generate and transmit MAVLink 2 `LANDING_TARGET` messages into the offboard bridge path
- keep the evidence honest by distinguishing packet transmission from downstream PX4 response validation

Implemented:
- MAVLink 2 landing-target sample builder and publisher in [landing_target_stream.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_stream.py)
- live stream script in [stream_live_px4_landing_target.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/stream_live_px4_landing_target.py)
- bridge-backed wrapper in [run_live_px4_landing_target_stream.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_landing_target_stream.ps1)
- unit tests in [test_landing_target_stream.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_stream.py)

What works now:
- the repo can build a MAVLink 2 `LANDING_TARGET` stream with:
  - `MAV_FRAME_LOCAL_NED`
  - `position_valid = 1`
  - `LANDING_TARGET_TYPE_VISION_FIDUCIAL`
- the Windows-host publisher auto-detects the WSL bridge IP and sends to the real bridge endpoint instead of localhost
- the live stream path produces an artifact and confirmed offboard `host->px4` packet flow

Validation evidence:
- live stream artifact:
  - [latest_landing_target_stream.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_stream.json)
- latest validated SITL log:
  - [live_probe_20260401_114956.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_114956.log)
- latest validated bridge log:
  - [live_probe_20260401_114956_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_114956_bridge.log)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 33 tests ... OK`

Observed live results:
- stream endpoint:
  - `udpout:172.23.68.199:14540`
- sent count:
  - `50`
- stream rate:
  - `10 Hz` for `5 s`
- bridge evidence:
  - `50` explicit `offboard host->px4` entries
  - packet size observed in the bridge log: `72 bytes`

Result:
- the repo now contains a real MAVLink 2 landing-target publisher path and verified transport into PX4's offboard UDP port
- the precision-landing workstream now spans:
  - baseline
  - controller logic
  - deterministic simulator evidence
  - live PX4 parameter profile
  - live `LANDING_TARGET` transmission path

Known gaps:
- this milestone proves transport, not yet PX4 internal response to the landing-target stream
- the live stream currently sends a stationary dock target and does not yet couple vehicle-relative vision estimates into absolute local-NED target coordinates
- target-loss/reacquisition behavior is not yet exercised against PX4's live landing-target estimator path

Next milestone:
- validate that PX4 consumes the landing-target stream through telemetry or ULog evidence
- couple the simulated vision/range estimate into live local-NED target coordinates
- build the combined mission-plus-docking replay bundle

## Milestone 12: Live LANDING_TARGET Consumption Proof

Date:
- `2026-04-01`

Objective:
- close the gap between confirmed packet transport and confirmed PX4 receiver-side consumption
- build a reproducible validator that distinguishes:
  - bridge delivery into PX4 UDP ports
  - PX4 heartbeat and command responsiveness on the host observer link
  - actual `MavlinkReceiver::handle_message_landing_target()` decode events
- document the remaining difference between:
  - receiver-side absolute-pose handling
  - outbound `LANDING_TARGET` streaming from PX4

Implemented:
- proof helpers in [landing_target_proof.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_proof.py)
- live proof harness in [prove_live_px4_landing_target_consumption.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/prove_live_px4_landing_target_consumption.py)
- one-command wrapper in [run_live_px4_landing_target_consumption.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_landing_target_consumption.ps1)
- stronger unit coverage in:
  - [test_landing_target_proof.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_proof.py)
  - [test_landing_target_stream.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_stream.py)
- temporary receiver instrumentation in [mavlink_receiver.cpp](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/mavlink/mavlink_receiver.cpp)

What works now:
- the host observer primes the PX4 GCS link and receives a real PX4 heartbeat
- the host observer requests `MAV_CMD_SET_MESSAGE_INTERVAL` for `LANDING_TARGET` and receives `COMMAND_ACK result=0`
- the live bridge path confirms:
  - `54` host-to-PX4 packets on the GCS bridge during the proof run
  - `50` nonzero `LANDING_TARGET` samples transmitted from the Windows host
- the instrumented PX4 receiver logs `50` decoded `LANDING_TARGET` packets with:
  - `position_valid = 1`
  - `frame = MAV_FRAME_LOCAL_NED`
  - `x = 1.25`
  - `y = -0.75`
  - `z = 0.0`
- the proof harness writes a stable artifact summarizing:
  - bridge traffic
  - observer heartbeat
  - command ack
  - receiver-side decode count
  - ULog inspection result

Validation evidence:
- live consumption proof artifact:
  - [latest_landing_target_consumption.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_consumption.json)
- latest validated SITL log:
  - [landing_target_consumption_20260401_133803.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/landing_target_consumption_20260401_133803.log)
- latest validated bridge log:
  - [landing_target_consumption_20260401_133803_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/landing_target_consumption_20260401_133803_bridge.log)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 39 tests ... OK`

Observed live results:
- proof status:
  - `consumed`
- bridge host-to-PX4 count:
  - `54`
- receiver decode count:
  - `50`
- first decoded receiver values:
  - `position_valid = 1`
  - `frame = 1`
  - `x = 1.25`
  - `y = -0.75`
  - `z = 0.0`
- observer `SET_MESSAGE_INTERVAL` ack:
  - `command = 511`
  - `result = 0`
- observer outbound `LANDING_TARGET` count:
  - `50`
- ULog result:
  - `landing_target_pose_samples = 0`
  - `irlock_report_samples = 0`

Important interpretation:
- receiver-side consumption is now proven by direct decode evidence in PX4
- the outbound `LANDING_TARGET` stream still shows zero relative-pose fields
- that zero stream is expected from source inspection:
  - [LANDING_TARGET.hpp](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/mavlink/streams/LANDING_TARGET.hpp) emits `x_rel/y_rel/z_rel` and `rel_pos_valid`
  - [mavlink_receiver.cpp](/D:/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot/src/modules/mavlink/mavlink_receiver.cpp) publishes only `x_abs/y_abs/z_abs` and `abs_pos_valid` for this path
- this is an inference from PX4 source, not a guess

Result:
- the repo now has a reproducible live proof that PX4 receives and decodes our injected `LANDING_TARGET` messages on SITL
- the precision-landing path is no longer blocked at “transport only”
- the artifact set now distinguishes:
  - bridge transport
  - host observer responsiveness
  - receiver-side decode
  - absent ULog surfacing

Known gaps:
- the current proof depends on temporary receiver instrumentation in vendored PX4
- `landing_target_pose` still does not surface in the ULog artifact path during this proof run
- the outbound PX4 `LANDING_TARGET` stream is not a faithful mirror of the injected absolute target because it streams relative fields only
- the live path still uses a stationary synthetic dock target, not a vision-derived dynamic local-NED target

Next milestone:
- replace the stationary target with a simulated vision/range estimate converted into live local-NED coordinates
- wire the precision-landing target path into mission completion and dock-approach scenarios
- remove or reduce temporary PX4 receiver instrumentation once a cleaner proof path replaces it

## Milestone 13: Projected-Approach LANDING_TARGET Source

Date:
- `2026-04-01`

Objective:
- replace the hardcoded stationary target source with a more realistic projected approach model
- derive absolute local-NED `LANDING_TARGET` samples from:
  - simulated vehicle local pose
  - simulated vision/range observation
  - body-frame to local-NED projection
- keep the live bridge transport workflow unchanged while improving the meaning of the injected target stream

Implemented:
- projection model in [landing_target_projection.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_projection.py)
- projected-approach mode in [stream_live_px4_landing_target.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/stream_live_px4_landing_target.py)
- unit coverage in [test_landing_target_projection.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_projection.py)

What works now:
- the repo can generate `LANDING_TARGET` samples from a simulated dock-approach geometry instead of an unexplained constant
- the projected-approach source computes:
  - vehicle local pose
  - vision observation angles
  - range-derived relative target
  - projected absolute local-NED dock coordinates
- the live stream script now records the projection preview alongside the transmitted MAVLink samples
- the live transport path still works with the improved source model on the GCS bridge path

Validation evidence:
- refreshed live stream artifact:
  - [latest_landing_target_stream.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_landing_target_stream.json)
- latest validated SITL log:
  - [live_probe_20260401_134311.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_134311.log)
- latest validated bridge log:
  - [live_probe_20260401_134311_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_134311_bridge.log)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 41 tests ... OK`

Observed live results:
- stream endpoint:
  - `udpout:172.23.68.199:14550`
- source mode:
  - `projected_approach`
- projection preview initial vehicle pose:
  - `north = 3.05`
  - `east = -1.85`
  - `down = -8.0`
- projection preview initial observation:
  - `forward_angle_rad = -0.2213`
  - `right_angle_rad = 0.1366`
  - `range_m = 8.0`
- projected target remains consistent:
  - `x = 1.25`
  - `y = -0.75`
  - `z = 0.0`

Result:
- the live target stream is no longer sourced from an unexplained fixed absolute coordinate only
- the repo now contains a reusable projection layer that matches the intended real-system flow:
  - vehicle pose
  - camera/range observation
  - local-NED target publication
- this gives us a better base for coupling precision landing to live telemetry and later judge-facing replay

Known gaps:
- the projected approach still uses a synthetic straight-line pose profile
- the source does not yet consume live vehicle local position from SITL during the stream
- no camera calibration or marker-detection noise model is included yet

Next milestone:
- couple the projected target source to live vehicle telemetry rather than a synthetic pose profile
- drive the projected source from mission-end dock-approach scenarios
- package the dock-approach evidence into replay artifacts for presentation

## Milestone 14: Live Telemetry-Driven Dock Approach Validation

Date:
- `2026-04-01`

Objective:
- replace the synthetic straight-line dock approach with a live PX4 SITL vehicle pose source
- prove one continuous path across:
  - mission launch
  - mission departure from the dock area
  - RTL return toward home
  - live local-NED pose projection into `LANDING_TARGET`
  - receiver-side PX4 decode evidence
- capture the result as a replayable artifact instead of a console-only run

Implemented:
- live local-pose gateway support in [models.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/models.py), [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py), and [config.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/config.py)
- dock-target baseline encoding in [system.toml](/D:/downloads/SeniorProject/Skylink2/autonomy/config/system.toml)
- single-frame projection helpers in [landing_target_projection.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_projection.py)
- single-sample publisher path in [landing_target_stream.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_stream.py)
- live dock-approach validator in [validate_live_px4_dock_approach.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_dock_approach.py)
- bridge-backed wrapper in [run_live_px4_dock_approach_validation.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_px4_dock_approach_validation.ps1)
- evidence-parser hardening in [landing_target_proof.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/landing_target_proof.py)
- regression updates in:
  - [test_vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_vehicle_interface.py)
  - [test_system_config.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_system_config.py)
  - [test_baseline_config.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_baseline_config.py)
  - [test_landing_target_projection.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_projection.py)
  - [test_landing_target_stream.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_stream.py)
  - [test_landing_target_proof.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_landing_target_proof.py)

What works now:
- the gateway can read live PX4 local-NED position plus yaw from MAVSDK instead of relying only on global position
- the dock target is now configured explicitly in the system baseline:
  - `dock_center_north_m = 0.0`
  - `dock_center_east_m = 0.0`
  - `dock_center_down_m = 0.0`
  - `approach_activation_radius_m = 12.0`
  - `landing_target_stream_rate_hz = 5.0`
- the live validator executes a real sequence:
  - connect
  - geofence upload
  - mission upload
  - arm
  - mission start
  - confirm mission departure beyond `5 m`
  - command RTL
  - wait for dock-approach window within `12 m`
  - project dock-relative `LANDING_TARGET` samples from the live SITL local pose
  - verify PX4 receiver-side decode evidence from the same run
- the stream stops after grounded observations instead of continuing indefinitely on the ground

Validation evidence:
- live dock-approach artifact:
  - [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json)
- validated SITL log:
  - [live_probe_20260401_152903.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_152903.log)
- validated bridge log:
  - [live_probe_20260401_152903_bridge.log](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/live_probe_20260401_152903_bridge.log)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 44 tests ... OK`

Observed live results:
- proof status:
  - `consumed_from_live_telemetry_projection`
- mission waypoint count:
  - `6`
- dock-approach activation radius:
  - `12.0 m`
- RTL entry into the approach window:
  - horizontal distance to dock `10.278 m`
  - altitude above dock `23.097 m`
- live projected stream:
  - `8` `LANDING_TARGET` records transmitted on the GCS bridge path
  - `8` GCS `host->px4` bridge events for the stream
  - `8` receiver-side `LANDING_TARGET rx` decode events in PX4 SITL
- final live stream record:
  - `in_air = false`
  - horizontal distance to dock `0.385 m`
  - this is within the frozen landing-accuracy target of `<= 0.4 m`

Important interpretation:
- this milestone is the first one where the projected dock target is driven by live PX4 telemetry instead of a synthetic pose profile
- the validated run itself was successful on the first dock-approach pass
- the evidence parser initially under-reported receiver and bridge counts because:
  - SITL writes wrapped terminal-control sequences into the log
  - the first parser assumed cleaner line boundaries than PX4 actually produced
- the parser was hardened against wrapped log text, and the final artifact was refreshed from the same validated run logs without changing vehicle-side behavior

Result:
- the repo now has a real mission-to-dock proof chain:
  - mission execution
  - RTL return
  - live local-pose-based landing-target projection
  - PX4 receiver-side decode evidence
- precision landing is no longer tied to a synthetic approach source
- the docking path is now grounded in the same live SITL telemetry that later hardware integration will use

Known gaps:
- the current live proof still depends on temporary receiver instrumentation in vendored PX4
- the dock target is fixed at the configured home-origin dock and does not yet consume a real marker detector
- the live validator proves the projected target and vehicle proximity, but it does not yet prove a PX4-native precision-landing state estimate through `landing_target_pose` or ULog
- weather-aware dock-approach gating and judge-facing replay packaging are still pending

Next milestone:
- add a vision-noise and range-noise model on top of the live local-pose dock projection
- package mission, RTL, and dock-approach evidence into one replay bundle
- start the weather-gated mission and docking validation path on the same live SITL backbone

## Milestone 15: Mission-To-Dock Replay Bundle

Date:
- `2026-04-01`

Objective:
- package the current live PX4 evidence into one reproducible bundle for review and judging
- stop forcing reviewers to inspect separate JSON files and SITL logs manually
- create a single artifact set that captures:
  - mission configuration
  - live execution and RTL
  - precision-landing profile
  - landing-target consumption proof
  - live dock approach

Implemented:
- replay-bundle builder in [replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/replay_bundle.py)
- bundle script in [build_latest_replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/build_latest_replay_bundle.py)
- regression coverage in [test_replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_replay_bundle.py)

What works now:
- the repo can collect the latest validated live artifacts into one bundle directory
- the bundle writes:
  - consolidated manifest JSON
  - reviewer-facing Markdown summary
  - dock-approach timeline CSV for plotting or replay tooling
- the bundle normalizes summary values from mixed artifact shapes, including the PX4 precision-profile list format

Validation evidence:
- replay bundle directory:
  - [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest)
- bundle summary:
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/summary.md)
- bundle manifest:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/manifest.json)
- dock-approach timeline:
  - [dock_approach_timeline.csv](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/dock_approach_timeline.csv)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 45 tests ... OK`

Observed bundle results:
- mission waypoint count:
  - `6`
- post-RTL execution mode:
  - `return_to_launch`
- dock proof status:
  - `consumed_from_live_telemetry_projection`
- dock stream record count:
  - `8`
- dock receiver count:
  - `8`
- final dock horizontal distance:
  - `0.3848117764806864 m`
- precision profile:
  - `RTL_PLD_MD = 2`
- landing-target consumption receiver count:
  - `50`
- precision-landing simulator pass count:
  - `2 / 3`

Result:
- the project now has a judge-facing evidence package instead of only low-level artifacts
- mission, RTL, and docking evidence can be reviewed from one directory
- the dock-approach timeline is now available as CSV for future plotting, animation, or browser replay work

Known gaps:
- this is a data bundle, not yet a rendered visual replay application
- weather evidence is still split between the safety harness and the live SITL path
- the bundle currently reflects the latest validated artifacts; it does not yet snapshot them under a date-stamped immutable bundle directory

Next milestone:
- add weather-gated live mission and docking validation on top of the current SITL backbone
- then convert the replay bundle into a rendered showcase layer once the weather path is in place

## Milestone 16: Weather-Gated Mission And Docking Policy Evidence

Date:
- `2026-04-01`

Objective:
- formalize weather gating as a typed subsystem instead of scattered wind checks
- prove launch, inflight continuation, and dock-approach readiness decisions against the frozen wind limit
- feed the resulting evidence back into the replay bundle so the showcase path remains cumulative

Implemented:
- typed weather gate in [weather_gate.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/weather_gate.py)
- weather scenario runner in [weather_scenario_runner.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/weather_scenario_runner.py)
- artifact script in [run_weather_gate_scenarios.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_weather_gate_scenarios.py)
- regression coverage in:
  - [test_weather_gate.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_weather_gate.py)
  - [test_weather_scenario_runner.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_weather_scenario_runner.py)
- replay bundle integration in [replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/replay_bundle.py)

What works now:
- weather gating uses a typed `WeatherReading` with steady wind plus gust values
- the gate evaluates a conservative effective wind:
  - `effective_wind_mps = max(steady_wind_mps, gust_wind_mps)`
- the same configured `7.0 m/s` wind limit now drives:
  - launch readiness
  - inflight mission-continuation allowance
  - dock-approach allowance
- scenario evidence covers:
  - nominal launch and docking readiness
  - gust-front launch abort
  - inflight wind-excursion RTL
  - nominal dock weather during RTL
- the replay bundle now includes the weather scenario manifest and pass count

Validation evidence:
- weather scenario directory:
  - [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest)
- weather summary:
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest/summary.md)
- weather manifest:
  - [manifest.json](/D:/downloads/SeniorProject/Skylink2/artifacts/weather_scenarios/latest/manifest.json)
- updated replay bundle summary:
  - [summary.md](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest/summary.md)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 48 tests ... OK`

Observed results:
- scenario count:
  - `4`
- passed count:
  - `4`
- nominal weather ready:
  - effective wind `4.5 m/s`
  - launch `yes`
  - dock `yes`
- gust abort launch:
  - effective wind `8.2 m/s`
  - launch `no`
  - dock `no`
  - safety action `abort_launch`
- inflight wind excursion:
  - effective wind `8.0 m/s`
  - mission continue `no`
  - safety action `return_to_launch`
  - final mode `return_to_launch`
- replay bundle now reports:
  - weather scenario pass count `4 / 4`

Result:
- weather gating is now an explicit part of the control evidence, not only a report statement
- the project can show reviewers that wind limits affect:
  - launch
  - mission continuation
  - docking readiness
- the replay bundle now captures both the live flight path evidence and the weather-policy evidence in one place

Known gaps:
- this milestone uses synthetic weather readings, not a live upstream weather feed yet
- the live PX4 dock-approach validator does not yet inject a changing weather profile during the same SITL run
- rendered judge-facing visualization of the weather + mission timeline is still pending

Next milestone:
- add a rendered showcase layer on top of the replay bundle
- or inject time-varying weather into the live SITL mission/dock validator, depending on whether presentation or deeper live integration has higher priority

## Milestone 17: Rendered Mission Showcase Layer

Date:
- `2026-04-01`

Objective:
- convert the replay bundle into a judge-facing rendered artifact instead of a folder of raw JSON, CSV, and Markdown
- keep the showcase bound to the validated replay-bundle data instead of inventing synthetic frontend-only state
- present the strongest evidence in the right order:
  - executive proof snapshot
  - mission lifecycle
  - dock approach replay
  - precision landing behavior
  - weather and PX4 proof chain

Implemented:
- showcase builder in [showcase_builder.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/showcase_builder.py)
- build script in [build_showcase.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/build_showcase.py)
- local serve script in [serve_showcase.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/serve_showcase.py)
- local PowerShell launcher in [run_showcase.ps1](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_showcase.ps1)
- regression coverage in [test_showcase_builder.py](/D:/downloads/SeniorProject/Skylink2/autonomy/tests/test_showcase_builder.py)

What works now:
- the repo can render a self-contained HTML showcase directly from the replay bundle
- the showcase writes:
  - [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html)
  - [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json)
- the page contains the current highest-value sections:
  - executive proof snapshot
  - mission lifecycle stages from upload through dock final
  - dock approach replay with:
    - timeline slider
    - plan view
    - isometric dock scene
    - current-frame metrics
  - precision-landing progression chart and scenario table
  - weather gate evidence table
  - PX4 proof and parameter tables
- the showcase is self-contained and does not require Streamlit, pandas, pydeck, or internet access

Validation evidence:
- rendered showcase directory:
  - [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest)
- rendered HTML:
  - [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html)
- normalized showcase data:
  - [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json)
- full regression status:
  - `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`
  - `Ran 51 tests ... OK`

Observed showcase results:
- bundle source:
  - `latest_live_px4_replay_bundle`
- mission lifecycle stages shown:
  - `Before Upload`
  - `After Upload`
  - `Execution Start`
  - `Mission Entry`
  - `RTL Active`
  - `Dock Approach`
  - `Dock Final`
- dock replay uses the current live dock records:
  - `8` replay frames
  - final horizontal distance `0.3848117764806864 m`
- precision section uses:
  - nominal precision-landing step curve
  - `2/3` scenario pass summary
- weather section uses:
  - `4/4` weather scenario pass summary

Result:
- the repo now has a presentation-grade artifact generated from the validated evidence path
- the showcase is portable and suitable for review without requiring a full dev environment
- the project can now move into deeper live integration or richer rendered replay without redoing the data-contract work

Known gaps:
- the showcase is rendered from validated artifacts, not a live-updating dashboard
- the dock replay is a 2.5D/isometric visualization, not a full physics-accurate 3D scene
- no embedded video or Gazebo capture is included yet

Next milestone:
- inject time-varying weather into the live SITL mission and dock validation path
- or add recorded media / richer 3D replay on top of the current showcase artifact

## Milestone 18 - Live Telemetry Refresh For 3D Showcase Fidelity

Objective:
- remove the last inferred pieces from the showcase pipeline
- record real mission waypoint positions for 3D marker placement
- refresh the live dock-approach artifact so the rendered quadcopter uses recorded roll and pitch instead of zeroed placeholders

Implemented:
- mission validation now serializes `mission.waypoints_local` in [validate_live_px4_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_mission.py)
- dock-approach validation now serializes `attitude_euler` alongside each recorded pose in [validate_live_px4_dock_approach.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_dock_approach.py)
- local pose model and gateway now carry roll/pitch in:
  - [models.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/models.py)
  - [vehicle_interface.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/vehicle_interface.py)
- replay timeline CSV now includes recorded attitude fields in [replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/replay_bundle.py)

Executed:
- `D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1`
- `D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1`
- `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py`
- `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py`
- `D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`

Observed result:
- [latest_mission_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_mission_validation.json) now contains explicit `waypoints_local` for all `6` mission waypoints
- [latest_dock_approach_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_dock_approach_validation.json) now contains recorded `attitude_euler` values across mission, RTL, and dock-stream frames
- rebuilt [showcase_data.json](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/showcase_data.json) now contains:
  - `13` unified `flight_telemetry` frames
  - non-zero `roll_deg` / `pitch_deg` values from live telemetry
  - actual mission waypoint positions for the 3D scene
- rebuilt [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html) now renders the drone mesh against refreshed live telemetry instead of inferred placeholders

Validation:
- replay bundle rebuilt successfully in [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest)
- showcase rebuilt successfully in [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest)
- full regression status:
  - `Ran 51 tests ... OK`

Current live evidence values:
- mission waypoint count: `6`
- unified telemetry frames: `13`
- landing-target receiver count: `50`
- dock proof status: `consumed_from_live_telemetry_projection`
- dock final horizontal distance remains within target band in the refreshed showcase output

Result:
- the showcase is now backed by refreshed live mission geometry and refreshed live aircraft attitude
- the remaining gap between validation artifacts and judge-facing 3D presentation has been closed without inventing synthetic frontend state

## Milestone 19 - Interactive Planner, Hardware Authenticity HUD, Media Binding, And Live Weather Injection Pipeline

Objective:
- turn the autonomy stack into an interactive mission product instead of a static replay viewer
- expose the real Python mission constraints over an HTTP API
- bind browser planning to a live SITL execution path with raw stdout/stderr visibility
- extend the replay/showcase artifact chain to carry live weather proof and optional recorded media

Implemented:
- mission API server in [mission_api.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/mission_api.py)
  - `GET /api/constraints`
  - `POST /api/mission/validate`
  - `POST /api/mission/execute`
  - `GET /api/system/logs` as SSE
- local-mission and weather-profile contract in [interactive_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/interactive_mission.py)
- shared live PX4 telemetry/runtime helpers in [live_px4_runtime.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/live_px4_runtime.py)
- live interactive mission runner in [run_live_interactive_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_interactive_mission.py)
- live planner mission validator in [execute_interactive_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/execute_interactive_mission.py)
- media binding discovery in [media_binding.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/media_binding.py)
- planner artifact in [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/planner/index.html)
- replay bundle schema extended in [replay_bundle.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/replay_bundle.py)
- showcase data/template extended for live weather evidence and bound recordings in:
  - [showcase_builder.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/showcase_builder.py)
  - [showcase_template.html](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/showcase_template.html)

Executed:
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py`
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py`
- `python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`

Observed result:
- planner page now exists as a real tracked artifact at [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/planner/index.html)
- planner behavior now includes:
  - click-to-place waypoints on a dark 2D geometric mission map
  - backend validation on every edit
  - red launch lockout on constraint failure
  - terminal HUD fed from `/api/system/logs`
  - automatic redirect into [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest/index.html) after successful execution
- replay bundle now supports:
  - [latest_live_weather_validation.json](/D:/downloads/SeniorProject/Skylink2/artifacts/live_px4/latest_live_weather_validation.json) when generated by the interactive run
  - optional recorded video bindings from [README.md](/D:/downloads/SeniorProject/Skylink2/artifacts/media/latest/README.md)
- showcase now renders:
  - live weather injection chart
  - bound media cards when recordings exist

Validation:
- full regression status:
  - `Ran 57 tests ... OK`
- replay bundle rebuilt successfully in [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/replay_bundle/latest)
- showcase rebuilt successfully in [latest](/D:/downloads/SeniorProject/Skylink2/artifacts/showcase/latest)

Result:
- the repo now contains an end-to-end interactive planning surface tied to the validated autonomy backend
- the judge-facing chain now spans planning, live execution evidence, replay telemetry, live weather proof, and optional recorded media without switching products

## Milestone 20 - Unified Mega-Dashboard, Live Telemetry SSE, And API-Proven Execution

Objective:
- unify planning, live controls, live telemetry, and replay evidence into one operator surface
- prove that the browser-facing API path executes real PX4 SITL missions instead of only rebuilding static artifacts
- make the live API stable enough for repeated dashboard sessions without losing telemetry or retaining unbounded log history

Implemented:
- unified dashboard data builder in [dashboard_builder.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/dashboard_builder.py)
- unified dashboard template in [dashboard_template.html](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/dashboard_template.html)
- dashboard build script in [build_dashboard.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/build_dashboard.py)
- unified live operator artifact in [index.html](/D:/downloads/SeniorProject/Skylink2/artifacts/dashboard/index.html)
- live mission API upgrades in [mission_api.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/mission_api.py)
  - `GET /api/constraints`
  - `POST /api/mission/validate`
  - `POST /api/mission/execute`
  - `GET /api/system/logs`
  - `GET /api/telemetry/live`
  - `GET /api/system/job/{job_id}`
- live execution bridge in [run_live_interactive_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/scripts/run_live_interactive_mission.py)
- planner/weather/battery execution contract in [interactive_mission.py](/D:/downloads/SeniorProject/Skylink2/autonomy/drone_system/interactive_mission.py)

Key runtime fixes:
- telemetry extraction no longer requires `__TELEMETRY__` to begin at column zero
- runner now preserves validator telemetry frames instead of wrapping them with a `[VALIDATOR]` prefix
- mission log and telemetry buffers now roll forward with bounded retention so long runs do not retain unbounded event history in memory

Executed:
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py`
- live HTTP smoke against:
  - `POST /api/mission/validate`
  - `POST /api/mission/execute`
  - `GET /api/system/logs`
  - `GET /api/telemetry/live`
  - `GET /api/system/job/{job_id}`
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py`
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py`
- `python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_dashboard.py`
- `python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"`

Observed result:
- dashboard UI now combines:
  - left environmental control center
  - top-right Leaflet GPS mission map
  - bottom-right Three.js live telemetry scene
- dashboard launch path now posts:
  - waypoint geometry
  - wind speed, wind direction, gust multiplier
  - starting battery percent and RTL threshold
- API path now proves live telemetry arrives during execution, not only after completion
- latest live API smoke artifact written to [mission_api_http_smoke_result.json](/D:/downloads/SeniorProject/Skylink2/artifacts/sitl_logs/mission_api_http_smoke_result.json)
- smoke artifact proves:
  - `validation_valid = true`
  - metadata SSE emitted immediately
  - first telemetry SSE frame included `gps_info`, `local_pose`, `attitude_euler`, and `battery`
  - final job snapshot returned `status = completed`
  - final job snapshot returned `exit_code = 0`
  - final job snapshot returned `telemetry_event_count = 10`
- replay/showcase/dashboard artifacts rebuilt successfully after the live API run

Validation:
- full regression status:
  - `Ran 68 tests ... OK`
- latest live weather proof remains:
  - `proof_status = rtl_triggered_by_live_weather_injection`
- dashboard artifact exists and is rebuildable from tracked scripts

Result:
- the planner and showcase are now unified into a real live Mega-Dashboard instead of separate products
- the browser can drive a real SITL mission with live telemetry feeding both the 2D map and the 3D scene
- the API execution path is now proven, repeatable, and bounded enough to use as the basis for the next hardware-integration phase
