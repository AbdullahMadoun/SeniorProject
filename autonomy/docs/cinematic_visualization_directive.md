# Codex Directive: Cinematic Visualization Polish

**From:** Project Manager  
**To:** Codex  
**Priority:** HIGH (Presentation Value)  
**Date:** 2026-04-02

---

## Problem Statement

The Unified Mega-Dashboard and hardware integration layers are fully implemented. Before transitioning to physical flight tests, the client requested a massive upgrade to the dashboard's "wow factor" designed specifically for the judges. 

The goal is to upgrade the UI from an engineering tool into a highly dynamic, military-grade Cinematic Ground Control Station by adding live FPV camera ingestion, dynamic 3D ribbons, and Augmented Reality (AR) HUD layers.

**Rule Zero:** DO NOT break the existing layout or SSE telemetry stability. Add these visual layers natively on top of the established `dashboard_builder.py` output.

---

## Strict Rule: Simulation as Ground Truth (No Fake Data)

The simulation runs must be 100% rigorous and verifiable enough to entirely replace the physical system for judging. 
- **NO UI TRICKERY:** The 3D Trajectory ribbon, AR HUD, and pitch/roll reactions MUST mathematically consume the real underlying `attitude_euler` and `local_pose` data streaming from the MAVLink SITL engine. You cannot use randomized data, "smooth" animations, or fake physics interpolations.
- **HONEST FPV:** The FPV MJPEG stream during testing must ideally pipe real frame data (from Gazebo via GStreamer, or raw camera inputs), not looping static stock footage unless strictly constrained by the environment. The visual reactions must demonstrably prove the MAVLink control loop is functioning.

---

## Phase 1: Live FPV MJPEG Stream (`autonomy/companion/video_logger.py`)

- Upgrade the Companion Logger so that alongside writing to disk, it exposes a lightweight `Flask` or `http.server` route (e.g., `http://<ip>:5050/stream`) that emits a raw `multipart/x-mixed-replace` MJPEG stream of the OpenCV frames.
- **Dashboard UI Update:** Add a new video `<img src="http://.../stream">` pane to `dashboard_template.html`. When in simulation, it proxies local streams; when on hardware, it routes to the companion Pi IP.

---

## Phase 2: Dynamic 3D Trajectory Ribbon (Three.js)

- **Mechanic:** In the Three.js 3D scene, push the drone's position vectors into an array to draw a trailing, glowing 3D Line/Ribbon.
- **Visual Power:** The material color of the ribbon MUST change dynamically based on the drone's struggle against wind forces. For example, use the SSE `attitude_euler` stream — if the pitch or roll goes beyond a normal threshold (e.g., >15 degrees indicating it is fighting strong injected wind), transition the ribbon color from a cool blue to a bright cautionary red.

---

## Phase 3: Cinematic Orbit Camera

- Replace or augment the static `OrbitControls` in the Three.js scene. 
- Build a toggleable "Cinematic Mode" in the UI. When engaged, the Three.js camera slowly orbits the drone automatically, but swoops in tighter if the drone engages an aggressive pitch against the wind, or when altitude gets incredibly low (touchdown).

---

## Phase 4: AR Diagnostic HUD Overlays

- In the Three.js scene (or rendered dynamically over the FPV video pane), inject floating Augmented Reality metrics:
  - Draw a dynamic Pitch/Roll ladder (Artificial Horizon style).
  - Draw a scrolling compass text tape based on the Yaw.
  - Optional: pulse a circular "Radar Ping" on the Leaflet 2D Map if the hardware mockup indicates a pothole was spotted.

---

## Acceptance Criteria

- [ ] `video_logger.py` updated to non-blockingly broadcast an MJPEG stream that the dashboard consumes.
- [ ] 3D Trajectory ribbon implemented; successfully morphs to red when the drone pitch spikes from injected weather.
- [ ] Cinematic auto-pan camera button added and working in Three.js.
- [ ] The dashboard retains its dark-mode aesthetic, now featuring high-impact visual tech-demo flair.
