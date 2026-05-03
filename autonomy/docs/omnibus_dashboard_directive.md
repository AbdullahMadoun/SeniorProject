# Codex Directive: Unified Live Mission Dashboard (Mega-Dashboard)

**From:** Project Manager  
**To:** Codex  
**Priority:** CRITICAL  
**Date:** 2026-04-01

---

## Problem Statement

The showcase and planner are currently separate pages. The client wants a unified **Single-Pane-of-Glass Ground Control Station** that merges planning, active environmental controls (Weather/Battery), 2D real-world mapping (GPS tracking), and live 3D physics rendering into a single live dashboard.

We must upgrade our `mission_api.py` to stream live telemetry, allowing the 2D map and 3D WebGL scene to run concurrently *during* the SITL flight, not just in post-flight replays.

---

## Phase 1: API Upgrades (`autonomy/scripts/mission_api.py`)

- **Live Telemetry Stream:** Build a new endpoint `GET /api/telemetry/live` using Server-Sent Events (SSE). While SITL is running, stream high-frequency data: `local_pose`, `gps_info` (Lat/Lon/Alt), `attitude_euler` (Roll/Pitch/Yaw), and `battery` to the browser.
- **Dynamic Override Execution:** Update `POST /api/mission/execute` to accept a payload containing:
  - `wind_speed_mps`, `wind_direction_deg`, `gust_multiplier`
  - `initial_battery_percent`, `rtl_battery_threshold`
  - The Python server must inject these via PX4 SITL MAVSDK commands (`param set SIM_WIND_SPD`, etc., or directly via configuration injection) *before* the drone launches.

---

## Phase 2: Master Dashboard Structure (`artifacts/dashboard/index.html`)

Create a pristine, dark-mode mega-dashboard UI (using glassmorphism and the Inter font, matching our premium aesthetic).

**Layout:**
1. **Left Side Panel (Environmental Control Center):**
   - Editable sliders for **Weather** (Wind speed, direction, gust magnitude).
   - Editable sliders for **Battery Policy** (Starting %, RTL Limit %).
   - A big "Launch Live Simulator" button.
   - The MAVLink Terminal HUD (scrolling text log we built previously).
2. **Top Right Panel (2D Real-world Map):**
   - Must use **Leaflet.js** (load CSS and JS from unpkg/CDN via `<script>`).
   - Center map on the Home GPS coordinate (Use the actual SITL origin `47.3979, 8.5461` or allow custom override).
   - Show the 100m geofence as a real drawn polygon/circle.
   - Click-to-place waypoints on the satellite/map tiles. 
   - A dedicated Drone Icon that tracks `gps_info` live during flight.
3. **Bottom Right Panel (Live 3D Telemetry Viewer):**
   - Migrate the existing **Three.js WebGL scene** here.

---

## Phase 3: The Live Sync Architecture

This is the most critical feature. The UI must not wait for the flight to finish.
When the user clicks "Launch Live Simulator":
1. POST the waypoints, weather config, and battery config to `/api/mission/execute`.
2. Disable map editing.
3. Open the `/api/telemetry/live` SSE stream.
4. **2D Sync:** Continuously update the Leaflet Drone Marker's Latitude/Longitude position on the geographic map based on the live stream.
5. **3D Sync:** Continuously update the Three.js Quadcopter's 3D grid `Position` and `Rotation (Euler Attitude)` based on the live stream. If the user set high wind, the 3D scene should visibly show the drone tilting to fight the wind while navigating the grid.

---

## Phase 4: Synchronized Visual Proof (Media Binding)

- The dashboard must support pre-recorded visual proof (e.g. Gazebo or QGC .mp4 renders).
- Provide a clear instruction or script that adds recorded video paths into `artifacts/media/latest/README.md`.
- Ensure the build script reads this README so the dashboard correctly loads and carries the bound recordings as synchronized visual proof.

---

## Phase 5: Version Control Checkpoint

- Commit all changes made during this milestone.
- Add a descriptive commit message.
- Push the milestone to the GitHub repo to ensure the newest live dashboard is backed up.

---

## Acceptance Criteria

- [ ] New `artifacts/dashboard/index.html` built, combining controls, Leaflet 2D, and Three 3D.
- [ ] Backend `/api/mission/execute` successfully accepts weather/battery mutation prior to flight.
- [ ] Backend `/api/telemetry/live` reliably streams fast-update real flight data.
- [ ] Visual checks: Click waypoints on a real Leaflet map, set a 10m/s wind limit, launch. Both the 2D Tracker and 3D Model must accurately navigate and animate *during* the flight execution in unison.

Do not use heavy node frameworks (React, etc.). Keep it vanilla JS/HTML for maximum portability and no-build-step simplicity.
