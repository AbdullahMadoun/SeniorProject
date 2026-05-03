**Server Recovery**

Local recovery for `yolo12s_rezzzq_v5align` is prepared from mirrored artifacts on this machine.

Local sources:
- `artifacts/live_run_state/yolo12s_rezzzq_v5align`
- `artifacts/live_epoch_weights/yolo12s_rezzzq_v5align`

Build the local resume bundle:

```powershell
powershell -ExecutionPolicy Bypass -File D:\downloads\SeniorProject\Skylink2\training_pilot\scripts\prepare_yolo12_v5align_resume.ps1
```

That reconstructs a run-shaped directory at:

```text
D:\downloads\SeniorProject\Skylink2\training_pilot\artifacts\resume_bundles\yolo12s_rezzzq_v5align
```

The bundle contains:
- `args.yaml`
- `results.csv`
- `weights\last.pt`
- `weights\best.pt`
- `weights\epoch25.pt`
- `weights\epoch50.pt`
- `weights\epoch75.pt`
- `weights\epoch100.pt`
- `resume_bundle_manifest.json`

Remote recovery intent once the server is back:

1. Restore this bundle to:
   - `/root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_v5align`
2. Resume with:

```bash
cd /root/SeniorProject/training_pilot
python scripts/resume_model.py \
  --project-root /root/SeniorProject/training_pilot \
  --model-id yolo12s_rezzzq \
  --run-dir /root/SeniorProject/training_pilot/runs/yolo12s_rezzzq_v5align \
  --device 0 \
  --workers 8
```

Notes:
- `resume_model.py` uses `weights/last.pt` and calls `model.train(resume=True)`.
- This is intended to preserve the original run directory and continue the same training history.
- After `yolo12s_rezzzq_v5align` is healthy again, the ensemble chain can continue with `ozair_yolov8_v5align` and `oracl4_yolov8_v5align`.
