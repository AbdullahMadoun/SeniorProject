param(
    [string]$Model = "gz_x500",
    [string]$World = "",
    [switch]$Headless = $true
)

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logRoot = Join-Path $projectRoot "artifacts\sitl_logs"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $logRoot $timestamp
$stdoutPath = Join-Path $logDir "stdout.log"
$stderrPath = Join-Path $logDir "stderr.log"
$pidPath = Join-Path $logDir "windows_pid.txt"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$repo = "/mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot"
$arguments = @("--cd", $repo, "--", "env")

if ($Headless) {
    $arguments += "HEADLESS=1"
}

if (-not [string]::IsNullOrWhiteSpace($World)) {
    $arguments += "PX4_GZ_WORLD=$World"
}

$arguments += @("make", "px4_sitl", $Model)

$proc = Start-Process -FilePath "wsl.exe" `
    -ArgumentList $arguments `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidPath -Value $proc.Id
Write-Output "log_dir=$logDir"
Write-Output "windows_pid=$($proc.Id)"
