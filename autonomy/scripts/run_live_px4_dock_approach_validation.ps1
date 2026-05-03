Get-Process mavsdk_server -ErrorAction SilentlyContinue | Stop-Process -Force
wsl bash -lc "export LIVE_PX4_VALIDATOR_SCRIPT='/mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_dock_approach.py'; export LIVE_PX4_VALIDATOR_LABEL='DOCK_APPROACH_VALIDATION'; bash /mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/live_px4_probe.sh"
