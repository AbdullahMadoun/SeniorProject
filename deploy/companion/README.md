# SkyLink Companion: MAVProxy systemd bridge

## Overview

`mavproxy-skylink.service` runs MAVProxy as a background system service on
the Raspberry Pi 5 companion. It opens the Pixhawk 4 over USB-CDC at
`/dev/ttyACM0`, speaks MAVLink, and forwards the stream to
`udp:127.0.0.1:14551` — the default endpoint that
`autonomy/companion/video_logger.py` listens on
(`DEFAULT_MAVLINK_TARGET`). Once the bridge is up, the Python pipeline can
attach and detach freely without ever touching the serial port directly.

This directory is the systemd-side companion to the Python pipeline in
`autonomy/companion/`.

## Prerequisites

- `.venv-pi` built per `autonomy/companion/bootstrap_rpi_companion.sh`.
  The unit calls `.venv-pi/bin/mavproxy.py` directly, so MAVProxy 1.8.74
  (pinned in `autonomy/companion/requirements-rpi.txt`) must be present
  inside that venv.
- User `pi` is a member of the `dialout` group so it can open
  `/dev/ttyACM0` without root.
- Pixhawk 4 reachable over USB at `/dev/ttyACM0`. USB-CDC enumeration
  takes ~30 s after autopilot power-on (the bootloader appears first,
  then the runtime firmware re-enumerates). The unit's
  `Requires=dev-ttyACM0.device` handles that wait, so the service will
  not race the autopilot at boot.

## Install

Copy the unit, reload systemd, and enable it:

```bash
sudo cp deploy/companion/mavproxy-skylink.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mavproxy-skylink
```

## Verify

Check that the unit is running:

```bash
systemctl status mavproxy-skylink --no-pager
```

Expect `Active: active (running)`.

Confirm the bridge is forwarding traffic by running the UDP listener
probe against port 14551:

```bash
.venv-pi/bin/python autonomy/companion/scripts/diagnostics/udp_listener_probe.py \
  --host 127.0.0.1 --port 14551
```

Expect `PROBE OK` and several hundred MAVLink v2 datagrams in the
default 5 s window. The probes themselves are documented under
`autonomy/companion/scripts/diagnostics/`; this README does not
duplicate their CLI.

## Disable / Stop / Uninstall

Stop the service for the rest of this boot without disabling it:

```bash
sudo systemctl stop mavproxy-skylink
```

Disable so it does not auto-start on the next boot:

```bash
sudo systemctl disable --now mavproxy-skylink
```

Full uninstall, removing the unit file as well:

```bash
sudo systemctl disable --now mavproxy-skylink
sudo rm /etc/systemd/system/mavproxy-skylink.service
sudo systemctl daemon-reload
```

## Troubleshooting

If the service is flapping or stuck in a restart loop, read the journal:

```bash
journalctl -u mavproxy-skylink -n 60 --no-pager
```

The unit caps restarts at `StartLimitBurst=5` per 60 s, so a hard
configuration error fails fast rather than chewing CPU forever.

If `/dev/ttyACM0` is missing, confirm the Pixhawk is plugged in and has
finished booting. `lsusb` should show `idVendor=26ac` with the product
string `PX4 FMU v5.x`. If you see `PX4 BL FMU v5.x` instead, the
autopilot is still in its USB bootloader — wait for the runtime firmware
to re-enumerate (~30 s).

If the listener probe reports zero datagrams while the service is
`active (running)`, another process is holding the UDP port. Check with:

```bash
fuser -v 14551/udp
```

A common culprit is a stale interactive `mavproxy.py` left over from a
manual debugging session.

## Design decisions

The unit runs as `Type=simple` with MAVProxy's `--daemon` flag.
`--daemon` only suppresses the interactive console; the process stays in
the foreground as a single PID, which is exactly what `Type=simple`
models. Earlier attempts (`Type=simple` without `--daemon`,
`Type=forking` with `--daemon`) failed for reasons recorded in the unit
file's comment header — see `mavproxy-skylink.service` for the full
v1 → v2 → v3 reasoning. The header is the canonical record; it is not
recapitulated here.
