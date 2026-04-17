param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8625,
    [int]$ApiCpuCore = 0,
    [switch]$OpenBrowser = $true,
    [string]$RemoteHost = "ssh4.vast.ai",
    [int]$RemotePort = 17126,
    [string]$RemoteUser = "root",
    [string]$RemoteRepoRoot = "/root/SeniorProject"
)

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$missionApi = Join-Path $PSScriptRoot "mission_api.py"
$candidatePythons = @(
    (Join-Path $repoRoot "autonomy\.venv\Scripts\python.exe"),
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    "python"
)

$python = $candidatePythons | Where-Object {
    if ($_ -eq "python") {
        return $true
    }
    Test-Path $_
} | Select-Object -First 1

if (-not $python) {
    throw "No Python interpreter found for mission_api.py"
}

$identityPath = Join-Path $repoRoot "deploy\backend\ssh\id_ed25519"
if (-not (Test-Path $identityPath)) {
    throw "SSH identity key not found at $identityPath"
}

$env:SKYLINK_REMOTE_SSH_HOST = $RemoteHost
$env:SKYLINK_REMOTE_SSH_PORT = "$RemotePort"
$env:SKYLINK_REMOTE_SSH_USER = $RemoteUser
$env:SKYLINK_REMOTE_REPO_ROOT = $RemoteRepoRoot
$env:SKYLINK_REMOTE_IDENTITY_PATH = (Resolve-Path $identityPath).Path
$env:SKYLINK_REMOTE_CONNECT_TIMEOUT_S = "12"

Write-Host "Remote execution target: $RemoteUser@$RemoteHost`:$RemotePort$RemoteRepoRoot"
Write-Host "Identity key: $env:SKYLINK_REMOTE_IDENTITY_PATH"

if ($OpenBrowser) {
    Start-Process "http://$BindHost`:$Port/planner/index.html"
}

& $python $missionApi --host $BindHost --port $Port --cpu-core $ApiCpuCore
