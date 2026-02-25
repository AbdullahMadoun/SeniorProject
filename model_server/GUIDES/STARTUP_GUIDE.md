# 📑 Hyper-Detailed Startup Guide: Road Inspector API
This document provides a **repeatable, zero-fail blueprint** for deploying the Road Inspector Hybrid Pipeline on any CUDA-enabled Linux server (Ubuntu 22.04+).

---

## 🛠️ 1. Hardware & System Requirements
Before starting, ensure your environment meets these specifications. Failure to do so will result in `CUDA Out of Memory` or initialization crashes.

- **GPU**: NVIDIA with **minimum 24GB VRAM** (e.g., RTX 3090, 4090, A10, A100, etc.).
- **RAM**: Minimum 16GB System RAM.
- **Disk Space**: At least **60GB** (The VLM weights alone are ~15GB, and Docker/System overhead takes more).
- **OS**: Ubuntu 22.04 LTS (recommended) or 24.04.
- **Drivers**: NVIDIA Driver 535+ and CUDA 12.1+.

---

## 📥 2. Initial System Setup
Run these commands in order. We assume you are the `root` user.

```bash
# 1. Update system repositories
apt-get update && apt-get upgrade -y

# 2. Install essential system binaries for Python and CV
# libsm6 and libxext6 are CRITICAL for OpenCV to work in a headless environment
apt-get install -y git wget curl python3-pip python3-venv ffmpeg libsm6 libxext6 lsof

# 3. Verify GPU health
nvidia-smi
```

---

## 📂 3. Project Installation
We will organize everything inside `/root/road_inspector`.

```bash
# 1. Create directory and enter it
mkdir -p /root/road_inspector
cd /root/road_inspector

# 2. Clone/Copy your files into this directory. 
# Ensure the following files exist in /root/road_inspector:
# - main.py
# - config.py
# - prompt.txt
# - requirements.txt
```

### 🧬 Directory Tree (Verify this!)
Your folder structure **MUST** look like this for the code to run correctly:
```text
/root/road_inspector/
├── main.py
├── config.py
├── prompt.txt
├── requirements.txt
└── GUIDES/
    ├── STARTUP_GUIDE.md
    └── API_INTEGRATION_GUIDE.md
```

---

## 🐍 4. Python Environment
We recommend using a Virtual Environment to avoid library conflicts.

```bash
# 1. Create the environment
python3 -m venv venv

# 2. Activate the environment
source venv/bin/activate

# 3. Install core dependencies (This takes 5-10 minutes)
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 📦 5. Model Weights Preparation
The API uses three distinct models.

### A. VLM & YOLOv12 (Auto-Download)
These will download automatically on first run to `~/.cache/huggingface`. Ensure you have an internet connection.

### B. YOLOv8 (Manual Download)
You MUST ensure the local weights for the specialized RDD model are in the expected path defined in `config.py`.

```bash
# Create the specific directory for oracl4 weights
mkdir -p /root/oracl4_rdd/models/

# Download the weights manually
wget -O /root/oracl4_rdd/models/YOLOv8_Small_RDD.pt \
https://huggingface.co/oracl4/YOLOv8_Small_RDD/resolve/main/YOLOv8_Small_RDD.pt
```

---

## 🚀 6. Launching the Service

### Method A: Foreground (For Testing)
Use this to see real-time logs and errors.
```bash
python3 main.py
```

### Method B: Background (For Production)
Use this if you want the API to keep running after you close your SSH window.
```bash
nohup python3 main.py > server.log 2>&1 &
```
- **To check if it is running:** `ps aux | grep main.py`
- **To see live logs:** `tail -f server.log`
- **To stop it:** `kill $(lsof -t -i:17612)`

---

## 🌍 7. Public Access (Cloudflare Tunnel)
If you are on a remote server (Vast.ai) and want to call the API from your home laptop:

```bash
# 1. Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared-linux-amd64.deb

# 2. Start the tunnel in the background
nohup cloudflared tunnel --url http://127.0.0.1:17612 > cloudflare.log 2>&1 &

# 3. Get your Public URL
grep -o "https://.*\.trycloudflare\.com" cloudflare.log | head -n 1
```

---

## 📝 8. Configuration & Tuning
You can edit `config.py` to adjust performance:

- `VLM_GPU_UTIL`: Default `0.90`. Set to `0.80` if you get OOM (Out of Memory) errors.
- `YOLO_CONF_THRESH`: Default `0.15`. Lower this to `0.10` to detect more minor cracks.
- `API_KEY`: Change `"road-inspector-secret-key-2024"` to your own secret string for security.

---

## 🔍 9. Troubleshooting FAQ

**Q: I get "ModuleNotFoundError: No module named 'cv2'"**
**A:** Run `pip install opencv-python-headless`.

**Q: I get "CUDA Out of Memory" during startup.**
**A:** Another process is using the GPU. Run `fuser -v /dev/nvidia*` and kill any dangling processes. Then ensure `VLM_GPU_UTIL` in `config.py` is not too high.

**Q: The VLM just repeats the same word over and over.**
**A:** Check `prompt.txt`. Ensure you haven't removed the "CRITICAL: Do not repeat" instruction. Also ensure `repetition_penalty` in `main.py` is set to `1.2`.

**Q: I can't reach the API from my browser.**
**A:** Ensure you are using the `https://...trycloudflare.com` link and that you have added your `X-API-Key` to the headers.
