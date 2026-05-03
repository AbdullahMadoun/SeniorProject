# Master Vast.ai Agent Directive: YOLO Training & Headless SITL

## Project Manager Context
You are an autonomous coding agent tasked with setting up a dual-purpose environment on a remote Vast.ai GPU instance. You must safely deploy a YOLO model training session while preserving the current ecosystem, AND you must set up a headless PX4 SITL (Software In The Loop) simulation. The SITL simulation must be fully independent of hardware but built on standard `pymavlink` architecture so it translates 1:1 to the physical drone later.

## 1. Remote Host Details
- **SSH Target**: `ssh -i D:\downloads\SeniorProject\Skylink2\deploy\backend\ssh\id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 19940 root@ssh7.vast.ai`
- **Current Service**: Lightweight YOLO inference server + `cloudflared`.

## 2. Execution Constraints
> [!CAUTION]
> - Do **NOT** lease a new Vast instance or destroy the current one.
> - Do **NOT** assume Docker is present; verify it.
> - Prefer end-to-end execution. If you lack dataset credentials, report it immediately.

## 3. Mission Phase 1: YOLO Training Workspace
1. **Inspect Host State**: Verify SSH, `nvidia-smi`, RAM, and active processes.
2. **De-confliction**: If the `/opt/skylink-model-server` or `cloudflared` services consume too much VRAM, safely suspend them (`systemctl stop`). Do not delete them.
3. **Training Execution**: Run a conservative smoke-test first (1 epoch) on the GPU. Verify checkpoints (`best.pt`) are generated successfully.

## 4. Mission Phase 2: Headless PX4 SITL Deployment
The user requires a PX4 simulation environment running on this GPU server. It must behave identically to the physical Raspberry Pi + Pixhawk rig.
1. **Dockerized PX4**: Deploy the official `px4io/px4-dev-simulation-focal` (or equivalent Gazebo container) on the Vast.ai instance.
2. **Headless Execution**: Ensure Gazebo runs headlessly (e.g., `HEADLESS=1 make px4_sitl gazebo`).
3. **Networking (Crucial for Hardware Parity)**: Expose UDP port `14550`. On the physical drone, the computer talks to Pixhawk via UART/MAVLink. In this SITL, scripts will talk to the simulation via UDP `127.0.0.1:14550`. This ensures zero python code changes when the user switches from the server SITL to the real drone.
4. **Validation**: Write a simple Python `pymavlink` script on the server to send `HEARTBEAT` or `COMMAND_LONG` (takeoff) to confirm the SITL is receiving commands.

## Final Output Expected from You:
Provide the user with:
1. The path to the verified YOLO checkpoints.
2. The exact commands you ran to spawn the detached PX4 SITL Docker container.
3. Proof that `pymavlink` reached the headless SITL on port `14550`.
