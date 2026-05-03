# SkyLink — extract frames from a drone video, then run the AI pipeline.
#
# Usage:
#   .\scripts\run_extractor.ps1 -VideoPath "data\videos\road.mp4"
#
# Optional overrides (all have safe defaults):
#   -Speed     <float>   Drone cruise speed in m/s     (default: 5.0)
#   -Altitude  <float>   Drone altitude in metres       (default: 10.0)
#   -FOV       <float>   Camera horizontal FOV degrees  (default: 82.6)
#   -Overlap   <float>   Frame overlap fraction [0,0.9) (default: 0.10)
#   -MaxFrames <int>     Hard limit on extracted frames (default: unlimited)
#   -RunAI               After extraction, immediately run the AI pipeline
#
# Example — standard simulation demo for judges:
#   .\scripts\run_extractor.ps1 `
#       -VideoPath "data\videos\road.mp4" `
#       -Speed 5.0 -Altitude 10.0 -FOV 82.6 -Overlap 0.10 -RunAI

param(
    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [double]$Speed     = 5.0,
    [double]$Altitude  = 10.0,
    [double]$FOV       = 82.6,
    [double]$Overlap   = 0.10,
    [int]   $MaxFrames = 0,          # 0 = unlimited
    [switch]$RunAI
)

$ErrorActionPreference = "Stop"

# Resolve paths relative to the app/ directory
$AppDir = Split-Path -Parent $PSScriptRoot
Set-Location $AppDir

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SkyLink — Video Frame Extractor"                           -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Build the Python command
$PythonArgs = @(
    "src/video_extractor.py",
    "--video",   $VideoPath,
    "--speed",   $Speed,
    "--altitude",$Altitude,
    "--fov",     $FOV,
    "--overlap", $Overlap
)

if ($MaxFrames -gt 0) {
    $PythonArgs += "--max-frames"
    $PythonArgs += $MaxFrames
}

Write-Host "[1/2] Extracting frames..." -ForegroundColor Yellow
python @PythonArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Frame extraction failed (exit code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[DONE] Frames saved to data\raw\" -ForegroundColor Green

if ($RunAI) {
    Write-Host ""
    Write-Host "[2/2] Running AI detection pipeline..." -ForegroundColor Yellow
    python src/main.py --conf-threshold 0.25

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] AI pipeline failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "[DONE] Detections written to data\processed\detections.csv" -ForegroundColor Green
    Write-Host ""
    Write-Host "Open the dashboard to view results:" -ForegroundColor Cyan
    Write-Host "  streamlit run src/dashboard.py" -ForegroundColor White
}

Write-Host ""
