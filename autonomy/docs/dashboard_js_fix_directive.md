# Codex Directive: Dashboard UI & State Lockout Fix

**From:** Project Manager  
**To:** OpenCode / MiniMax  
**Priority:** UI BLOCKER  
**Date:** 2026-04-02

---

## 🚫 Bug Report: UI Freeze & Timeline Squashing

The recent Milestone 25 Event Timeline injection caused significant UX regressions.

### Issue 1: Permanent UI State Lockout ("Buttons are useless")
The user is completely locked out of the simulation controls (Weather Mode, Battery Action, and Launch buttons).
**Root Cause Hypothesis:**
If the SSE stream from `mission_api.py` drops, fails, or completes without properly dispatching the exact `{"type": "complete"}` or `{"type": "failed"}` JSON payload structure to the browser, the JavaScript variable `S.locked` remains permanently `true`. This instantly disables all buttons guarded by `if (S.locked) return;`.
**Action:** Review the SSE pipeline in `mission_api.py` and the `streamLogs()` function in `dashboard_template.html`. Ensure there is a robust timeout or heartbeat so the UI can gracefully reset `S.locked = false` if the server disconnects.

### Issue 2: Event Timeline CSS Squashing
The new Event Timeline is structurally overlapping or getting crushed to 0 pixels with a horizontal scrollbar.
**Action:** Audit `.event-timeline` in `dashboard_template.html`. Ensure it explicitly sets `flex-shrink: 0`, and verify that its parent container (`.scene-shell`) appropriately manages 3D canvas height constraints (e.g. `display: flex; flex-direction: column` with `overflow: hidden`) so the absolute/fixed positioning of the timeline doesn't collapse under the Three.js WebGL canvas.

---

## Execution Constraint
- You are **NOT** permitted to change the overall layout of the Dashboard.
- You are **ONLY** permitted to fix the state machine bounds for `S.locked`, and strictly enforce the CSS box-model bounds for the Timeline overlay.
