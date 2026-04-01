Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
python -m streamlit run drone_system\visualizer_app.py --server.port 8601
