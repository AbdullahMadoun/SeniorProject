# Drone Platform Runbook

This runbook is the GitHub-facing shortcut to the current drone-stack commands.

## 1. Baseline Validation

```powershell
python -m unittest discover -s D:\downloads\SeniorProject\Skylink2\autonomy\tests -p "test_*.py"
```

Expected result:

- `Ran 51 tests ... OK`

## 2. Rebuild The Judge-Facing Showcase

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

Outputs:

- [manifest.json](../artifacts/replay_bundle/latest/manifest.json)
- [index.html](../artifacts/showcase/latest/index.html)
- [showcase_data.json](../artifacts/showcase/latest/showcase_data.json)

## 3. Serve The Showcase Locally

```powershell
python -m http.server 8888 --directory D:\downloads\SeniorProject\Skylink2\artifacts\showcase\latest
```

Open:

- `http://127.0.0.1:8888`

## 4. Refresh Live PX4 Inputs

Use this when the showcase needs fresh live waypoint geometry or fresh live attitude telemetry:

```powershell
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_mission_validation.ps1
D:\downloads\SeniorProject\Skylink2\autonomy\scripts\run_live_px4_dock_approach_validation.ps1
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
```

## 5. Full Reference

For the complete environment and WSL/PX4 setup flow, use:

- [autonomy/docs/reproducibility_runbook.md](../autonomy/docs/reproducibility_runbook.md)
- [autonomy/docs/installation_log.md](../autonomy/docs/installation_log.md)
