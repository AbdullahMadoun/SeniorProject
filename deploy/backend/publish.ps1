param(
    [Parameter(Mandatory = $true)]
    [string]$Registry,
    [string]$ImageName = "skylink-backend",
    [string]$Tag,
    [switch]$PushLatest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$appRoot = Join-Path $repoRoot "app"
$registryPrefix = $Registry.TrimEnd("/")

if (-not $Tag) {
    $gitTag = $null
    try {
        $gitTag = (git -C $repoRoot rev-parse --short HEAD).Trim()
    } catch {
        $gitTag = $null
    }

    if (-not $gitTag) {
        $gitTag = Get-Date -Format "yyyyMMddHHmmss"
    }

    $Tag = $gitTag
}

$imageRef = "{0}/{1}:{2}" -f $registryPrefix, $ImageName, $Tag
$latestRef = "{0}/{1}:latest" -f $registryPrefix, $ImageName

docker info | Out-Null
docker build --pull -t $imageRef -f (Join-Path $appRoot "Dockerfile") $appRoot
docker push $imageRef

if ($PushLatest) {
    docker tag $imageRef $latestRef
    docker push $latestRef
}

Write-Host "Published image: $imageRef"
