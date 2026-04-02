# STRICT DIRECTIVE: UI Formatting & Core Simulation Fixes

**From:** Project Manager  
**To:** Codex  
**Priority:** BLOCKER / CRITICAL  
**Date:** 2026-04-02

---

## 🚫 UNACCEPTABLE CURRENT STATE
The Mega-Dashboard was audited and the current UI/UX layout is a disaster. There are extreme CSS clipping issues, flexbox failures, and worse, the simulation fails to launch. These fundamental flaws must be resolved BEFORE embarking on any cinematic upgrades.

You are ordered to fix the following issues immediately:

### 1. Leaflet Satellite Enforcement
You must replace the standard placeholder tile layer in Leaflet. The user demands a full colored Satellite Map logic for both the waypoint planner and the simulation viewer. 
- Use Esri World Imagery: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`

### 2. Disastrous CSS Layouts (Underflow & Overflow)
- **Target/Status Collision:** The flexbox layout containing the `TARGET` string (`udpin://0.0.0.0...`) and the `STATUS` string (`Bridge Active`) are aggressively overlapping. Fix the CSS grid/flex boundaries immediately so text wraps safely and doesn't bleed out of the border.
- **Media Box Clipping:** Text inside your `MEDIA` card is falling out of the bottom bound. Ensure text elements have responsive padding, and `overflow-wrap: break-word` applied.
- **Scrollbar Mess:** The nested scrolling between the main page body and the sidebar is clunky. Standardize `overflow-y` behaviors so the dashboard feels like a fixed-height web app, not a massive scrolling document.

### 3. Ensure UI Resiliency for Cinematic Artifacts
The cinematic layers (FPV Panes, 3D Ribbons) introduced in Milestone 21 require a rock-solid, responsive flexbox foundation. Do not push cinematic polish if the underlying sidebar grid crashes into itself. 

---

## Acceptance Constraints
Do not proceed until:
1. The Leaflet map natively shows Esri World Imagery natively.
2. The UI handles text layout with responsive CSS grids and `overflow-wrap` correctly so `udpin` constraints don't crash into statuses.
3. The new FPV Panes and UI are perfectly aligned inside the dashboard window.

---

## Natural next steps

1. Visit the dashboard dynamically via `python autonomy/scripts/mission_api.py` and test the FPV stream end-to-end to validate the layout.
2. Move to the next directive once you want the next milestone executed.
