$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "prove_live_px4_landing_target_consumption.py"
$pythonPath = Join-Path $PSScriptRoot "..\\.venv\\Scripts\\python.exe"

& $pythonPath $scriptPath
