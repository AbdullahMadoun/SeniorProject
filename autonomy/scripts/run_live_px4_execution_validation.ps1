Get-Process mavsdk_server -ErrorAction SilentlyContinue | Stop-Process -Force
wsl bash -lc "export LIVE_PX4_VALIDATOR_SCRIPT='/mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/validate_live_px4_execution.py'; export LIVE_PX4_VALIDATOR_LABEL='EXECUTION_VALIDATION'; bash /mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/live_px4_probe.sh"
