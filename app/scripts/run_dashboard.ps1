Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
& .\.venv\Scripts\streamlit run src/dashboard.py --server.port 8501
