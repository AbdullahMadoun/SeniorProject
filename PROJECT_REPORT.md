# SkyLink MVP - Software Engineering Project Report

**Project:** SkyLink MVP  
**Version:** MVP (Detection + Cloud Sync + Dashboard)  
**Date:** 2026-02-23  
**Prepared by:** SWE Implementation Team

---

## 1. Executive Summary

SkyLink MVP is a crack-inspection software pipeline for drone imagery.  
The system processes 1080p images, detects cracks using a YOLO-based model, stores processed outputs in Supabase Storage, stores metadata in Supabase Postgres, and visualizes results in a Streamlit dashboard with map-based localization and navigation links.

This implementation focuses on **software engineering scope** (pipeline, data handling, cloud sync, observability, dashboard), while flight control, charging, and hardware safety remain out of scope for software-only MVP.

---

## 2. Problem Statement

Manual visual inspection of infrastructure is slow and inconsistent.  
The goal is to provide an automated inspection flow that:

1. Detects crack-like defects from drone images.
2. Assigns severity and organizes findings.
3. Shares findings centrally through cloud storage/database.
4. Presents actionable map and image views for operators.

---

## 3. Scope (What This MVP Covers)

### In Scope (SWE-Owned)

1. Image ingestion from `data/raw`.
2. YOLO inference for crack detection.
3. Annotation generation and processed image export.
4. Metadata persistence in CSV and Supabase Postgres.
5. Processed image upload to Supabase Storage.
6. Dashboard visualization:
   - KPIs
   - Detection map
   - Per-image location index with Google Maps links
7. Timing checks and operational metrics for pipeline latency.

### Out of Scope (Hardware/Flight/System-Level)

1. Flight control (range/altitude/speed).
2. Battery physics and charge circuits.
3. Docking station control logic and contact safety.
4. GACA operational compliance enforcement.
5. Real-time telemetry ingestion from drone firmware.

---

## 4. Current Architecture

```text
Raw Images (1080p)
   -> detector.py (YOLO crack inference + severity + GPS extraction)
   -> processed/*.jpg + detections.csv
   -> cloud_sync.py
      -> Supabase Storage (processed images)
      -> Supabase Postgres (metadata rows via transaction)
   -> dashboard.py (Streamlit)
      -> KPIs + Map + Location Index + Latest Detections
```

---

## 5. Repository Structure

```text
SkyLink-MVP/
├── src/
│   ├── main.py
│   ├── detector.py
│   ├── cloud_sync.py
│   ├── dashboard.py
│   └── mock_gps.py
├── models/
│   ├── crack.pt
│   └── yolov8n.pt
├── data/
│   ├── raw/
│   └── processed/
├── sql/
│   └── supabase_schema.sql
├── Dockerfile
├── requirements.txt
├── SETUP_SUPABASE.md
└── PROJECT_REPORT.md
```

---

## 6. Core Components

### 6.1 `src/detector.py`

1. Uses `crack.pt` (downloaded automatically if missing).
2. Filters detections to target class list (`SKYLINK_TARGET_CLASSES`, default `crack`).
3. Applies confidence threshold (default `0.25`).
4. Applies minimum box area ratio filter (`SKYLINK_MIN_CRACK_AREA_RATIO`).
5. Draws bounding boxes and confidence labels.
6. Computes severity:
   - `High Severity` if area ratio >= 0.02
   - otherwise `Low Severity`
7. Attempts GPS extraction from EXIF.

### 6.2 `src/cloud_sync.py`

1. Creates/uses Supabase client.
2. Uses Supabase Storage bucket for images.
3. Uses psycopg connection pool for Postgres.
4. Inserts metadata in a DB transaction.
5. Uses compensation behavior:
   - if DB insert fails after upload, uploaded file is removed (best effort).
6. Uses `prepare_threshold=None` for transaction pooler compatibility.

### 6.3 `src/main.py`

1. Orchestrates full pipeline over all images in `data/raw`.
2. Writes `data/processed/detections.csv`.
3. Optional sync to Supabase via `--sync`.
4. Includes optional technical grounding calculations:
   - Drag force
   - Thrust-to-weight ratio

### 6.4 `src/dashboard.py`

1. Loads from Supabase first, then CSV fallback.
2. Shows KPIs:
   - total detections
   - high severity count
   - average confidence
   - localization metric
3. Map behavior:
   - Real GPS if available
   - Realistic mock coordinates when GPS is missing (demo mode)
4. Adds **Location Index** table:
   - image name
   - severity
   - source (gps/mock)
   - lat/lon
   - Google Maps navigation link

### 6.5 `src/mock_gps.py`

Adds synthetic GPS coordinates to local CSV for demo-only presentations when EXIF GPS is unavailable.

---

## 7. Model Choice and Status

1. Active model: `models/crack.pt`
2. Source configured in code:
   - `https://huggingface.co/hyunon/crack-yolov8/resolve/main/crack.pt`
3. Model is integrated and running in the current flow.
4. Detection output currently used as MVP baseline.
5. Accuracy KPI in code (`estimated_accuracy`) is a heuristic indicator, not a formal benchmark.

**Note:** A formal accuracy claim (e.g., >75%) requires labeled test data and standard metrics (precision/recall/mAP).

---

## 8. Data Model (Postgres)

Table: `public.detections`

Main fields:

1. `image_name`
2. `storage_path`
3. `image_url`
4. `detection_count`
5. `max_confidence`
6. `severity`
7. `gps_lat`, `gps_lon`
8. `localization_m`, `localization_target_met`
9. `estimated_accuracy`, `accuracy_target_met`
10. `processing_seconds`, `timestamp_utc`
11. `boxes` (JSONB)

Indexes:

1. `timestamp_utc DESC`
2. `severity`

---

## 9. Environment and Configuration

Required `.env` keys:

1. `SUPABASE_URL`
2. `SUPABASE_SERVICE_ROLE_KEY`
3. `SUPABASE_DB_POOLER_URL`
4. `SUPABASE_BUCKET`

Recommended demo keys:

1. `SKYLINK_DEMO_GPS_IF_MISSING=true`
2. `SKYLINK_DEMO_CENTER_LAT`
3. `SKYLINK_DEMO_CENTER_LON`
4. `SKYLINK_DEMO_STEP_DEG`

---

## 10. Runtime Flow

### 10.1 Current MVP Flow (Batch Images)

1. User places images in `data/raw`.
2. Run:
   - `python src/main.py --conf-threshold 0.25 --sync`
3. System performs detection and annotations.
4. Processed images are uploaded to Supabase Storage.
5. Metadata rows are inserted in Supabase Postgres.
6. Dashboard displays latest results.

### 10.2 Target Future Flow (Drone-Connected)

1. Drone streams frames + telemetry (GPS/time/mission id).
2. Edge processor runs inference per frame.
3. Results sync continuously to cloud.
4. Dashboard updates near real-time with alerting and route context.

---

## 11. Observed Run Metrics (Current Dataset)

Based on latest `data/processed/detections.csv`:

1. Processed images with detections: **21**
2. Total detected boxes: **349**
3. High severity images: **21**
4. Average max confidence: **0.7199**
5. Average processing time per image: **1.6031 s**
6. Max processing time: **3.032 s**
7. Localization metric value in output: **20.0 m**
8. Supabase sync status: **uploaded = 21**

---

## 12. SWE Metrics Mapping to Project Constraints

### Can be addressed directly in this software

1. Camera resolution check (1080p input validation).
2. Detection quality metric pipeline (requires labeled evaluation set).
3. Data sharing latency (processing-to-cloud timing).
4. Upload throughput monitoring.
5. Dashboard map localization and navigation UX.

### Cannot be guaranteed by this software alone

1. Flight range / altitude / speed.
2. Battery duration / charge time.
3. Auto landing precision.
4. Docking electrical safety and contact-based charging.
5. Airworthiness/regulatory physical operation constraints.

---

## 13. Risks and Limitations

1. GPS may be absent in EXIF for many images.
2. Current mock GPS mode is for demo only and must be clearly labeled.
3. Model performance not yet validated on a formally labeled project-specific dataset.
4. Service role key handling requires strict secret management.
5. Network conditions can affect sync latency and throughput.

---

## 14. Improvement Roadmap

1. Add formal evaluation module (mAP, precision, recall) with labeled test set.
2. Add mission/session entities in DB (project, drone, run id, operator).
3. Add filtering/search in dashboard (severity, time range, region).
4. Add alert rules (high severity threshold notifications).
5. Add automated report export (PDF summary + map snapshots).
6. Integrate real drone telemetry stream and GPS confidence fields.

---

## 15. Reproducibility Checklist

1. Clone repository.
2. Create and activate virtual environment.
3. Install requirements.
4. Copy `.env.example` to `.env` and fill Supabase credentials.
5. Put test images in `data/raw`.
6. Run pipeline with `--sync`.
7. Launch dashboard and validate map/image/KPI output.

---

## 16. Conclusion

The MVP achieves a full SWE inspection loop:

1. detection,
2. processing,
3. cloud persistence,
4. map-based visualization,
5. operator-friendly location navigation.

It is ready for demonstration and collaborative use, with clear next steps toward production readiness and tighter hardware integration.

