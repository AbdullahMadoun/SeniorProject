# SkyLink2 (Reproducible)

`Skylink2` is the app repo. It does not run your hosted VLM model locally.

It provides:
- A web bridge UI/API (`src/server.py`) that forwards analysis to your hosted model server.
- Supabase sync for annotated images and detection metadata.
- A Streamlit dashboard (`src/dashboard.py`) for reviewing synced results.
- A packaged hosted-model server drop at `road_inspector_server/` plus the original zip at `artifacts/road_inspector_updated.zip`.

## Architecture

1. Browser opens `http://localhost:8001` (served by `src/server.py`).
2. `POST /api/analyze` proxies request to your hosted model URL/API key.
3. Frontend draws boxes on canvas.
4. `POST /api/sync` sends annotated image (base64) to bridge.
5. Bridge stores a local copy in `data/processed/history/` and uploads that same annotated image + metadata to Supabase.
6. Dashboard reads Supabase records and shows only new bridge-prefixed rows by default.

## Repository Layout

```text
Skylink2/
|-- src/
|   |-- server.py
|   |-- dashboard.py
|   |-- cloud_sync.py
|   `-- static/
|-- data/
|   `-- processed/history/
|-- road_inspector_server/           # extracted hosted model server code
|-- artifacts/road_inspector_updated.zip
|-- .env.example
|-- requirements.txt
`-- scripts/
```

## Reproducible Setup (Windows / PowerShell)

```powershell
cd D:\downloads\SeniorProject\Skylink2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set required values in `.env`:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DB_POOLER_URL`
- `SKYLINK_VLM_API_URL`
- `SKYLINK_VLM_API_KEY`

## Run (Recommended)

Terminal 1:
```powershell
cd D:\downloads\SeniorProject\Skylink2
.\.venv\Scripts\Activate.ps1
python src/server.py
```

Open:
- `http://localhost:8001` (web app + analysis flow)

Terminal 2:
```powershell
cd D:\downloads\SeniorProject\Skylink2
.\.venv\Scripts\Activate.ps1
streamlit run src/dashboard.py --server.port 8501
```

Open:
- `http://localhost:8501` (dashboard)

## Verification

Bridge health:
```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

Expected output:
```json
{"status":"ok"}
```

## Notes

- `web_client/` at repo root is not used for runtime.
- Old Supabase trial rows are hidden by default from the board.
- New records are tagged with `bridge_` image names.
- Never expose `SUPABASE_SERVICE_ROLE_KEY` in browser code.

## Extra Docs

- [SETUP_SUPABASE.md](SETUP_SUPABASE.md)
- [PROJECT_REPORT.md](PROJECT_REPORT.md)
- [road_inspector_server/README.md](road_inspector_server/README.md)
