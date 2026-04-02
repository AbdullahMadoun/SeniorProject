# STRICT DIRECTIVE: Brutal UI/UX Overhaul & Satellite Map Requirement

**From:** Project Manager  
**To:** Codex  
**Priority:** BLOCKER / CRITICAL  
**Date:** 2026-04-02

---

## 🚫 EXTREME UI/UX FAILURES DETECTED
Milestone 21 (Cinematic Visuals) succeeded in laying the data pipes, but the foundational Mega-Dashboard UI is failing. A visual audit found severe CSS overlapping, broken multi-level scrollbars, and an incorrect map type. 

You are ordered to cease adding new features and fix these layout flaws immediately.

### 1. Mandatory Satellite Image Map (Top Priority)
The user expressly demands a colored Satellite Map for waypoint editing and simulation viewing. The current dark vectorized OSM map is unacceptable.
- **Action:** Replace the Leaflet tile layer in `dashboard_template.html` / `dashboard_builder.py`.
- **Target Provider:** Use `Esri.WorldImagery` (URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`) or a similar high-res colored satellite XYZ tile layer. Do not use dark mode vectors.

### 2. Disastrous CSS Layouts (Underflow & Overflow)
- **Target/Status Collision:** In the left sidebar, the `.grid` or flexbox containing `TARGET` (`udpin://...`) and `STATUS` (`Bridge Active`) are overlapping heavily. Fix the boundaries so text wraps natively and doesn't collide into adjacent text.
- **Media Box Clipping:** Text inside your `MEDIA` card strings fall out of the bottom boundary. Ensure responsive padding and `overflow-wrap: break-word`.
- **Buried Buttons:** The "Launch Live Simulator" button gets buried under a messy double-scrollbar effect in the dashboard. Standardize the `overflow-y` behaviors so the dashboard feels like an app, not a nested document.

### 3. FPV UI Alignment
- Ensure the new FPV tracking panes introduced in Milestone 21 are cleanly sized. If the MJPEG stream (`/api/fpv/stream`) is offline or 502, show a clean "Awaiting FPV Connection" placeholder rather than collapsing the UI or showing broken image icons.

---

## Acceptance Constraints
Do not exit until:
1. The Leaflet map natively shows Real Colored Satellite Imagery natively.
2. The UI handles text layout resizing robustly so strings (`udpin`, status constants) don't crash into each other.
3. The FPV pane clearly handles offline/online stream states without breaking the grid.
