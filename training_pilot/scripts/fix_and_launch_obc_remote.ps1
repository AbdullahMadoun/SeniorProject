param(
    [string]$SshHost = "ssh2.vast.ai",
    [int]$SshPort = 10022,
    [string]$SshUser = "root",
    [string]$SshKey = "$HOME\.ssh\id_ed25519"
)

$remoteCommand = @'
set -e
cd /root/SeniorProject/training_pilot
Q=/root/SeniorProject/training_pilot/external/OBC-YOLOv8/ultralytics10.24/ultralytics/nn
if [ ! -f "$Q/qlhnet.py" ] && [ -f "$Q/.ipynb_checkpoints/qlhnet-checkpoint.py" ]; then
  cp "$Q/.ipynb_checkpoints/qlhnet-checkpoint.py" "$Q/qlhnet.py"
fi
python3 -c "import sys; sys.path.insert(0, '/root/SeniorProject/training_pilot/external/OBC-YOLOv8/ultralytics10.24'); import ultralytics; print('IMPORT_OK', ultralytics.__file__)"
log=/root/SeniorProject/training_pilot/artifacts/logs/obc_initial_resume.log
rm -f "$log"
tmux kill-session -t maxrecall_obc 2>/dev/null || true
tmux new -d -s maxrecall_obc "cd /root/SeniorProject/training_pilot && python scripts/train_model.py --project-root /root/SeniorProject/training_pilot --model-id obc_yolov8 --device 0 --workers 8 --stage initial > $log 2>&1"
sleep 6
tmux ls 2>/dev/null
printf '\n====LOG====\n'
head -n 80 "$log" || true
'@

$sshArgs = @(
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-i", $SshKey,
    "-p", $SshPort.ToString(),
    "$SshUser@$SshHost",
    "bash", "-lc", $remoteCommand
)

& ssh @sshArgs
exit $LASTEXITCODE
