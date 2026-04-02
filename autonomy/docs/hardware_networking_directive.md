# Codex Directive: Central Config & Network Hardening

**From:** Project Manager  
**To:** Codex  
**Priority:** ARCHITECTURE BLOCKER  
**Date:** 2026-04-02

---

## Problem Statement
A static audit of the codebase revealed a devastating flaw for the Sprint 10 hardware transition. Sockets across the system (`mission_api.py`, `video_logger.py`, etc.) are heavily hardcoded to listen and stream over `127.0.0.1`. When running on the actual Raspberry Pi, this explicitly blocks the operator's laptop from fetching MAVLink sockets, video streams, or dashboard APIs over Wi-Fi. 
Additionally, system constants are being parsed raw via `os.environ` throughout arbitrary files, creating a scattershot configuration structure.

---

## Technical Constraints

### 1. Centralized Configuration Node
- Create a new file at `autonomy/drone_system/config.py`.
- Define a strict `SystemConfig` data class or Pydantic model.
- Move **ALL** `os.environ` fallback logic (e.g. `SKYLINK_MAVLINK_TARGET`, `SKYLINK_FPV_SOURCE_URL`) into this central file. 
- Refactor all external files (`mission_api.py`, `video_logger.py`, `dashboard_builder.py`) to import these cleanly typed connection constants from `config.py`.

### 2. Eliminating Localhost
- Search all refactored Python scripts for `.bind()` or connection `host` assignments.
- Change any server interfaces from `127.0.0.1` or `localhost` to `0.0.0.0` to permit Wi-Fi connections when running natively on the drone hardware. 

### 3. Proxy Socket Resilience (502 Bad Gateway)
- Edit the `mission_api.py` endpoint for `/api/fpv/stream` (the MJPEG proxy).
- If the `video_logger.py` is not running or goes offline mid-flight, the current proxy throws aggressive `502 Bad Gateway` traces and hangs.
- Implement robust exception handling, exponential connection backoff, and graceful socket shutdown in the streaming proxy endpoint. It must recover seamlessly if the companion thread restarts.

---

## Validation
Do not exit this directive until you have verified `python -m unittest discover` succeeds. The architectural extraction must not break internal module imports!
