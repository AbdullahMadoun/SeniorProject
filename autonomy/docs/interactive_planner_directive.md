# Codex Directive: Interactive Mission Planner & Hardware Authenticity HUD

**From:** Project Manager  
**To:** Codex  
**Priority:** CRITICAL  
**Date:** 2026-04-01

---

## Problem Statement

The showcase currently visualizes a static, pre-recorded replay bundle. The judges need to see that the system actively enforces safety constraints on new, dynamic missions, and they need **visual proof** that the backend is communicating with the real PX4 SITL emulator (not simulating a fake script).

We are building an **Interactive Mission Planner** that connects a web frontend to a new FastAPI backend. 

---

## Phase 1: Autonomy Mission API (`autonomy/scripts/mission_api.py`)

Create a dedicated FastAPI server that wraps the autonomy stack.

**Requirements:**
- **`GET /api/constraints`**: Returns `SystemBaseline` limits (geofence radius, default cruise speed, max altitude).
- **`POST /api/mission/validate`**: Accepts a JSON list of waypoints. Runs them through `mission_control.validate_mission_request()`. Returns HTTP 200 with success, or HTTP 400 with the exact constraint failure reason (e.g., "Waypoint altitude 40.0 m exceeds 30.0 m").
- **`POST /api/mission/execute`**: Accepts validated waypoints. It should write these waypoints to a temporary cache or override the default `live-sitl-smoke` mission. It then invokes the validation runner (e.g., `run_live_px4_mission_validation_wsl.ps1` or a custom script) as a background subprocess. Returns immediately with a job ID or status.
- **`GET /api/system/logs`**: Use Server-Sent Events (SSE) to stream stdout/stderr from the running SITL subprocess in real-time. This provides the MAVLink terminal string logs perfectly.

---

## Phase 2: Interactive Planner UI (`artifacts/planner/index.html`)

Create a self-contained HTML/CSS/JS web UI for mission planning.

**Visual Aesthetic:**
- Must exactly match the dark-mode premium UI we just built for the showcase (Inter font, glassmorphism, `#0a0a0f` bg).

**Interactive Map (2D Grid / Math based):**
- Draw a large HTML5 Canvas or SVG map.
- Center is `(0,0)` (Home).
- Draw the 100m Geofence as a clear circle.
- Allow clicking to place waypoints (convert canvas pixels to Local NED meters).
- Draw paths connecting waypoints.

**Live Rule Engine Sidebar:**
- Actively validate the waypoints against the backend `/api/mission/validate` endpoint on every click.
- If the backend returns a 400 constraint violation, flash a red alert block in the sidebar (e.g., "Constraint Violated: Max Radius"). Disable the "Execute Mission" button.
- If valid, show green checks for Geofence, Min Waypoints, and Altitude constraints.

---

## Phase 3: Hardware Authenticity HUD

Judges need proof that the emulation is real hardware logic.

**Live MAVLink Console:**
- Make a terminal-style UI block (monospaced font, black background) inside the planner.
- When the user clicks "Execute Mission", connect an `EventSource` to `/api/system/logs`.
- Stream the exact real-time compiler, PX4 boot, MAVSDK connection, and `STATUSTEXT` logs (e.g., `[PX4] Arming...`) directly into this HUD while they wait the ~60 seconds for the SITL flight.
- **Connection Metadata**: Show `Target: udpin://0.0.0.0:14540` and `Status: Bridge Active`.

---

## Phase 4: Execution & Hand-off

- Once the `/api/mission/execute` job completes (the process finishes and the new `latest` replay bundle is written), automatically redirect the user's browser to the 3D showcase `../showcase/latest/index.html` to watch what they just flew!

---

## Phase 5: Gazebo / QGC Media Binding

- The system currently produces data artifacts. We need to optionally bundle video evidence.
- Update the artifact schema so it can reference a recorded video file (e.g., a `.mp4` Gazebo recording or a QGC screen recording).
- Integrate this media directly into the newly built replay bundle so the Showcase UI can elegantly display the video alongside the telemetry.

---

## Phase 6: Live Weather Injection (Next Runtime Milestone)

- The dock validation and mission scripts currently run in a static environment.
- Inject time-varying, dynamic weather streams (real or simulated) into the LIVE SITL validation path.
- Prove that the drone actively parses this weather and executes gating or RTL actions based on real-time environmental changes, capturing this explicitly in the new validations.

---

## Acceptance Criteria

- [ ] New `mission_api.py` FastAPI server written and serves correctly.
- [ ] New `planner/index.html` built with dark-mode matching the showcase.
- [ ] Clicking on the 2D map adds waypoints that are strictly bounded by real backend constraint checks.
- [ ] Violating constraints throws red UI alerts.
- [ ] The "Execute" button runs the physical SITL emission process and streams raw terminal text logs into the UI HUD.
- [ ] Upon completion, seamlessly redirects into the 3D Replay Showcase pipeline.

Keep the pipeline simple and minimal dependencies (no bulky JS frameworks, vanilla JS is fine for the planner UI).
