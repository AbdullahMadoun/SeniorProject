# Codex Directive: CPU Core Isolation & HUD UI Cleanup

**From:** Project Manager  
**To:** Codex  
**Priority:** BLOCKER (Performance & Polish)  

---

## 1. CPU Core Isolation (Affinity) - CRITICAL
Running the Mega-Dashboard API, the SITL physics executor, and the Companion MJPEG Video Logger simultaneously causes severe CPU contention. The intensive OpenCV compression loops starve the FastAPI/MAVLink polling threads, causing the API server to crash under load.

You need to implement programmatic CPU Affinity (using the `psutil` library) across the three critical application pillars, guaranteeing they are physically pinned to distinctly separated CPU cores.

- **Dependency Injection:** Add `psutil` as a requirement if not already present.
- **Affinity Helper:** Create a graceful helper function `enforce_cpu_affinity(core_id: int)`. If it throws an exception (unsupported architectures), `try/except` gracefully with a console warning.
- **App 1 (mission_api.py):** Pin the FastAPI Uvicorn process to Core `0`. Add `--cpu-core` argument.
- **App 2 (video_logger.py):** Pin the heavy MJPEG OpenCV loop to Core `1` so it can't kill the API. Add `--cpu-core` argument.
- **App 3 (execute_interactive_mission.py):** Pin the MAVSDK physical execution to Cores `2` and `3`.

---

## 2. FPV HUD Artifact Cleanup
Milestone 22 successfully stabilized the sidebar and map. However, the FPV Camera HUD inside the 3D scene is a sloppy, heavily overlapping mess:
- The "FPV stream offline" text prints forcefully directly over the PITCH and ROLL numbers.
- The "HEADING 098 deg" strings crash into the UI components.
- The broken `alt` text from the `<img>` tag spills out when the image stream is offline.

**Action:** Re-write the CSS bounds for the FPV HUD specifically in `dashboard_template.html`. Separate the telemetry overlay (Pitch/Roll/Heading text) from the video stream layer using clear flex barriers or explicit z-index/top placements so the words never collide with each other. If the `<img>` fails to load, gracefully hide its broken HTML alt text.
