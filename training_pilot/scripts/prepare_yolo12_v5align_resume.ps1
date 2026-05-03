param()

$repoRoot = "D:\downloads\SeniorProject\Skylink2\training_pilot"
$script = Join-Path $repoRoot "scripts\prepare_local_resume_bundle.py"
$outputRoot = Join-Path $repoRoot "artifacts\resume_bundles"

python $script `
  --run-name "yolo12s_rezzzq_v5align" `
  --state-dir "D:\downloads\SeniorProject\Skylink2\artifacts\live_run_state\yolo12s_rezzzq_v5align" `
  --weights-dir "D:\downloads\SeniorProject\Skylink2\artifacts\live_epoch_weights\yolo12s_rezzzq_v5align" `
  --output-root $outputRoot
