# Road Inspector: Hybrid YOLO + VLM Pavement Analysis

An industrial-grade road inspection API that combines the localized speed of **Dual YOLO** models with the deep engineering analysis of **Qwen2.5-VL-7B**.

## 🌟 Key Features
- **Dual YOLO Core**: Runs YOLOv8 and YOLOv12 in parallel to ensure no defect is missed, then merges overlapping boxes using a custom Non-Maximum Suppression (NMS) layer.
- **Vision-Language Analysis**: Detected defects are passed to the 7B-parameter Qwen VLM for high-level engineering reporting.
- **Hazard-Centric Severity**: Uses a strictly defined severity logic that prioritizes **driving danger** over mere visual aesthetics.
- **VRAM Optimized**: Employs manual CUDA cache clearing and garbage collection to prevent fragmentation during long-term server operation on a single GPU.
- **Cloudflare Integrated**: Includes a quick-tunnel mechanism for exposing the API to the public internet with HTTPS without needing ngrok or complex firewall rules.

---

## 🏗️ Repository Structure
- `main.py`: The FastAPI server containing the inference pipeline.
- `config.py`: Central settings for model paths, confidence thresholds, and class mapping.
- `prompt.txt`: The engineer-refined system prompt that guides the VLM's behavior.
- `requirements.txt`: Comprehensive dependency list.
- `evaluate_hybrid_batch.py`: Batch evaluation script for testing on local image sets.
- `GUIDES/`:
    - `STARTUP_GUIDE.md`: **Boringly detailed** instructions for setting up from a blank OS.
    - `API_INTEGRATION_GUIDE.md`: For developers wanting to query this server.
    - `SSH_FORWARDING_GUIDES.md`: For secure local access via SSH tunnels.

---

## ⚡ Quick Start (Ready-to-Run)
If the environment is already configured:
```bash
cd road_inspector
python3 main.py
```
The server will start on `0.0.0.0:17612`.

---

## 🛠️ Installation
For a full guide on setting this up on a fresh Ubuntu instance with CUDA, see [STARTUP_GUIDE.md](./STARTUP_GUIDE.md).

1. **Clone and Install**:
```bash
git clone <your-repo-url>
cd road_inspector
pip install -r requirements.txt
```

2. **Run**:
```bash
python3 main.py
```

---

## 🔌 API Summary
- **Endpoint**: `POST /analyze`
- **Method**: `application/json`
- **Auth**: `X-API-Key: road-inspector-secret-key-2024`

**Request Example**:
```json
{
  "image_b64": "...",
  "location": {"lat": 34.0, "lon": -118.0}
}
```

**Response Example**:
```json
{
  "report": {
    "summary": "3 defect(s) detected. 1 high-severity issue(s).",
    "boxes": [...],
    "report_markdown": "# Pavement Distress Repair Report..."
  }
}
```

---

## 👨‍💻 Author & Acknowledgements
Built for industrial road-user danger assessment. Leveraging YOLOv8, YOLOv12, and the Qwen2.5-VL series.
