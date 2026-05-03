# Autonomy Stack

This subsystem is the new flight/autonomy workstream for the real PX4-based system.

It is intentionally separated from the earlier demo-oriented inspection stack. The goal here is
to build a simulation-first backbone that can later connect to PX4 hardware with minimal rewrite.

## Current Focus

- Full-system scope definition for drone autonomy, simulation, docking, telemetry, and cloud services
- Locked software baseline from the project report and confirmed hardware
- Simulation-first validation with recorded evidence
- Reusable control path across emulator, PX4 SITL, and real PX4 hardware

## Initial Deliverables

- `config/system.toml`
- `docs/system_baseline.md`
- `docs/execution_model.md`
- `docs/architecture_decisions.md`
- `docs/installation_log.md`
- `docs/milestone_results.md`
- `docs/reproducibility_runbook.md`
- `../deploy/simulation/README.md`
- `drone_system/config.py`
- `drone_system/geofence.py`
- `drone_system/interactive_mission.py`
- `drone_system/landing_target_projection.py`
- `drone_system/landing_target_stream.py`
- `drone_system/landing_target_proof.py`
- `drone_system/live_px4_runtime.py`
- `drone_system/media_binding.py`
- `drone_system/replay_bundle.py`
- `drone_system/mission_control.py`
- `drone_system/precision_landing.py`
- `drone_system/precision_landing_px4.py`
- `drone_system/scenario_runner.py`
- `drone_system/safety_engine.py`
- `drone_system/showcase_builder.py`
- `drone_system/runtime_affinity.py`
- `drone_system/vehicle_interface.py`
- `drone_system/weather_gate.py`
- `drone_system/weather_scenario_runner.py`
- `drone_system/geometry.py`
- `drone_system/synthetic_telemetry.py`
- `drone_system/capability_report.py`
- `drone_system/dashboard_builder.py`
- `drone_system/dashboard_template.html`
- `drone_system/visualizer_app.py`
- `scripts/check_phase0_capability.py`
- `scripts/check_live_px4_snapshot.py`
- `scripts/check_runtime_readiness.py`
- `scripts/build_dashboard.py`
- `scripts/build_latest_replay_bundle.py`
- `scripts/build_showcase.py`
- `scripts/execute_interactive_mission.py`
- `scripts/generate_synthetic_telemetry.py`
- `scripts/live_px4_probe.sh`
- `scripts/mission_api.py`
- `scripts/run_live_interactive_mission.py`
- `scripts/run_precision_landing_scenarios.py`
- `scripts/run_weather_gate_scenarios.py`
- `scripts/run_live_px4_execution_validation.ps1`
- `scripts/run_live_px4_dock_approach_validation.ps1`
- `scripts/run_live_px4_landing_target_consumption.ps1`
- `scripts/run_live_px4_landing_target_stream.ps1`
- `scripts/run_live_px4_mission_validation.ps1`
- `scripts/run_live_px4_precision_landing_profile.ps1`
- `scripts/run_live_px4_probe.ps1`
- `scripts/run_live_px4_snapshot_wsl.ps1`
- `scripts/run_live_px4_mission_validation_wsl.ps1`
- `scripts/run_live_px4_landing_target_consumption_linux.sh`
- `scripts/run_live_px4_probe_linux.sh`
- `scripts/run_live_px4_mission_validation_linux.sh`
- `scripts/run_live_px4_execution_validation_linux.sh`
- `scripts/run_live_px4_precision_landing_profile_linux.sh`
- `scripts/run_live_px4_landing_target_stream_linux.sh`
- `scripts/run_live_px4_dock_approach_validation_linux.sh`
- `scripts/run_px4_sitl_wsl.ps1`
- `scripts/run_safety_scenarios.py`
- `scripts/run_showcase.ps1`
- `scripts/start_px4_sitl_wsl_background.ps1`
- `scripts/stop_px4_sitl_wsl.ps1`
- `scripts/validate_live_px4_mission.py`
- `scripts/validate_live_px4_execution.py`
- `scripts/validate_live_px4_dock_approach.py`
- `scripts/configure_live_px4_precision_landing.py`
- `scripts/prove_live_px4_landing_target_consumption.py`
- `scripts/stream_live_px4_landing_target.py`
- `scripts/run_visualizer.ps1`
- `scripts/serve_showcase.py`
- `scripts/wsl_mavlink_bridge.py`

## Source Of Truth

The current software-side source of truth is `docs/system_baseline.md`.

The current execution and validation model is `docs/execution_model.md`.

The selected upstream stack and architecture decisions are recorded in `docs/architecture_decisions.md`.

Implementation progress and milestone evidence are recorded in `docs/milestone_results.md`.

Environment setup and exact reproduction steps are recorded in `docs/reproducibility_runbook.md`.

Date-stamped installation and execution history is recorded in `docs/installation_log.md`.

## Live Operator Surfaces

- `artifacts/planner/index.html`
  - interactive 2D mission planning
  - Leaflet + Esri World Imagery satellite basemap
  - Python-backed constraint validation
- `artifacts/showcase/latest/index.html`
  - replay and evidence presentation
- `artifacts/dashboard/index.html`
  - unified live Mega-Dashboard
  - Leaflet 2D GPS map with Esri World Imagery satellite basemap
  - Three.js live 3D telemetry scene
  - telemetry-driven cinematic orbit camera and wind-load trajectory ribbon
  - AR-style FPV HUD with companion MJPEG stream proxy
  - CPU-isolated API, SITL execution, and FPV logging paths
  - live environmental overrides
  - SSE log HUD and live telemetry feed

Run the dashboard/API locally with:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py --cpu-core 0
```

Then open:

- `http://127.0.0.1:8625/`

That file resolves contradictions between:

- the corrected report narrative in `D:\\downloads\\SeniorProject\\info.txt`
- older appendix tables
- hardware decisions already made by the team

If another note or older draft conflicts with the baseline, treat it as obsolete until the baseline is explicitly revised.

## Validation Strategy

Development is staged by dependency:

- emulator first
- PX4 SITL next
- real PX4 hardware after software proof exists

This laptop is sufficient for local control logic, replay tooling, and lightweight simulation support.
Heavier 3D simulation and cloud execution remain part of the system scope, but they should be treated as remotely runnable workloads rather than the default local loop.
