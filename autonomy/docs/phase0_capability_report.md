# Phase 0 Capability Report

- OS: `Microsoft Windows 11 Home`
- CPU: `Intel(R) Core(TM) i5-8265U CPU @ 1.60GHz`
- Cores / Threads: `4 / 8`
- RAM: `7.85 GB` total, `1.06 GB` free
- GPU: `Intel(R) UHD Graphics 620`
- GPU VRAM: `1.00 GB`
- WSL available: `True`

## Recommendation

Use lightweight visualization as the baseline; keep full 3D simulation optional.

## Rationale

- System RAM is below the preferred 16 GB baseline for comfortable Gazebo-class simulation.
- GPU VRAM is limited, so integrated-graphics rendering is a constraint for 3D simulation.
- Current free RAM is low, which increases the risk of instability for heavy simulators.
