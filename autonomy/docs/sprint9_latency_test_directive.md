# Codex Directive: Sprint 9 Latency Protocol

**From:** Project Manager  
**To:** Codex  
**Priority:** FINAL SIMULATION MILESTONE  

---

## Objective
The codebase is structurally complete. CPU isolation is active, the UI is decoupled from the physics thread, and FPV MJPEG rendering is robust. 
According to the `Autonomous Drone Pothole Inspection – Full Build Guide`, we are sitting at the climax of Sprint 9: 
> "Time the full pipeline to verify ≤ 5 min latency... SITL mission → telemetry log → YOLO detect (mocked) → dashboard".

We need a mathematically rigorous test script to validate this latency constraint before we transition the codebase to the physical Raspberry Pi hardware in Sprint 10.

## Action Required
Create a continuous integration / validation script `autonomy/scripts/run_sprint9_latency_test.py`.

This script must:
1. Boot the `execute_interactive_mission.py` flow.
2. Monitor the `video_logger.py` background process (or emulate the telemetry generation).
3. Validate that a full simulated run of the primary Geofence space correctly drops the `telemetry_log.csv` payload and returns to RTL mode successfully.
4. Utilize `time.time()` to strictly measure the entire execution bounds. If the complete physics run and API evaluation takes longer than `300 seconds` (5 minutes), the script must forcefully fail the run.
5. Record the final latency output into a summary artifact at `artifacts/live_px4/sprint9_latency_results.txt`.

Do not exit the process until you have run this test, and the CSV/latency artifacts prove that the system is officially Sprint 10 hardware-ready!
