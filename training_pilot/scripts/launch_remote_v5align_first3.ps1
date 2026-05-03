param(
    [string]$SshHost = "ssh2.vast.ai",
    [int]$SshPort = 10022,
    [string]$SshUser = "root",
    [string]$SshKey = "$HOME\.ssh\id_ed25519"
)

$remoteCommand = @'
/bin/bash -lc '
set -e
cd /root/SeniorProject/training_pilot
chmod +x scripts/launch_v5align_first3.sh
log=/root/SeniorProject/training_pilot/artifacts/logs/ensemble_v5align_first3.log
tmux kill-session -t ensemble_v5align_train 2>/dev/null || true
tmux new -d -s ensemble_v5align_train "cd /root/SeniorProject/training_pilot; PYTHON_BIN=python DEVICE=0 WORKERS=8 bash scripts/launch_v5align_first3.sh > $log 2>&1"
sleep 8
tmux ls 2>/dev/null
echo ====
head -n 80 "$log" || true
'
'@

$sshArgs = @(
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL",
    "-i", $SshKey,
    "-p", $SshPort.ToString(),
    "$SshUser@$SshHost",
    $remoteCommand
)

& ssh @sshArgs
exit $LASTEXITCODE
