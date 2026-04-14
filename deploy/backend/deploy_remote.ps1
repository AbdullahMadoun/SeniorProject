param(
    [Parameter(Mandatory = $true)]
    [string]$Registry,
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$ImageName = "skylink-backend",
    [string]$RemoteUser = "root",
    [string]$RemotePath = "/opt/skylink-backend",
    [string]$Tag = "latest",
    [string]$EnvFile = "",
    [string]$SshDir = "",
    [switch]$BuildAndPush,
    [switch]$PushLatest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$registryPrefix = $Registry.TrimEnd("/")
$scriptRoot = $PSScriptRoot
$publishScript = Join-Path $scriptRoot "publish.ps1"
$composeSource = Join-Path $scriptRoot "docker-compose.server.yml"
$remote = "{0}@{1}" -f $RemoteUser, $Server
$imageRef = "{0}/{1}:{2}" -f $registryPrefix, $ImageName, $Tag

if ($BuildAndPush) {
    & $publishScript -Registry $Registry -ImageName $ImageName -Tag $Tag -PushLatest:$PushLatest
}

ssh $remote "mkdir -p $RemotePath"
scp $composeSource "${remote}:$RemotePath/docker-compose.yml"

if ($EnvFile) {
    scp $EnvFile "${remote}:$RemotePath/.env"
}

if ($SshDir) {
    ssh $remote "mkdir -p $RemotePath/ssh"
    scp -r $SshDir "${remote}:$RemotePath"
}

$remoteCommand = @"
set -e
cd $RemotePath
export IMAGE='$imageRef'
docker compose pull
docker compose up -d --remove-orphans
"@

ssh $remote $remoteCommand

Write-Host "Deployed image: $imageRef"
