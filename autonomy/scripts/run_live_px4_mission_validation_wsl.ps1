param(
    [string]$SystemAddress = "udpin://0.0.0.0:14540",
    [double]$ConnectTimeoutSeconds = 15.0
)

$repo = "/mnt/d/downloads/SeniorProject/Skylink2"
$command = @(
    "--cd", $repo, "--", "env",
    "MAVSDK_SYSTEM_ADDRESS=$SystemAddress",
    "MAVSDK_CONNECT_TIMEOUT_S=$ConnectTimeoutSeconds",
    "python3",
    "autonomy/scripts/validate_live_px4_mission.py"
)

wsl @command
