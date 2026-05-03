param(
    [string]$Model = "gz_x500",
    [string]$World = "",
    [switch]$Headless = $true
)

$repo = "/mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot"
$arguments = @("--cd", $repo, "--")

$envArgs = @()
if ($Headless) {
    $envArgs += "HEADLESS=1"
}

if (-not [string]::IsNullOrWhiteSpace($World)) {
    $envArgs += "PX4_GZ_WORLD=$World"
}

$arguments += "env"
$arguments += $envArgs
$arguments += @("make", "px4_sitl", $Model)

wsl @arguments
