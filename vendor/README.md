# Vendor Bootstrap

This directory is reserved for local upstream checkouts used by the drone autonomy stack.

It is intentionally not committed as full source in this repo because the upstream trees are large and should stay authoritative in their own repositories.

Expected local contents during SITL work:

- `PX4-Autopilot`
- `ardupilot`
- `MAVSDK-Python`

The tracked source of truth for setup commands is:

- [autonomy/docs/reproducibility_runbook.md](../autonomy/docs/reproducibility_runbook.md)

If the vendor directory is empty on GitHub, that is expected.
