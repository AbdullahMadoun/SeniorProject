param(
  [switch]$IncludeV5Align
)

$scriptDir = 'D:\downloads\SeniorProject\Skylink2\training_pilot\scripts'
$repoRoot = 'D:\downloads\SeniorProject\Skylink2'
$python = 'python'
$sshHost = 'ssh2.vast.ai'
$sshPort = '10022'
$sshUser = 'root'
$sshKey = Join-Path $HOME '.ssh\id_ed25519'
$logRoot = Join-Path $repoRoot 'artifacts\mirror_logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$runs = @(
  @{ Name='yolo12s_rezzzq_custom'; Remote='/root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_custom' },
  @{ Name='ozair_yolov8_custom'; Remote='/root/SeniorProject/training_pilot/runs/ozair_yolov8_custom' },
  @{ Name='oracl4_yolov8_custom'; Remote='/root/SeniorProject/training_pilot/runs/oracl4_yolov8_custom' }
)

if ($IncludeV5Align) {
  $runs += @(
    @{ Name='yolo12s_rezzzq_v5align'; Remote='/root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_v5align' },
    @{ Name='ozair_yolov8_v5align'; Remote='/root/SeniorProject/training_pilot/runs/ozair_yolov8_v5align' },
    @{ Name='oracl4_yolov8_v5align'; Remote='/root/SeniorProject/training_pilot/runs/oracl4_yolov8_v5align' },
    @{ Name='obc_yolov8_v5align'; Remote='/root/SeniorProject/training_pilot/runs/obc_yolov8_v5align' }
  )
}

foreach ($run in $runs) {
  $stateDir = Join-Path $repoRoot ("artifacts\\live_run_state\\{0}" -f $run.Name)
  $weightsDir = Join-Path $repoRoot ("artifacts\\live_epoch_weights\\{0}" -f $run.Name)
  New-Item -ItemType Directory -Force -Path $stateDir, $weightsDir | Out-Null

  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*sync_remote_run_metadata.py*" -and $_.CommandLine -like "*$($run.Name)*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*sync_remote_epoch_checkpoints.py*" -and $_.CommandLine -like "*$($run.Name)*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

  $metaArgs = @(
    (Join-Path $scriptDir 'sync_remote_run_metadata.py'),
    '--ssh-host', $sshHost,
    '--ssh-port', $sshPort,
    '--ssh-user', $sshUser,
    '--ssh-key', $sshKey,
    '--remote-file', "$($run.Remote)/results.csv",
    '--remote-file', "$($run.Remote)/args.yaml",
    '--remote-file', "$($run.Remote)/results.png",
    '--remote-file', "$($run.Remote)/PR_curve.png",
    '--remote-file', "$($run.Remote)/P_curve.png",
    '--remote-file', "$($run.Remote)/R_curve.png",
    '--remote-file', "$($run.Remote)/F1_curve.png",
    '--remote-file', "$($run.Remote)/confusion_matrix.png",
    '--remote-file', "$($run.Remote)/confusion_matrix_normalized.png",
    '--local-dir', $stateDir,
    '--poll-seconds', '30',
    '--idle-timeout-seconds', '43200',
    '--connect-timeout-seconds', '20',
    '--scp-retries', '6',
    '--scp-retry-delay-seconds', '15'
  )
  $metaName = "mirror_meta_$($run.Name)"
  Start-Process -FilePath $python -ArgumentList $metaArgs -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "$metaName.out.log") -RedirectStandardError (Join-Path $logRoot "$metaName.err.log") | Out-Null

  $ckptArgs = @(
    (Join-Path $scriptDir 'sync_remote_epoch_checkpoints.py'),
    '--ssh-host', $sshHost,
    '--ssh-port', $sshPort,
    '--ssh-user', $sshUser,
    '--ssh-key', $sshKey,
    '--remote-run-dir', $run.Remote,
    '--local-dir', $weightsDir,
    '--epoch-step', '25',
    '--poll-seconds', '60',
    '--idle-timeout-seconds', '43200',
    '--connect-timeout-seconds', '20',
    '--scp-retries', '6',
    '--scp-retry-delay-seconds', '20'
  )
  $ckptName = "mirror_ckpt_$($run.Name)"
  Start-Process -FilePath $python -ArgumentList $ckptArgs -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "$ckptName.out.log") -RedirectStandardError (Join-Path $logRoot "$ckptName.err.log") | Out-Null
}
