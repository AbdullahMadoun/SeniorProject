# Showcase Visual Overhaul Directive

## Problem

The current showcase (`artifacts/showcase/latest/index.html`) looks like a developer debug page — the drone is a dot, the dock is an ellipse, charts are bare SVG lines, and the overall aesthetic is beige placeholder. This is going to judges at a senior project presentation. It must look like a real flight simulation visualization.

## What Must Change

### 1. Capture Full Mission Telemetry (not just 8 dock frames)

The dock approach validator (`validate_live_px4_dock_approach.py`) already captures `mission_entry_observations`, `departure_observations`, `rtl_approach_observations`, and `live_stream.records` — but the showcase only uses the 8 `live_stream.records`.

**Concatenate ALL observation arrays** from `latest_dock_approach_validation.json` into the showcase data:
```python
all_frames = (
    artifact.get("mission_entry_observations", []) +
    artifact.get("departure_observations", []) +
    artifact.get("rtl_approach_window", {}).get("observations", []) +
    artifact.get("live_stream", {}).get("records", [])
)
```

Each frame has `local_pose` with `north_m`, `east_m`, `down_m`, `yaw_deg`. Add `attitude_euler` (roll, pitch) to the telemetry recording if not already present.

### 2. Three.js 3D Flight Visualization

Replace the 2D Canvas isometric view AND SVG plan view with a **Three.js WebGL 3D scene**.

**Import via importmap (no build step, self-contained):**
```html
<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.min.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/"
  }
}
</script>
```

**Scene must include:**
- Ground plane (200m × 200m) with grid lines every 10m
- 100m radius geofence boundary as a translucent ring/cylinder on the ground
- Waypoint markers at each mission waypoint position
- Landing pad at dock position (circular with "H" or crosshair marking)
- Quadcopter drone mesh (central body + 4 arms + 4 rotor discs) — NOT a circle
- Apply roll/pitch/yaw from telemetry to the drone's Euler rotation — drone tilts during flight
- 3D flight path trail, color-coded by mode (blue=mission, orange=RTL, green=dock)
- Dashed vertical line from drone to ground (altitude indicator)
- OrbitControls for camera rotation/zoom
- Ambient + directional lighting with drone shadow on ground
- Dark background (#0a0a1a) with subtle fog

**Animation:**
- Timeline slider drives 3D position
- Play/Pause button with smooth animation
- Speed control (1x, 2x, 4x)
- Camera presets: Top-down, Side, Follow drone, Free orbit
- HUD overlay showing: altitude, speed, mode, battery, dock error

### 3. Dark Mode Premium UI

Replace beige/cream with dark mode:
```css
--bg: #0a0a0f;
--surface: #12121a;  
--border: rgba(255,255,255,0.06);
--text: #e8e8ed;
--accent-primary: #00d4aa;
--accent-secondary: #6366f1;
```

Font: Inter from Google Fonts. Glassmorphism panels. No beige.

### 4. Charts with proper styling

- Dark backgrounds matching theme
- Gradient fills under line charts
- Smooth bezier curves
- Proper axis labels and typography

## What NOT to Change

- `showcase_builder.py` data extraction core logic — extend it, don't rewrite
- `build_showcase.py`, `serve_showcase.py` — keep pipeline
- Test coverage — update tests as needed

## Priority Order

1. Full telemetry in showcase data (concatenate all observation arrays)
2. Three.js 3D scene (hero element, full-width, ~500px tall)
3. Dark mode UI
4. Camera presets + speed controls

## Commands

```powershell
# Rebuild
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py

# Test
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"

# Serve
D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python -m http.server 8888 --directory D:\downloads\SeniorProject\Skylink2\artifacts\showcase\latest
```
