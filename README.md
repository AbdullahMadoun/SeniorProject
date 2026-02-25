# SkyLink: Road Inspection VLM

This repository contains the software suite for autonomous drone road inspection using the Qwen2.5-VL-7B-Instruct Vision Language Model.

## Problem Solving & Architectural Decisions

To ensure the system works reliably in real-world, edge-deployed scenarios, we made significant architectural shifts from the initial prototype:

1.  **Decoupling Edge Client & Model Server (`app/` vs `model_server/`)**
    *   **Problem:** Mixing the lightweight edge tools (drone bridge, dashboards) with the heavy PyTorch/CUDA model server made the repository bloated, difficult to navigate, and hard to deploy on edge devices (like a laptop or Jetson) that lack large GPUs.
    *   **Solution:** The repository is now split into two clean directories: `app/` (Edge client, bridge, and dashboard) and `model_server/` (GPU inference API). This Separation of Concerns means the edge client can be installed with minimal dependencies, while the model server can be deployed on specialized hardware (e.g., Vast.ai).
2.  **Offline-First via Supabase Removal**
    *   **Problem:** The system originally relied on Supabase (a cloud PostgreSQL service) to sync detections. In remote road inspection scenarios, internet connectivity is often spotty or non-existent. A hard dependency on a cloud database prevented the system from running on air-gapped edge devices.
    *   **Solution:** We stripped out Supabase and SQL integrations, replacing them with local file-based persistence (CSVs and JSON). The Streamlit dashboard now reads directly from local storage, making the system 100% capable of offline operation.
3.  **Enhanced Security & Key Management**
    *   **Problem:** API keys were previously handled directly in the frontend browser code, posing a security risk.
    *   **Solution:** We routed all VLM requests through the local Bridge server. The frontend talks to the Bridge, and the Bridge securely manages the API key and communicates with the `model_server`, keeping secrets out of the browser.

## Components
- A web bridge UI/API (`src/server.py`) that forwards analysis to your hosted model server.
- A Streamlit dashboard (`src/dashboard.py`) for reviewing synced results.
- A packaged hosted-model server drop at `road_inspector_server/` plus the original zip at `artifacts/road_inspector_updated.zip`.

## Architecture

1. Browser opens `http://localhost:8001` (served by `src/server.py`).
2. `POST /api/analyze` proxies request to your hosted model URL/API key.
3. Frontend draws boxes on canvas.
4. Bridge stores a local copy in `data/processed/history/` and also saves the detection record.
5. Dashboard reads records and shows only new bridge-prefixed rows by default.

## Repository Layout

```text
├── app/                      <-- Edge client tools
│   ├── src/
│   │   ├── server.py         (Bridge Server)
│   │   ├── dashboard.py      (Streamlit Viewer)
│   │   `-- static/           (Frontend UI)
│   ├── data/                 (Local persistence)
│   ├── scripts/
│   ├── Dockerfile
│   └── requirements.txt
├── model_server/             <-- GPU Inference Server
│   ├── app.py
│   └── docs/
└── artifacts/
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
- `SKYLINK_VLM_API_URL`

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

- Netlify hosting instructions: [NETLIFY_DEPLOY.md](NETLIFY_DEPLOY.md)

## Extra Docs


- [PROJECT_REPORT.md](PROJECT_REPORT.md)
- [road_inspector_server/README.md](road_inspector_server/README.md)
