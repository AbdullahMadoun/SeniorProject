# SkyLink Vast PX4 Simulation

This path adds a Linux/Vast.ai execution lane for the PX4 SITL validation stack without replacing the existing Windows/WSL workflow.

Use it when the simulation workload should run on a remote Ubuntu GPU/VM host and the local workstation should stay focused on editing, artifact review, or dashboard work.

## Docker First

For fresh machines and Vast VMs, the supported path is now the simulation container. It bundles the autonomy stack, bootstraps `vendor/PX4-Autopilot` automatically during image build, and runs the existing mission planner/API on port `8625`.

Build and run it from the repo root:

```powershell
docker compose -f .\docker-compose.simulation.yml up --build
```

Then open:

- `http://127.0.0.1:8625/planner/index.html`

That path is intended to be self-contained:

- no manual PX4 checkout on the host
- no WSL requirement
- no ad-hoc host package bootstrap after the image is built

## Scope

- `vast_probe.py`
  - small repo-local Vast.ai helper
  - can list instances, inspect one instance, fetch bounded boot logs, wait for SSH readiness, search offers, create templates, create instances, and attach an SSH key
- `bootstrap_remote.sh`
  - bootstraps PX4 SITL prerequisites on a Linux host and clones `vendor/PX4-Autopilot` automatically when it is missing
- Linux-native validation wrappers under `autonomy/scripts/`
  - probe
  - mission validation
  - execution validation
  - precision-landing profile
  - landing-target stream
  - dock-approach validation

## Credentials

`vast_probe.py` loads the API key from the first available source:

- `SKYLINK_VAST_API_KEY`
- `VAST_API_KEY`
- `VAST_API`
- repo `.env`

For this workspace, the existing repo `.env` is enough.

## Reconnect To An Existing Instance

List live instances:

```powershell
python .\deploy\simulation\vast_probe.py instances
```

Inspect one instance:

```powershell
python .\deploy\simulation\vast_probe.py show-instance --instance-id <ID>
```

Fetch the last 120 boot/runtime log lines without an unbounded polling loop:

```powershell
python .\deploy\simulation\vast_probe.py request-logs --instance-id <ID> --tail-lines 120 --timeout-seconds 120
```

Wait for SSH:

```powershell
python .\deploy\simulation\vast_probe.py wait-instance --instance-id <ID> --timeout-seconds 900 --require-ssh
```

If the instance is SSH-capable and your public key is not attached yet:

```powershell
python .\deploy\simulation\vast_probe.py attach-ssh-key --instance-id <ID> --public-key-file C:\Users\<you>\.ssh\id_ed25519.pub
```

## Search And Create

### VM-capable offers for PX4 SITL

```powershell
python .\deploy\simulation\vast_probe.py offers `
  --offer-type ondemand `
  --verified `
  --vm-capable `
  --min-reliability 0.995 `
  --allocated-storage-gb 96 `
  --limit 20
```

### Create a VM-oriented template

```powershell
python .\deploy\simulation\vast_probe.py create-template `
  --name skylink2-px4-vm `
  --image docker.io/vastai/kvm `
  --tag ubuntu_terminal `
  --runtype ssh `
  --recommended-disk-space 96 `
  --extra-filter-json "{\"vms_enabled\":{\"eq\":true}}"
```

### Create the instance

```powershell
python .\deploy\simulation\vast_probe.py create-instance `
  --offer-id <OFFER_ID> `
  --template-hash-id <TEMPLATE_HASH> `
  --disk-gb 96 `
  --label skylink2-px4-vm `
  --vm `
  --runtype ssh
```

## Before Running PX4

SSH into the remote machine and verify basic capacity first:

```bash
hostname
nvidia-smi
free -h
df -h
```

Make sure this repo is present on the remote host. Then bootstrap it:

```bash
cd /path/to/Skylink2
bash deploy/simulation/bootstrap_remote.sh bootstrap
```

That step:

- installs Ubuntu prerequisites
- syncs git submodules
- clones `vendor/PX4-Autopilot` at `v1.14.3` if it is missing
- runs `vendor/PX4-Autopilot/Tools/setup/ubuntu.sh --no-nuttx`
- creates `autonomy/.venv`
- installs the Python packages required by the live PX4 validators
- builds `make px4_sitl gz_x500`

## Remote Validation Commands

Run these on the Linux/Vast host inside the repo root.

Probe:

```bash
bash autonomy/scripts/run_live_px4_probe_linux.sh
```

Mission validation:

```bash
bash autonomy/scripts/run_live_px4_mission_validation_linux.sh
```

Execution validation:

```bash
bash autonomy/scripts/run_live_px4_execution_validation_linux.sh
```

Precision-landing PX4 parameter profile:

```bash
bash autonomy/scripts/run_live_px4_precision_landing_profile_linux.sh
```

Projected `LANDING_TARGET` stream:

```bash
bash autonomy/scripts/run_live_px4_landing_target_stream_linux.sh
```

`LANDING_TARGET` consumption proof:

```bash
bash autonomy/scripts/run_live_px4_landing_target_consumption_linux.sh
```

Dock approach with projected landing target injection:

```bash
bash autonomy/scripts/run_live_px4_dock_approach_validation_linux.sh
```

## Outputs

These commands keep the existing artifact contracts:

- `artifacts/live_px4/*.json`
- `artifacts/sitl_logs/*.log`

That means the same replay/showcase/dashboard build steps can consume the outputs after they are copied back or produced in a shared checkout.
