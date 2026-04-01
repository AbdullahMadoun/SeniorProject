Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& "D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python.exe" "D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py"
& "D:\downloads\SeniorProject\Skylink2\autonomy\.venv\Scripts\python.exe" "D:\downloads\SeniorProject\Skylink2\autonomy\scripts\serve_showcase.py"
