[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$OpenBrowser,
    [switch]$EnableQuickTunnel,
    [string]$CloudflaredBin = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$venvDir = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$runtimeDir = if ($env:SKYLINK_RUNTIME_DIR) { $env:SKYLINK_RUNTIME_DIR } else { Join-Path $repoRoot "artifacts\runtime_state" }
$runId = Get-Date -Format "yyyyMMdd_HHmmss"
$stateFile = Join-Path $runtimeDir "stack_state.json"
$modelLog = Join-Path $runtimeDir "model_server_$runId.log"
$modelErrLog = Join-Path $runtimeDir "model_server_$runId.err.log"
$bridgeLog = Join-Path $runtimeDir "bridge_server_$runId.log"
$bridgeErrLog = Join-Path $runtimeDir "bridge_server_$runId.err.log"
$modelLauncher = Join-Path $runtimeDir "launch_model_server.ps1"
$bridgeLauncher = Join-Path $runtimeDir "launch_bridge_server.ps1"
$envFile = Join-Path $repoRoot ".env"
$remoteInfoFile = Join-Path $runtimeDir "remote_model_info.json"
$remoteLogFile = Join-Path $runtimeDir "remote_model.log"
$remoteInstanceFile = Join-Path $runtimeDir "remote_model_instance_id.txt"
$cloudflaredRuntimeDir = Join-Path $runtimeDir "cloudflared"
$tunnelInfoFile = Join-Path $runtimeDir "tunnel_info.json"
$tunnelLogFile = Join-Path $runtimeDir "cloudflared.log"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{}
    }

    $values = @{}
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $index = $line.IndexOf("=")
        if ($index -lt 1) {
            continue
        }
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        $values[$key] = $value
    }
    return $values
}

function Stop-ExistingStack {
    if (-not (Test-Path $stateFile)) {
        return
    }

    try {
        $state = Get-Content -Path $stateFile -Raw | ConvertFrom-Json
        foreach ($procId in @($state.model_pid, $state.bridge_pid)) {
            if ($procId) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                } catch {
                }
            }
        }
        Start-Sleep -Milliseconds 750
    } catch {
    }
}

function Ensure-Venv {
    if (-not (Test-Path $venvPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv $venvDir
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv $venvDir
        } else {
            throw "Python was not found on PATH."
        }
    }

    if ($SkipInstall) {
        return
    }

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $repoRoot "model_server\requirements-yolo.txt")
    & $venvPython -m pip install -r (Join-Path $repoRoot "app\requirements.txt")
    & $venvPython -m pip install supabase
}

function Wait-ForHttp200 {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Resolve-CloudflaredBinary {
    param(
        [hashtable]$DotEnv
    )

    if (-not $EnableQuickTunnel) {
        return ""
    }

    if ($CloudflaredBin) {
        if (-not (Test-Path $CloudflaredBin)) {
            throw "Cloudflared binary not found at $CloudflaredBin"
        }
        return (Resolve-Path $CloudflaredBin).Path
    }

    if ($DotEnv.ContainsKey("SKYLINK_CLOUDFLARED_BIN") -and $DotEnv["SKYLINK_CLOUDFLARED_BIN"]) {
        $configured = $DotEnv["SKYLINK_CLOUDFLARED_BIN"]
        if (Test-Path $configured) {
            return (Resolve-Path $configured).Path
        }
    }

    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    New-Item -ItemType Directory -Force -Path $cloudflaredRuntimeDir | Out-Null
    $downloadTarget = Join-Path $cloudflaredRuntimeDir "cloudflared.exe"
    $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadTarget
    return $downloadTarget
}

function Wait-ForTunnelUrl {
    param(
        [int]$BridgePort,
        [int]$TimeoutSeconds = 120
    )

    if (-not $EnableQuickTunnel) {
        return ""
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$BridgePort/api/runtime-config" -TimeoutSec 5
            $publicUrl = [string]($response.PUBLIC_BRIDGE_URL)
            if ($publicUrl) {
                return $publicUrl.Trim()
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    return ""
}

function Get-ListenerProcessId {
    param(
        [int]$Port
    )

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        return [int]$listener.OwningProcess
    }
    return $null
}

function New-LauncherScripts {
    param(
        [hashtable]$DotEnv,
        [string]$ResolvedCloudflaredBin
    )

    $apiKey = if ($DotEnv.ContainsKey("API_KEY") -and $DotEnv["API_KEY"]) { $DotEnv["API_KEY"] } else { "road-inspector-secret-key-2024" }
    $modelPort = if ($DotEnv.ContainsKey("PORT") -and $DotEnv["PORT"]) { $DotEnv["PORT"] } else { "17612" }
    $bridgePort = if ($DotEnv.ContainsKey("SKYLINK_BRIDGE_PORT") -and $DotEnv["SKYLINK_BRIDGE_PORT"]) {
        $DotEnv["SKYLINK_BRIDGE_PORT"]
    } elseif ($DotEnv.ContainsKey("BRIDGE_PORT") -and $DotEnv["BRIDGE_PORT"]) {
        $DotEnv["BRIDGE_PORT"]
    } else {
        "8001"
    }
    $defaultVlmMode = if ($DotEnv.ContainsKey("VLM_BACKEND") -and $DotEnv["VLM_BACKEND"]) { $DotEnv["VLM_BACKEND"] } else { "api" }

    $sharedDotEnvLoader = @'
function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $index = $line.IndexOf("=")
        if ($index -lt 1) {
            continue
        }
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}
'@

    $modelScript = @"
`$ErrorActionPreference = 'Stop'
$sharedDotEnvLoader
Import-DotEnv '$envFile'
Set-Location '$repoRoot'

`$env:PYTHONUTF8 = '1'
`$env:API_KEY = if (`$env:API_KEY) { `$env:API_KEY } else { '$apiKey' }
`$env:HOST = if (`$env:HOST) { `$env:HOST } else { '0.0.0.0' }
`$env:PORT = if (`$env:PORT) { `$env:PORT } else { '$modelPort' }
`$env:DETECTOR_MODE = 'ensemble'
`$env:ENSEMBLE_ENABLED = 'true'
if (-not `$env:ENSEMBLE_WBF_SKIP) { `$env:ENSEMBLE_WBF_SKIP = '0.01' }
if (-not `$env:ENSEMBLE_FINAL_THRESHOLD) { `$env:ENSEMBLE_FINAL_THRESHOLD = '0.03' }
if (-not `$env:ENSEMBLE_MIN_SUPPORT) { `$env:ENSEMBLE_MIN_SUPPORT = '1' }
if (-not `$env:VLM_BACKEND) { `$env:VLM_BACKEND = 'api' }

& '$venvPython' '.\model_server\main.py'
"@

    $bridgeScript = @"
`$ErrorActionPreference = 'Stop'
$sharedDotEnvLoader
Import-DotEnv '$envFile'
Set-Location '$repoRoot'

`$env:PYTHONUTF8 = '1'
`$env:SKYLINK_BRIDGE_PORT = '$bridgePort'
`$env:SKYLINK_ENABLE_QUICK_TUNNEL = '$($EnableQuickTunnel.ToString().ToLowerInvariant())'
`$env:SKYLINK_REMOTE_MODEL_AUTOSTART = 'false'
`$env:SKYLINK_USE_BRIDGE_PROXY = 'true'
`$env:SKYLINK_FRONTEND_DIRECT_MODEL = 'false'
`$env:SKYLINK_REMOTE_MODEL_INFO_FILE = '$remoteInfoFile'
`$env:SKYLINK_REMOTE_MODEL_LOG_FILE = '$remoteLogFile'
`$env:SKYLINK_REMOTE_MODEL_INSTANCE_FILE = '$remoteInstanceFile'
`$env:SKYLINK_TUNNEL_INFO_FILE = '$tunnelInfoFile'
`$env:SKYLINK_TUNNEL_LOG_FILE = '$tunnelLogFile'
`$env:SKYLINK_VLM_API_URL = 'http://127.0.0.1:$modelPort/analyze'
`$env:SKYLINK_VLM_API_KEY = '$apiKey'
`$env:SKYLINK_DEFAULT_VLM_MODE = '$defaultVlmMode'
`$env:SKYLINK_CLOUDFLARED_BIN = '$ResolvedCloudflaredBin'
`$env:SKYLINK_CLOUDFLARED_CONFIG_FILE = ''

& '$venvPython' '.\app\src\server.py'
"@

    Set-Content -Path $modelLauncher -Value $modelScript -Encoding UTF8
    Set-Content -Path $bridgeLauncher -Value $bridgeScript -Encoding UTF8

    return @{
        ModelPort = $modelPort
        BridgePort = $bridgePort
        DefaultVlmMode = $defaultVlmMode
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
Stop-ExistingStack
Ensure-Venv

$dotEnv = Import-DotEnv $envFile
$resolvedCloudflaredBin = Resolve-CloudflaredBinary -DotEnv $dotEnv

New-Item -ItemType Directory -Force -Path $cloudflaredRuntimeDir | Out-Null
$ports = New-LauncherScripts -DotEnv $dotEnv -ResolvedCloudflaredBin $resolvedCloudflaredBin

if (Test-Path $remoteInfoFile) { Remove-Item $remoteInfoFile -Force }
if (Test-Path $remoteLogFile) { Remove-Item $remoteLogFile -Force }
if (Test-Path $remoteInstanceFile) { Remove-Item $remoteInstanceFile -Force }
if (Test-Path $tunnelInfoFile) { Remove-Item $tunnelInfoFile -Force }
if (Test-Path $tunnelLogFile) { Remove-Item $tunnelLogFile -Force }

$modelProcess = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $modelLauncher) `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $modelLog `
    -RedirectStandardError $modelErrLog `
    -WindowStyle Hidden `
    -PassThru

if (-not (Wait-ForHttp200 -Url "http://127.0.0.1:$($ports.ModelPort)/health" -TimeoutSeconds 180)) {
    throw "Model server did not become healthy. Check $modelLog"
}

$bridgeProcess = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $bridgeLauncher) `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $bridgeLog `
    -RedirectStandardError $bridgeErrLog `
    -WindowStyle Hidden `
    -PassThru

if (-not (Wait-ForHttp200 -Url "http://127.0.0.1:$($ports.BridgePort)/api/health" -TimeoutSeconds 120)) {
    throw "Bridge server did not become healthy. Check $bridgeLog"
}

$resolvedModelPid = Get-ListenerProcessId -Port ([int]$ports.ModelPort)
$resolvedBridgePid = Get-ListenerProcessId -Port ([int]$ports.BridgePort)
$publicBridgeUrl = Wait-ForTunnelUrl -BridgePort ([int]$ports.BridgePort)

$state = @{
    started_at = (Get-Date).ToString("o")
    model_pid = if ($resolvedModelPid) { $resolvedModelPid } else { $modelProcess.Id }
    bridge_pid = if ($resolvedBridgePid) { $resolvedBridgePid } else { $bridgeProcess.Id }
    model_health = "http://127.0.0.1:$($ports.ModelPort)/health"
    bridge_health = "http://127.0.0.1:$($ports.BridgePort)/api/health"
    dashboard_url = "http://127.0.0.1:$($ports.BridgePort)/"
    model_log = $modelLog
    model_err_log = $modelErrLog
    bridge_log = $bridgeLog
    bridge_err_log = $bridgeErrLog
    public_bridge_url = $publicBridgeUrl
    tunnel_info_file = $tunnelInfoFile
    tunnel_log_file = $tunnelLogFile
}
$state | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8

Write-Host ""
Write-Host "SkyLink local stack is running." -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:$($ports.BridgePort)/"
Write-Host "Model health: http://127.0.0.1:$($ports.ModelPort)/health"
Write-Host "Bridge health: http://127.0.0.1:$($ports.BridgePort)/api/health"
if ($publicBridgeUrl) {
    Write-Host "Public tunnel: $publicBridgeUrl"
}
Write-Host "Logs:"
Write-Host "  $modelLog"
Write-Host "  $bridgeLog"

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$($ports.BridgePort)/" | Out-Null
}
