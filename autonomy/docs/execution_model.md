# SkyLink Execution Model

This project is now treated as a full-system software build, not a narrow phase exercise.

All of the following are in scope:

- drone autonomy
- PX4/Pixhawk integration
- SITL and high-fidelity simulation
- docking return and precision landing
- telemetry logging and replay
- judge-facing recorded outputs
- cloud-side orchestration and data services

The work is phased by dependency, not by the old phase labels.

## Workstreams

### 1. Core Flight Interface

Goal:
- establish a single control abstraction that can talk to simulator, PX4 SITL, and real PX4 hardware

Primary outputs:
- connection adapters
- mission upload/start/abort/RTL interface
- telemetry subscription interface
- parameter management helpers

Exit criteria:
- same mission command path works against emulator and PX4 SITL
- connection loss and reconnection are handled deterministically
- QGroundControl can observe the same vehicle state during test runs

### 2. Mission and Safety Engine

Goal:
- own the high-level behavior of the vehicle

Primary outputs:
- preflight validation
- geofence checks
- mission envelope validation
- battery RTL logic
- wind gating
- speed envelope enforcement
- mission monitor loop

Exit criteria:
- invalid mission plans are rejected before upload
- RTL is triggered at configured thresholds
- out-of-envelope conditions cause abort or hold behavior by policy
- all safety decisions are logged with machine-readable reasons

### 3. Docking and Precision Landing

Goal:
- prove autonomous recovery to base, target acquisition, and precise touchdown

Primary outputs:
- dock/base model
- landing target detection path
- range-assisted final descent logic
- lost-target fallback behavior
- landing success/failure classification

Exit criteria:
- vehicle can return to base and land inside the frozen error bound
- target loss behavior is deterministic and tested
- final descent path uses the defined sensing strategy, not a fake teleport or scripted shortcut

### 4. Simulation and Emulation

Goal:
- replace physical flight with defensible software validation

Primary outputs:
- control-unit emulator
- PX4 SITL launch path
- 3D simulation path where feasible
- synthetic telemetry generator
- scripted scenarios for weather, low battery, and docking recovery

Exit criteria:
- core scenarios run reproducibly from scripts
- each scenario emits logs, artifacts, and pass/fail status
- simulator and emulator can both drive the same higher-level mission/safety code

### 5. Telemetry, Logging, and Replay

Goal:
- generate proof, not just console output

Primary outputs:
- structured telemetry logs
- event logs
- mission summary artifact
- replay visualizer inputs
- judge-facing recorded bundles

Exit criteria:
- every scenario produces a replayable artifact set
- logs are timestamped and correlated across subsystems
- replay bundle can show mission path, safety events, and landing outcome after the run is over

### 6. Cloud and Backend Services

Goal:
- support remote orchestration, artifact storage, and later analysis integration

Primary outputs:
- run metadata service
- artifact packaging/upload path
- result manifest format
- remote simulation execution hooks

Exit criteria:
- simulation outputs can be packaged and transferred off-machine
- backend interfaces are versioned and testable locally
- cloud integration is not coupled to a live demo requirement

### 7. Hardware Bring-Up

Goal:
- make the software transferable from SITL to the real drone

Primary outputs:
- PX4 parameter packs
- hardware checklists
- sensor verification utilities
- real-link connection profile

Exit criteria:
- the same mission/safety engine can bind to the real PX4 endpoint
- hardware prerequisites and calibration order are documented
- no simulator-only assumptions remain hidden in the control path

## Quality Gates

No workstream is considered complete without automated or scripted validation.

### Unit Gates

Use for:
- geometry
- mission generation
- safety rule evaluation
- config parsing
- event classification

Requirement:
- deterministic tests with explicit expected outputs

### Integration Gates

Use for:
- mission upload to emulator and SITL
- telemetry capture
- RTL logic
- docking target acquisition pipeline

Requirement:
- scripts return non-zero on failure
- artifact bundle produced on every run

### Scenario Gates

Required baseline scenarios:

1. nominal mission completion
2. low-battery RTL
3. wind rejection before launch
4. wind excursion during mission
5. geofence or area rejection
6. lost-telemetry or connection disruption
7. precision landing success
8. precision landing target-loss fallback

Requirement:
- each scenario has a written pass/fail contract

### Evidence Gates

Every serious run must produce:

- telemetry log
- event log
- configuration snapshot
- mission definition snapshot
- replay manifest
- optional recorded video or simulation capture

If a run cannot be replayed or audited later, it is not accepted as proof.

## Immediate Build Sequence

1. finalize architecture and interfaces
2. implement mission/safety engine against emulator
3. bind the same interfaces to PX4 SITL
4. add docking and precision landing path
5. add scenario runner and replay bundle generation
6. add cloud artifact packaging and remote execution hooks
7. prepare hardware transfer path

## Non-Negotiable Engineering Rules

- no fake success states
- no manual “assume pass” scenario results
- no simulator-only behaviors hidden in production code paths
- no undocumented parameter drift between report, config, and code
- no feature marked complete without a reproducible test path
