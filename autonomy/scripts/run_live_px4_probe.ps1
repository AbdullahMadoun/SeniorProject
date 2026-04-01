Get-Process mavsdk_server -ErrorAction SilentlyContinue | Stop-Process -Force
wsl bash -lc "bash /mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/live_px4_probe.sh"
