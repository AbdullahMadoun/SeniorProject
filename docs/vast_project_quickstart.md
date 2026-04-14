# Vast Quickstart For Skylink2

## Why This Note Exists

Use this when told to connect to or create a Vast.ai instance for `Skylink2`.

The main lesson: do not guess the Vast mode.

- Use a standard Vast container instance when one container can run the workload directly.
- Use a Vast VM when the remote host itself must run Docker, Compose, `systemd`, or similar host-level tooling.

For this project:

- YOLO model serving or Python training can usually use a standard Vast instance.
- Dockerized PX4 SITL should default to a Vast VM, because the host must run Docker on the remote machine.

## What Helped From The Skill

The `vast-docker-remote-compute` skill was useful for four reasons:

1. It made the Docker-instance vs VM boundary explicit.
2. It reinforced template-first launches instead of ad hoc instance creation.
3. It clarified that account/API access and SSH key registration are prerequisites, not optional cleanup.
4. It explained why old SSH host/port notes are not reliable; recover the live endpoint from the Vast API each time.

## Default Rules For This Repo

1. Reuse an existing instance if the task says so.
2. Do not trust stale `sshX.vast.ai:port` values from old notes without checking the live instance record.
3. Require `VAST_API_KEY` or `SKYLINK_VAST_API_KEY` before trying to recover or create anything.
4. Prefer helper script usage over hand-built API payloads.

Helper script:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py --help
```

## Reconnect To An Existing Instance

List live instances:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py instances
```

Inspect one instance:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py show-instance --instance-id <ID>
```

Wait until SSH is ready:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py wait-instance --instance-id <ID> --timeout-seconds 900 --require-ssh
```

If the instance is a standard container and the current key is missing, attach the public key:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py attach-ssh-key --instance-id <ID> --public-key-file C:\Users\mohdm\.ssh\id_ed25519.pub
```

Then SSH using the returned `ssh_host` and `ssh_port`.

## Create A New Instance Only When Explicitly Told

### A. Standard Container Path

Use this for model server or direct Python workloads.

Search offers:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py offers --offer-type ondemand --verified --min-reliability 0.995 --min-gpu-ram-gb 24 --min-direct-ports 2 --allocated-storage-gb 64 --limit 20
```

Create a template:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py create-template --name skylink2-model-ssh --image vastai/pytorch --tag cuda-13.0.2-auto --runtype ssh --recommended-disk-space 64
```

Create the instance:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py create-instance --offer-id <OFFER_ID> --template-hash-id <TEMPLATE_HASH> --disk-gb 64
```

### B. VM Path

Use this for PX4 Dockerized SITL or anything that needs Docker on the remote host.

Search VM-capable offers:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py offers --offer-type ondemand --verified --vm-capable --min-reliability 0.995 --allocated-storage-gb 96 --limit 20
```

Create a VM template:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py create-template --name skylink2-px4-vm --image docker.io/vastai/kvm --tag ubuntu_terminal --runtype ssh --recommended-disk-space 96 --extra-filter-json "{\"vms_enabled\":{\"eq\":true}}"
```

Create the VM instance:

```powershell
python C:\Users\mohdm\.codex\skills\vast-docker-remote-compute\scripts\vast_probe.py create-instance --offer-id <OFFER_ID> --template-hash-id <TEMPLATE_HASH> --disk-gb 96
```

## Before Starting Work On The Remote Host

Always verify:

```powershell
ssh -i D:\downloads\SeniorProject\Skylink2\deploy\backend\ssh\id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p <SSH_PORT> root@<SSH_HOST> "hostname; nvidia-smi; free -h; df -h"
```

For this repo, also decide early:

- if reusing an existing instance is mandatory
- if the task needs only one runtime container
- if the task needs host-level Docker, which means VM

## Anti-Patterns

- Do not assume standard Vast instances can run Docker-in-Docker.
- Do not trust an old SSH port without checking the current instance state.
- Do not create a new instance when the task explicitly says reuse the current one.
- Do not keep a failed paid instance running while debugging basic connectivity.
