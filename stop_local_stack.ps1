[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$runtimeDir = if ($env:SKYLINK_RUNTIME_DIR) { $env:SKYLINK_RUNTIME_DIR } else { Join-Path $repoRoot "artifacts\runtime_state" }
$stateFile = Join-Path $runtimeDir "stack_state.json"

if (-not (Test-Path $stateFile)) {
    Write-Host "No local stack state file found."
    exit 0
}

try {
    $state = Get-Content -Path $stateFile -Raw | ConvertFrom-Json
} catch {
    Write-Warning "Failed to parse $stateFile"
    exit 1
}

foreach ($procId in @($state.model_pid, $state.bridge_pid)) {
    if (-not $procId) {
        continue
    }
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped PID $procId"
    } catch {
        Write-Host "PID $procId was already stopped"
    }
}

Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
Write-Host "SkyLink local stack stopped."
