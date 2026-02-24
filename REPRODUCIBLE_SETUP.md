# Reproducible Setup Checklist

## 1. Clone and prepare

```powershell
git clone <repo-url>
cd Skylink2
.\scripts\setup.ps1
```

## 2. Configure environment

Edit `.env` and set:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DB_POOLER_URL`
- `SKYLINK_VLM_API_URL`
- `SKYLINK_VLM_API_KEY`

## 3. Run services

Terminal A:
```powershell
.\scripts\run_bridge.ps1
```

Terminal B:
```powershell
.\scripts\run_dashboard.ps1
```

## 4. Validate

Bridge:
```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
```

UI:
- `http://localhost:8001`
- `http://localhost:8501`

## 5. Expected behavior

- Analysis request is forwarded to hosted model server.
- Annotated image is uploaded to Supabase via `/api/sync`.
- Dashboard displays new bridge-prefixed rows.
