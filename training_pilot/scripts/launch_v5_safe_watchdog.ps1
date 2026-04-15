param(
    [switch]$ArmDestroy,
    [switch]$PreflightOnly,
    [int]$InstanceId = 0,
    [string]$ApiKey = "",
    [string]$RemoteRunDir = "/root/SeniorProject/training_pilot/runs/yolov8m_v5_production_final2",
    [string]$TrainSession = "production_v5_train",
    [string]$LocalExportRoot = "D:\downloads\SeniorProject\Skylink2\artifacts\final_safe_snapshots",
    [string]$LocalLiveCache = "D:\downloads\SeniorProject\Skylink2\artifacts\live_epoch_weights\yolov8m_v5_production_final2",
    [string[]]$ExtraRemotePath = @(
        "/root/SeniorProject/training_pilot/data/unified_bridge/dataset.yaml",
        "/root/SeniorProject/training_pilot/data/unified_bridge/bridge_manifest.json"
    ),
    [double]$PollSeconds = 60,
    [double]$QuiesceSeconds = 120,
    [int]$StopStablePolls = 3,
    [double]$GpuIdleSeconds = 0,
    [double]$GpuIdleUtilThreshold = 0,
    [int]$ScpRetries = 4,
    [double]$ScpRetryDelaySeconds = 15
)

$ErrorActionPreference = "Stop"

$repoRoot = "D:\downloads\SeniorProject\Skylink2\training_pilot"
$pythonScript = Join-Path $repoRoot "scripts\safe_auto_snapshot_and_destroy.py"
$sshKey = Join-Path $HOME ".ssh\id_ed25519"
if (-not (Test-Path $pythonScript)) {
    throw "Missing watchdog script: $pythonScript"
}
if (-not (Test-Path $sshKey)) {
    throw "Missing SSH key: $sshKey"
}
if ($ArmDestroy -and $InstanceId -le 0) {
    throw "InstanceId must be provided when -ArmDestroy is used."
}

$argsList = @(
    $pythonScript,
    "--ssh-host", "ssh2.vast.ai",
    "--ssh-port", "10022",
    "--ssh-user", "root",
    "--ssh-key", $sshKey,
    "--remote-project-root", "/root/SeniorProject/training_pilot",
    "--remote-run-dir", $RemoteRunDir,
    "--local-export-root", $localExportRoot,
    "--local-live-cache", $localLiveCache,
    "--epoch-step", "25",
    "--poll-seconds", "$PollSeconds",
    "--quiesce-seconds", "$QuiesceSeconds",
    "--stop-stable-polls", "$StopStablePolls",
    "--gpu-idle-seconds", "$GpuIdleSeconds",
    "--gpu-idle-util-threshold", "$GpuIdleUtilThreshold",
    "--scp-retries", "$ScpRetries",
    "--scp-retry-delay-seconds", "$ScpRetryDelaySeconds"
)

if ($TrainSession) {
    $argsList += @("--train-session", $TrainSession)
}

foreach ($path in $ExtraRemotePath) {
    $argsList += @("--extra-remote-path", $path)
}

if ($ApiKey) {
    $argsList += @("--api-key", $ApiKey)
}
if ($ArmDestroy) {
    $argsList += @("--instance-id", "$InstanceId", "--arm-destroy")
}
if ($PreflightOnly) {
    $argsList += "--preflight-only"
}

& python @argsList
