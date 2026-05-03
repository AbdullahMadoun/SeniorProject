# Vast.ai YOLO Training Agent Directive

## Project Manager Context
You are tasked with executing a remote YOLO model training session on a pre-existing Vast.ai GPU instance. You must safely hijack the host without destroying its current inference server, set up an isolated training workspace, and smoke-test the GPU pipeline.

## 1. Remote Host Details
- **SSH Target**: `ssh -i D:\downloads\SeniorProject\Skylink2\deploy\backend\ssh\id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 19940 root@ssh7.vast.ai`
- **Current Service Path**: `/opt/skylink-model-server`
- **Current Status**: Running a lightweight YOLO inference server + `cloudflared`.
- **Public URL**: `https://girlfriend-richard-impressed-and.trycloudflare.com/analyze`

## 2. Execution Constraints
> [!CAUTION]
> - Do **NOT** lease a new Vast instance.
> - Do **NOT** destroy the current instance.
> - Do **NOT** rotate the current public URL unless strictly necessary.
> - Do **NOT** assume Docker is present; verify it.
> - Do **NOT** assume the dataset is ready; discover and state blockers clearly.
> - Prefer end-to-end execution over planning. Stop and report exactly what is missing if blocked by credentials, dataset absent, or configs.

## 3. Step-By-Step Mission
1. **Inspect Host State**:
   - Verify SSH Access.
   - Run `nvidia-smi` to confirm GPU visibility.
   - Check Disk, RAM, CUDA, Python, and Docker availability.
   - Profile `htop` / `nvidia-smi` to see what is using CPU/GPU.
2. **Environment Decision**:
   - Decide whether to train directly via bare-metal Python OR inside a Docker container (if Docker is present or if you choose to install it).
3. **De-confliction**:
   - If the current `/opt/skylink-model-server` or `cloudflared` consumes too much VRAM or port conflicts arise, safely `systemctl stop` or `kill` them. Do **NOT** delete their files.
4. **Workspace Generation**:
   - Create a fully isolated remote training directory separated from the inference server.
   - Rsync or sync only the necessary training scripts from `D:\downloads\SeniorProject` to this new directory.
5. **Dependencies**:
   - Install only the strict prerequisites needed for YOLO training (`ultralytics`, `torch`, etc.).
6. **Execution (Smoke Test)**:
   - Run a highly conservative, fast smoke-test first (e.g. 1 epoch, small batch). 
   - Verify that logs stream, GPU VRAM spikes actively, and checkpoints (`best.pt` / `last.pt`) populate the output directory.
7. **Final Reporting Requirements**:
   - Exact SSH/remote commands utilized.
   - Absolute path to the new remote training workspace.
   - Whether Docker was used.
   - Whether the inference service was actively suspended.
   - Path to the generated checkpoints.
   - Any definitive blockers preventing full-scale high-epoch training.
