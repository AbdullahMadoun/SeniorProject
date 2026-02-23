# SkyLink MVP - Supabase Setup and Handover

## 1) Prepare environment

1. Copy env template:
   - `cp .env.example .env` (Linux/Mac)
   - `Copy-Item .env.example .env` (PowerShell)
2. In `.env`, fill:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_POOLER_URL` (Connection pooling, transaction mode, port 6543)

## 2) Install and run locally

1. Install requirements:
   - `python -m pip install -r requirements.txt`
2. Put raw images in `data/raw`.
3. Run detection only (no cloud sync):
   - `python src/main.py --conf-threshold 0.25`
4. Run detection + Supabase sync:
   - `python src/main.py --conf-threshold 0.25 --sync`
5. Start dashboard:
   - `streamlit run src/dashboard.py --server.port 8501`

## 3) Supabase objects used

- Storage bucket: `SUPABASE_BUCKET` (default `skylink-images`)
- Table: `public.detections`
- SQL schema file: `sql/supabase_schema.sql`
  - The app auto-creates this schema on first `--sync`.

## 4) Fix IPv6-only DB issue

Use `SUPABASE_DB_POOLER_URL` from Supabase dashboard (Connection pooling / Transaction mode).
Do not rely on direct DB host if your network has IPv6 limitations.

## 5) Share with teammates (without your laptop)

### Option A (recommended): GitHub + cloud deployment

1. Push project to GitHub.
2. Deploy as a Docker web service on Render/Railway.
3. Set environment variables from `.env` in the hosting dashboard.
4. Share the deployment URL with teammates/evaluators.

### Option B: GitHub only (teammates run locally)

1. Push repo to GitHub.
2. Share repo link.
3. Teammates clone, create `.env`, run commands in section 2.
