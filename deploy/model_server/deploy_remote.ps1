param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$RemoteUser = "root",
    [int]$SshPort = 22,
    [string]$RemotePath = "/opt/skylink-model-server",
    [ValidateSet("native", "docker_vm")]
    [string]$DeploymentMode = "native",
    [string]$ApiKey = "",
    [string]$Port = "17612",
    [switch]$DisableVlm,
    [switch]$EnableYoloV8,
    [ValidateSet("local", "api", "disabled")]
    [string]$VlmBackend = "local",
    [string]$VlmModel = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ",
    [string]$GpuMemUtil = "0.80",
    [string]$MaxModelLen = "16384",
    [string]$MaxOutputTokens = "16384",
    [string]$YoloV8WeightsUrl = "https://huggingface.co/oracl4/YOLOv8_Small_RDD/resolve/main/YOLOv8_Small_RDD.pt",
    [string]$YoloV8Path = "",
    [string]$YoloV12Repo = "rezzzq/yolo12s-road-damage-rdd2022",
    [string]$Yolo12RepoUrl = "https://github.com/sunsmarterjie/yolov12.git",
    [string]$Yolo12RepoRef = "",
    [string]$EnsembleMembers = "rezzzq_yolo12s_rdd2022,ozair_yolov8_rdd2022,oracl4_yolov8_rdd2022",
    [string]$DockerImageName = "skylink-model-server:latest",
    [string]$DockerContainerName = "skylink-model-server",
    [string]$HuggingFaceToken = "",
    [string]$PublicBaseUrl = "",
    [string]$PublicHost = "",
    [string]$BridgeEnvFile = "",
    [switch]$DisableTunnel,
    [switch]$SkipInstall,
    [switch]$SkipPrefetch,
    [switch]$SkipLaunch,
    [switch]$SkipWaitForHealth,
    [switch]$SkipWaitForTunnel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Key,
        [string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content $Path
    }

    $pattern = "^{0}=" -f [regex]::Escape($Key)
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "{0}={1}" -f $Key, $Value
            $updated = $true
        }
    }

    if (-not $updated) {
        $lines += "{0}={1}" -f $Key, $Value
    }

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
$modelServerDir = Join-Path $repoRoot "model_server"
$trainingWeightsDir = Join-Path $repoRoot "training_pilot\\weights"
$externalYolo12Dir = Join-Path $repoRoot "external\\yolov12"
$deployAssetDir = Resolve-Path $PSScriptRoot
$bootstrapScript = Join-Path $PSScriptRoot "bootstrap_remote.sh"
$remote = "{0}@{1}" -f $RemoteUser, $Server
$remoteModelDir = "$RemotePath/model_server"
$remoteDeployRoot = "$RemotePath/deploy"
$remoteDeployDir = "$remoteDeployRoot/model_server"
$remoteBootstrapPath = "$RemotePath/bootstrap_remote.sh"

if (-not (Test-Path $modelServerDir)) {
    throw "Missing model_server directory at $modelServerDir"
}
if (-not (Test-Path $trainingWeightsDir)) {
    throw "Missing training_pilot\\weights directory at $trainingWeightsDir"
}
if (-not (Test-Path $bootstrapScript)) {
    throw "Missing bootstrap script at $bootstrapScript"
}

if (-not $ApiKey) {
    $ApiKey = [guid]::NewGuid().ToString("N")
}
if (-not $YoloV8Path) {
    $YoloV8Path = "$remoteModelDir/models/YOLOv8_Small_RDD.pt"
}
$enableYoloV8 = if ($EnableYoloV8) { $true } elseif ($DisableVlm) { $false } else { $true }
$installLocalVlm = ((-not $DisableVlm) -and $VlmBackend -eq "local").ToString().ToLowerInvariant()
$enableVlmString = (-not $DisableVlm).ToString().ToLowerInvariant()
$enableYoloV8String = $enableYoloV8.ToString().ToLowerInvariant()
$enableTunnelString = (-not $DisableTunnel).ToString().ToLowerInvariant()
$waitForHealthString = (-not $SkipWaitForHealth).ToString().ToLowerInvariant()
$waitForTunnelString = (-not $SkipWaitForTunnel).ToString().ToLowerInvariant()
$prefetchModelsString = (-not $SkipPrefetch).ToString().ToLowerInvariant()

$envLines = @(
    "API_KEY=$ApiKey"
    "HOST=0.0.0.0"
    "PORT=$Port"
    "REMOTE_DEPLOY_MODE=$DeploymentMode"
    "DOCKER_IMAGE_NAME=$DockerImageName"
    "DOCKER_CONTAINER_NAME=$DockerContainerName"
    "ENABLE_VLM=$enableVlmString"
    "VLM_BACKEND=$VlmBackend"
    "INSTALL_LOCAL_VLM=$installLocalVlm"
    "ENABLE_YOLO_V8=$enableYoloV8String"
    "MODEL_NAME=$VlmModel"
    "VLM_MODEL=$VlmModel"
    "GPU_MEM_UTIL=$GpuMemUtil"
    "MAX_MODEL_LEN=$MaxModelLen"
    "MAX_OUTPUT_TOKENS=$MaxOutputTokens"
    "DETECTOR_MODE=ensemble"
    "ENSEMBLE_ENABLED=true"
    "ENSEMBLE_MEMBERS=$EnsembleMembers"
    "ENSEMBLE_MODEL_REZZZQ=$RemotePath/training_pilot/weights/rdd_trained_local/yolo12s_rezzzq_v5align/best.pt"
    "ENSEMBLE_MODEL_OZAIR=$RemotePath/training_pilot/weights/rdd_trained_local/ozair_yolov8_custom/best.pt"
    "ENSEMBLE_MODEL_ORACL4=$RemotePath/training_pilot/weights/rdd_trained_local/oracl4_yolov8_custom/best.pt"
    "YOLO_MODEL_V8=$YoloV8Path"
    "YOLO_MODEL_V12=$YoloV12Repo"
    "YOLO12_REPO_DIR=$RemotePath/external/yolov12"
    "YOLO12_REPO_URL=$Yolo12RepoUrl"
    "YOLO12_REPO_REF=$Yolo12RepoRef"
    "YOLO_V8_WEIGHTS_URL=$YoloV8WeightsUrl"
    "PUBLIC_BASE_URL=$PublicBaseUrl"
    "PUBLIC_HOST=$PublicHost"
    "ENABLE_QUICK_TUNNEL=$enableTunnelString"
    "WAIT_FOR_HEALTH=$waitForHealthString"
    "WAIT_FOR_TUNNEL=$waitForTunnelString"
    "PREFETCH_MODELS=$prefetchModelsString"
)
if ($HuggingFaceToken) {
    $envLines += "HUGGINGFACE_HUB_TOKEN=$HuggingFaceToken"
}

$tempEnv = Join-Path ([System.IO.Path]::GetTempPath()) ("skylink-model-{0}.env" -f [guid]::NewGuid().ToString("N"))
[System.IO.File]::WriteAllLines(
        $tempEnv,
        $envLines,
        [System.Text.UTF8Encoding]::new($false)
    )

try {
    ssh -p $SshPort $remote "mkdir -p $RemotePath $remoteDeployRoot $RemotePath/training_pilot $RemotePath/external"
    scp -P $SshPort -r $modelServerDir "${remote}:$RemotePath"
    scp -P $SshPort -r $trainingWeightsDir "${remote}:$RemotePath/training_pilot"
    if (Test-Path $externalYolo12Dir) {
        scp -P $SshPort -r $externalYolo12Dir "${remote}:$RemotePath/external"
    }
    scp -P $SshPort -r $deployAssetDir "${remote}:$remoteDeployRoot"
    scp -P $SshPort $bootstrapScript "${remote}:$remoteBootstrapPath"
    scp -P $SshPort $tempEnv "${remote}:$RemotePath/.env"
    ssh -p $SshPort $remote "chmod +x $remoteBootstrapPath $remoteModelDir/run.sh"

    if (-not $SkipLaunch) {
        $bootstrapSubcommand = if ($SkipInstall) { "start" } else { "bootstrap" }
        ssh -p $SshPort $remote "ROOT_DIR=$RemotePath $remoteBootstrapPath $bootstrapSubcommand"
    }

    $statusJson = ssh -p $SshPort $remote "ROOT_DIR=$RemotePath $remoteBootstrapPath status"
    $status = $statusJson | ConvertFrom-Json

    if ($BridgeEnvFile) {
        Set-EnvValue -Path $BridgeEnvFile -Key "SKYLINK_VLM_API_URL" -Value $status.analyze_url
        Set-EnvValue -Path $BridgeEnvFile -Key "SKYLINK_VLM_API_KEY" -Value $ApiKey
    }

    [PSCustomObject]@{
        Server = $Server
        RemotePath = $RemotePath
        DeploymentMode = $DeploymentMode
        AnalyzeUrl = $status.analyze_url
        ReachableBaseUrl = $status.reachable_base_url
        TunnelUrl = $status.tunnel_url
        ApiKey = $ApiKey
        BridgeEnvFile = $BridgeEnvFile
        Status = $status.status
    }
}
finally {
    Remove-Item -LiteralPath $tempEnv -ErrorAction SilentlyContinue
}
