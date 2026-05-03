# SkyLink Phase 1: Pi-Pixhawk USB bring-up notes

## Decisions log
- [2026-05-03] Phase 0: recon complete; see docs/PHASE0_RECON.md.
- [2026-05-03] Phase 0 review: Session 1 skipped (MAVProxy already in
  .venv-pi, dialout already configured per recon §C). Diagnostic
  scripts -> autonomy/companion/scripts/diagnostics/. Systemd /
  MAVProxy configs -> deploy/companion/. MAVProxy invocation:
  .venv-pi/bin/mavproxy.py. Working branch:
  feature/rpi5-companion-bringup. UDP endpoint: udp:127.0.0.1:14551
  (video_logger.py:30).
- [2026-05-03] Session 3: heartbeat_probe.py written at
  autonomy/companion/scripts/diagnostics/. Run with .venv-pi python.
- [2026-05-03] Session 4: Heartbeats confirmed. Live attitude streaming.
- [2026-05-03] Session 5: MAVProxy UDP endpoint pinned to 127.0.0.1:14551
  (source: autonomy/companion/video_logger.py:30, confirmed unchanged
  from Phase 0).
- [2026-05-03] Session 6: MAVProxy bridge UART->UDP verified at
  127.0.0.1:14551 using .venv-pi MAVProxy.
- [2026-05-03] Session 7: End-to-end smoke test PASSED. Run dir:
  /tmp/skylink_session7_run/. 50/50 frames captured via picamera2
  (real OV5647); ATTITUDE+VFR_HUD streamed through the MAVProxy
  bridge with att_age max 17 ms, vfr_age max 105 ms,
  telemetry_errors_count=0. Attitude populated and stable
  (autopilot stationary). lat/lon/alt all null and CSV
  telemetry_source=none — expected indoors without GPS lock; PX4
  does not stream GLOBAL_POSITION_INT, so telemetry_updates=0 in
  summary. No code changes to video_logger.py.
- [2026-05-03] Session 8: mavproxy-skylink.service installed with
  Type=simple + --daemon, Restart=on-failure, StartLimitBurst=5/60s
  (in [Unit]), and dev-ttyACM0.device dependency. Active and forwarding;
  listener probe PROBE OK with 1699 MAVLink v2 datagrams in 5s.
  Note: Type=forking was attempted in v2 and failed because
  MAVProxy 1.8.74's --daemon suppresses the interactive shell but does
  not fork — Type=simple matches the actual single-PID foreground
  behavior.
- [2026-05-03] Session 9: Reboot persistence VERIFIED. Service
  auto-started; heartbeat probe OK; UDP bridge OK.

## Diagnostic script conventions

Diagnostic scripts live in `autonomy/companion/scripts/diagnostics/`
(per the 2026-05-03 review above). Each is single-responsibility,
type-hinted, has CLI via argparse, prints `PROBE OK` or
`PROBE FAIL: <reason>` as the final stdout line, and exits 0/non-zero
accordingly. Probes are read-only — they never write to the autopilot.
