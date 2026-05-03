**Offline Operation**

Training should be treated as server-owned, not laptop-owned.

What that means:
- Run training inside `tmux` on the server.
- Keep `save_period: 25` and rolling `best.pt` / `last.pt`.
- Use laptop mirroring as a best-effort cache, not as a runtime dependency.
- If the laptop goes offline, the server training should continue unchanged.

Recommended remote launch for the V5-aligned chain:

```bash
cd /root/SeniorProject/training_pilot
bash scripts/launch_v5align_tmux.sh
bash scripts/rebuild_curated_tensorboard.sh
```

That gives:
- `ensemble_v5align_train` tmux session for the training chain
- `ensemble_tensorboard` tmux session for TensorBoard

When the laptop is back online, catch up with a one-shot snapshot:

```powershell
powershell -ExecutionPolicy Bypass -File D:\downloads\SeniorProject\Skylink2\training_pilot\scripts\backfill_run_snapshot.ps1 `
  -RemoteRunDir /root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_v5align `
  -LocalOutputRoot D:\downloads\SeniorProject\Skylink2\artifacts\backfill_snapshots
```

If strict resume is needed after a server interruption:

1. Build the local recovery bundle:

```powershell
powershell -ExecutionPolicy Bypass -File D:\downloads\SeniorProject\Skylink2\training_pilot\scripts\prepare_yolo12_v5align_resume.ps1
```

2. Restore the bundle to the server run path.

3. Resume:

```bash
cd /root/SeniorProject/training_pilot
python scripts/resume_model.py \
  --project-root /root/SeniorProject/training_pilot \
  --model-id yolo12s_rezzzq \
  --run-dir /root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_v5align \
  --device 0 \
  --workers 8
```

TensorBoard:
- server-side process is independent of laptop connectivity
- local browser access still requires the SSH tunnel when you are back online
