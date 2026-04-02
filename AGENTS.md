# AGENTS.md - SkyLink Autonomous Drone System

This file provides guidance for agentic coding assistants operating in the Skylink2 repository.

## Project Overview

**Skylink2** is an integrated autonomous drone docking and inspection system for smart city monitoring in Saudi Arabia.

**Key Components:**
- PX4 SITL + MAVSDK-Python autonomy stack
- Custom Three.js WebGL + Leaflet "Mega-Dashboard" (DO NOT replace with Foxglove)
- SSE-based live telemetry streaming (DO NOT modify - already complete)
- Raspberry Pi companion hardware layer with GPIO/camera/MAVLink
- Precision landing with ArUco markers + LANDING_TARGET MAVLink streaming

## Repository Structure

```
Skylink2/
├── drone_platform/          # GitHub-facing entry for drone stack
├── autonomy/                 # Core autonomy code (PRIMARY FOCUS)
│   ├── drone_system/         # Core modules: config, models, safety_engine, mission_control
│   ├── scripts/              # mission_api.py, build_*.py, run_*.py, validate_*.py
│   ├── tests/                # 26+ unittest test files
│   ├── companion/            # Pi-facing hardware layer (GPIO, camera, FPV)
│   └── docs/                 # Milestones, runbooks, directives, system_baseline.md
├── artifacts/                # Generated evidence (dashboard, showcase, replay_bundle, live_px4)
├── model_server/             # Road inspection API (legacy)
├── vendor/                   # PX4-Autopilot, MAVSDK-Python checkouts
└── examples/                 # Static example media
```

## Build/Lint/Test Commands

### Autonomy Unit Tests

```powershell
# Full test suite (all tests)
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"

# Single test file
python -m unittest D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_safety_engine.py

# Single test method
python -m unittest D:\downloads\SeniorProject\Skylink2\autonomy\tests\test_safety_engine.SafetyEngineTests.test_preflight_rejects_high_wind

# Companion tests
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\companion\tests -p "test_*.py"
```

### Artifact Build Commands

```powershell
# Build replay bundle
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py

# Build showcase
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py

# Build dashboard
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_dashboard.py

# Scenario artifacts
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_safety_scenarios.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_precision_landing_scenarios.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_weather_gate_scenarios.py
```

### Runtime/Validation Commands

```powershell
# Mission API (dashboard backend) - already has SSE streaming, DO NOT modify
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\mission_api.py --cpu-core 0

# Runtime readiness check
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\check_runtime_readiness.py

# PX4 SITL validation (PowerShell scripts)
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_probe.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1

# Full simulation with dashboard
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_simulation.ps1 -Host 127.0.0.1 -Port 8625 -StartMockFpv
```

## Code Style Guidelines

### Imports

```python
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .config import SystemBaseline  # Relative imports within drone_system
from autonomy.drone_system.models import Waypoint  # Cross-module imports
```

**Order**: `__future__` → stdlib → third-party → local imports (relative where applicable)

### Type Annotations

- Use `from __future__ import annotations` for forward references
- Always include return type annotations on functions/methods
- Use `| None` syntax (Python 3.10+) not `Optional[]`

```python
def parse_cpu_cores(raw: str | Iterable[int] | int | None, *, default: Iterable[int] | None = None) -> list[int]:
```

### Data Classes

Use frozen dataclasses for immutable data models:

```python
@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    alt_m: float
```

### Enums

Inherit from both `str` and `Enum` for serialization-friendly enums:

```python
class VehicleMode(str, Enum):
    DISCONNECTED = "disconnected"
    MISSION = "mission"
    RETURN_TO_LAUNCH = "return_to_launch"
```

### Constants

Use SCREAMING_SNAKE_CASE and group in module-level sets for validation:

```python
WEATHER_PROFILE_MODE_PROOF = "proof"
WEATHER_PROFILE_MODE_FULL_TRIP = "full_trip"
SUPPORTED_WEATHER_PROFILE_MODES = {
    WEATHER_PROFILE_MODE_PROOF,
    WEATHER_PROFILE_MODE_FULL_TRIP,
}
```

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Classes/Dataclasses | PascalCase | `MissionSafetyEngine`, `VehicleSnapshot` |
| Functions/Methods | snake_case | `validate_mission_request`, `assess_preflight` |
| Constants | SCREAMING_SNAKE_CASE | `MAX_OPERATING_WIND_MPS`, `BATTERY_RTL_PERCENT` |
| Private members | _leading_underscore | `_baseline`, `_run()` |
| Type variables | PascalCase | `T`, `Any` |

### Error Handling

- Use `ValueError` for invalid arguments/validation failures
- Catch specific exceptions, not bare `Exception`
- Provide context in error messages using f-strings with formatted values

```python
try:
    validate_mission_request(request, self._baseline)
except ValueError as exc:
    reasons.append(SafetyReason.MISSION_INVALID)
    details.append(str(exc))
```

### Optional Dependencies

Wrap optional imports with graceful fallbacks:

```python
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore
```

### Async Code

Use `asyncio.run()` for async test helpers:

```python
async def _run() -> None:
    gateway = InMemoryVehicleGateway(self.baseline)
    await gateway.connect()
    # ...

asyncio.run(_run())
```

### Control Flow

Prefer early returns and simple conditionals over deeply nested logic. The codebase uses explicit if/else chains rather than reducing everything to single expressions.

## Testing Patterns

### Test Class Structure

```python
class SafetyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = load_system_baseline()
        self.engine = MissionSafetyEngine(self.baseline)
        # ... fixtures

    def test_preflight_rejects_high_wind(self) -> None:
        decision = self.engine.assess_preflight(self.snapshot, self.request, wind_mps=8.0)
        self.assertEqual(decision.action, SafetyAction.ABORT_LAUNCH)
        self.assertIn(SafetyReason.WIND_LIMIT_EXCEEDED, decision.reasons)
```

### Path Setup for Imports

Test files must add `REPO_ROOT` to `sys.path`:

```python
AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
```

### Dataclass Test Fixtures

Use `replace()` to create modified test fixtures:

```python
snapshot = replace(self.snapshot, battery_percent=20.0, armed=True, in_air=True)
```

## Key System Constraints (from system_baseline.md)

These values are **frozen** and enforced in tests (`test_baseline_config.py`):

| Parameter | Value |
|-----------|-------|
| Mission radius | 100 m |
| Cruise speed | 3-7 m/s |
| RTL battery | 20% |
| Max wind | 7 m/s |
| Landing accuracy | <= 0.4 m |
| Charging power | 50 W |

Any change to these values requires updating both `config/system.toml` AND the corresponding test.

## Safety-Critical Code Areas

The following modules contain safety-critical logic - changes require extra validation:

1. **safety_engine.py** - RTL, battery thresholds, wind limits
2. **mission_control.py** - Waypoint validation, radius/altitude/speed enforcement
3. **geofence.py** - 100m operational boundary
4. **interactive_mission.py** - Battery chain, weather profiles
5. **precision_landing_px4.py** - Landing parameter application

## ARCHITECTURE CONSTRAINTS (DO NOT MODIFY)

### Dashboard Stack - PROTECTED
- **DO NOT** integrate Foxglove Studio. We have a custom Three.js WebGL + Leaflet Mega-Dashboard built over Milestones 20-23.
- **DO NOT** replace or rebuild the SSE pipeline in `mission_api.py`. It is complete and CPU-isolated to core 0.
- Any visualization work must inject into the existing `artifacts/dashboard/index.html` without breaking CSS flexboxes or FPV layouts.

### CPU Affinity Topology - PROTECTED
- API/Uvicorn: Core 0
- FPV logger: Core 1
- Live execution: Cores 2,3

Use `runtime_affinity.py` helpers. Always wrap affinity calls with graceful fallbacks.

## Hardware Transition (HITL)

### Mock vs Hardware Mode

**Simulation Mode (default):**
- MAVSDK: `udpin://0.0.0.0:14540`
- Camera: Mock or GStreamer from Gazebo
- GPS: Simulated by SITL

**Hardware Mode (production):**
- MAVSDK: `/dev/ttyAMA0` baud=57600 (Pixhawk TELEM2)
- Camera: `cv2.VideoCapture(0)` or GStreamer pipeline
- GPS: Holybro M10 (real hardware)
- GPIO: RPi.GPIO (real pins via `gpio_charging.py`)

See `autonomy/docs/hitl_integration_guide.md` for full transition procedure.

## Artifacts/Evidence

Generated files under `artifacts/` are **committed** as they are part of the evidence build:

- `artifacts/dashboard/index.html` - Live Mega-Dashboard
- `artifacts/planner/index.html` - Interactive mission planner
- `artifacts/showcase/latest/index.html` - Judge-facing replay
- `artifacts/replay_bundle/latest/` - Flight telemetry evidence
- `artifacts/live_px4/latest_*.json` - PX4 validation snapshots

After changes affecting UI, telemetry, or visual templates, rebuild artifacts:
```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_dashboard.py
```

## Important Docs

- `autonomy/docs/system_baseline.md` - Frozen system values (source of truth)
- `autonomy/docs/milestone_results.md` - Implementation progress and evidence
- `autonomy/docs/reproducibility_runbook.md` - Complete environment setup
- `autonomy/docs/opencode_realignment_directive.md` - Current sprint constraints
- `drone_platform/EVIDENCE.md` - Current validated state summary
