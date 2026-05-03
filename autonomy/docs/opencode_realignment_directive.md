# Project Realignment Directive

**From:** Project Manager
**To:** OpenCode / MiniMax
**Priority:** ARCHITECTURE DEFENSE & HARDWARE TRANSITION
**Date:** 2026-04-02

---

## 🚫 TASK CANCELLATIONS & CONSTRAINTS

I have reviewed your proposed `AGENTS.md` plan. You must strictly halt and discard the following tasks to prevent devastating regressions to our locked milestone work:

1. **[CANCELLED] Foxglove Studio Integration:** Do not integrate Foxglove. We have already spent Milestones 20–23 building a bespoke "Mega-Dashboard" utilizing custom Three.js WebGL and Leaflet integrations specifically designed for our academic showcase. Abandoning this for Foxglove destroys weeks of custom UI engineering.
2. **[CANCELLED] Live Dashboard SSE Streaming:** Do NOT rebuild or touch the SSE pipeline. Live MAVLink-to-SSE streaming is already completely finalized in `autonomy/scripts/mission_api.py` and is heavily isolated to core 0 via programmatic `psutil` affinity constraints to prevent physics crashes. Touching this will break the CPU isolation.

---

## ✅ APPROVED EXECUTION PATH

You are to refocus entirely on closing the final hardware and presentation gaps. Execute the following strictly constrained tasks:

### Agent 1: Hardware Transition & HITL Deployment (Sprint 10 Protocol)
Your first priority is preparing the repo for physical Raspberry Pi deployment.
*   **Focus:** Formalize the HITL playbook and write a unified bash/powershell deployment launcher.
*   **Action:** Ensure the launcher perfectly switches parameters so `video_logger.py` and `mission_api.py` drop their `--mock-camera` and `--mock-mavlink` flags, and remap from UDP localhosts to the physical `/dev/ttyAMA0` UART connections for production flight.

### Agent 2: Judge Visualization (Timeline Overlay)
Your second priority is increasing the academic clarity of the existing dashboard.
*   **Focus:** An Event Timeline.
*   **Constraint:** You must inject this directly into the EXISTING dashboard architecture (`artifacts/dashboard/index.html`).
*   **Action:** Build a timeline UI component that parses the SSE stream and explicitly lists major autonomy triggers (e.g., *[03:45] Wind load exceeded 3% -> Returning to Launch*). Do NOT break the existing CSS flexboxes or the recently constrained FPV layouts.
