Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& ".\.venv\Scripts\python.exe" ".\scripts\build_showcase.py"
& ".\.venv\Scripts\python.exe" ".\scripts\serve_showcase.py"
