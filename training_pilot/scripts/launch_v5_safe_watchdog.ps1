param(
    [switch]$ArmDestroy,
    [switch]$PreflightOnly,
    [int]$InstanceId = 0,
    [string]$ApiKey = "",
    [double]$PollSeconds = 60,
    [double]$QuiesceSeconds = 120,
    [int]$StopStablePolls = 3,
    [int]$ScpRetries = 4,
    [double]$ScpRetryDelaySeconds = 15
)

$ErrorActionPreference = "Stop"

$repoRoot = "D:\downloads\SeniorProject\Skylink2\training_pilot"
$pythonScript = Join-Path $repoRoot "scripts\safe_auto_snapshot_and_destroy.py"
$sshKey = Join-Path $HOME ".ssh\id_ed25519"
$localExportRoot = "D:\downloads\SeniorProject\Skylink2\artifacts\final_safe_snapshots"
$localLiveCache = "D:\downloads\SeniorProject\Skylink2\artifacts\live_epoch_weights\yolov8m_v5_production_final2"

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
    "--remote-run-dir", "/root/SeniorProject/training_pilot/runs/yolov8m_v5_production_final2",
    "--train-session", "production_v5_train",
    "--local-export-root", $localExportRoot,
    "--local-live-cache", $localLiveCache,
    "--epoch-step", "25",
    "--poll-seconds", "$PollSeconds",
    "--quiesce-seconds", "$QuiesceSeconds",
    "--stop-stable-polls", "$StopStablePolls",
    "--scp-retries", "$ScpRetries",
    "--scp-retry-delay-seconds", "$ScpRetryDelaySeconds",
    "--extra-remote-path", "/root/SeniorProject/training_pilot/data/unified_bridge/dataset.yaml",
    "--extra-remote-path", "/root/SeniorProject/training_pilot/data/unified_bridge/bridge_manifest.json"
)

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
