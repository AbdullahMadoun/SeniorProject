# SkyLink MVP

Crack-inspection MVP for drone images.

The system detects cracks from 1080p images, annotates outputs, syncs results to Supabase (Storage + Postgres), and shows findings in a Streamlit dashboard with map/location navigation.

## Features

1. YOLO crack detection (`crack.pt`) with confidence threshold.
2. Processed image export with bounding boxes.
3. Severity tagging (`High Severity` / `Low Severity`).
4. Supabase sync:
   - Processed images to Storage.
   - Metadata to Postgres with transactions.
5. Dashboard:
   - KPIs.
   - Geo map.
   - Location index with Google Maps links.
6. Demo GPS mode when real GPS EXIF is missing.

## Tech Stack

1. Python 3.9+
2. Ultralytics YOLO
3. Streamlit
4. Supabase Python client
5. Psycopg + psycopg_pool

## Project Structure

```text
SkyLink-MVP/
|-- src/
|   |-- main.py
|   |-- detector.py
|   |-- cloud_sync.py
|   |-- dashboard.py
|   `-- mock_gps.py
|-- models/
|-- data/
|   |-- raw/
|   `-- processed/
|-- sql/
|   `-- supabase_schema.sql
|-- Dockerfile
|-- requirements.txt
|-- .env.example
|-- SETUP_SUPABASE.md
`-- PROJECT_REPORT.md
```

## Quick Start

1. Open terminal in `SkyLink-MVP`.
2. Create and activate virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Create `.env` from template:

```powershell
Copy-Item .env.example .env
```

5. Fill Supabase values in `.env`:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_POOLER_URL`

## Run

1. Put input images in `data/raw`.
2. Run detection only (local CSV/images):

```powershell
python src/main.py --conf-threshold 0.25
```

3. Run full flow with Supabase sync:

```powershell
python src/main.py --conf-threshold 0.25 --sync
```

4. Start dashboard:

```powershell
streamlit run src/dashboard.py --server.port 8501
```

5. Open:

```text
http://localhost:8501
```

## Demo GPS (for presentations)

If images have no GPS EXIF, dashboard can generate realistic demo points.

1. Enabled by default in `.env`:
   - `SKYLINK_DEMO_GPS_IF_MISSING=true`
2. Optional manual injection into local CSV:

```powershell
python src/mock_gps.py --center-lat 26.3073 --center-lon 50.1456 --radius-deg 0.00012 --overwrite
```

## Notes

1. `SUPABASE_SERVICE_ROLE_KEY` is backend secret. Do not expose it publicly.
2. Use Supabase Transaction pooler connection string (`port 6543`) to avoid IPv6/direct-DB issues.
3. Model file `models/crack.pt` is auto-downloaded on first run if missing.

## Sharing with Team

1. Push project to GitHub (without `.env`).
2. Teammates clone the repo.
3. Teammates create `.env` from `.env.example`.
4. Teammates run Quick Start and Run commands.

## Extra Docs

1. Setup guide: `SETUP_SUPABASE.md`
2. Full report: `PROJECT_REPORT.md`
