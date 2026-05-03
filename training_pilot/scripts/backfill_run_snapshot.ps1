param(
  [Parameter(Mandatory = $true)][string]$RemoteRunDir,
  [Parameter(Mandatory = $true)][string]$LocalOutputRoot
)

$ErrorActionPreference = "Stop"

$sshKey = Join-Path $HOME ".ssh\id_ed25519"
if (-not (Test-Path $sshKey)) {
  throw "Missing SSH key: $sshKey"
}

$runName = Split-Path $RemoteRunDir -Leaf
$targetDir = Join-Path $LocalOutputRoot $runName
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

scp -r `
  -o StrictHostKeyChecking=no `
  -o UserKnownHostsFile=NUL `
  -o ConnectTimeout=20 `
  -i $sshKey `
  -P 10022 `
  "root@ssh2.vast.ai:$RemoteRunDir" `
  $LocalOutputRoot

Write-Output "snapshot=$targetDir"
