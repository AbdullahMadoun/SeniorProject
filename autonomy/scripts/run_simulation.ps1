param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8625,
    [switch]$OpenBrowser = $true,
    [switch]$StartMockFpv = $true,
    [int]$ApiCpuCore = 0,
    [int]$VideoCpuCore = 1,
    [int]$FpvPort = 5050
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$apiScript = Join-Path $PSScriptRoot "mission_api.py"
$videoScript = Join-Path $repoRoot "companion\video_logger.py"

if (-not (Test-Path $python)) {
    throw "Autonomy virtual environment python not found at $python"
}

if ($StartMockFpv) {
    $videoCommand = "& '$python' '$videoScript' --mock-mavlink --mock-camera --stream --stream-host 127.0.0.1 --stream-port $FpvPort --cpu-core $VideoCpuCore --max-frames 0"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        $videoCommand
    ) | Out-Null
}

if ($OpenBrowser) {
    Start-Process "http://$Host`:$Port/"
}

& $python $apiScript --host $Host --port $Port --cpu-core $ApiCpuCore
