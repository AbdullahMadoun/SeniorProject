"""
Road Inspection VLM API Service
================================
FastAPI service using Qwen2.5-VL-7B-Instruct via vLLM to detect
pavement cracks/potholes and generate engineering reports.
"""

import base64
import io
import json
import os
import re
import secrets
import sys
import textwrap
from contextlib import asynccontextmanager
from typing import Any, Optional, Union, List

import cv2
import numpy as np
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from ultralytics import YOLO

from config import config

try:
    from qwen_vl_utils import process_vision_info
except ImportError:
    process_vision_info = None

try:
    from transformers import AutoProcessor
except ImportError:
    AutoProcessor = None

try:
    from vllm import LLM, SamplingParams
except ImportError:
    LLM = None
    SamplingParams = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "road-inspector-secret-key-2024")
MODEL_NAME = os.environ.get("MODEL_NAME", os.environ.get("VLM_MODEL", config.VLM_MODEL))
HOST = os.environ.get("HOST", config.HOST)
PORT = int(os.environ.get("PORT", str(config.PORT)))
GPU_MEM_UTIL = float(os.environ.get("GPU_MEM_UTIL", str(config.VLM_GPU_UTIL)))
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", str(config.VLM_MAX_LEN)))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", str(config.VLM_MAX_OUT)))
ENABLE_VLM = os.environ.get("ENABLE_VLM", str(config.ENABLE_VLM)).strip().lower() in {"1", "true", "yes", "on"}
ENABLE_YOLO_V8 = os.environ.get("ENABLE_YOLO_V8", str(config.ENABLE_YOLO_V8)).strip().lower() in {"1", "true", "yes", "on"}

# ---------------------------------------------------------------------------
# Prompt (loaded from /root/prompt.txt or embedded fallback)
# ---------------------------------------------------------------------------
PROMPT_FILE = os.environ.get("PROMPT_FILE", os.path.join(os.path.dirname(__file__), "prompt.txt"))


def load_prompt() -> str:
    """Load the VLM prompt from file."""
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r") as f:
            return f.read().strip()
    # Fallback prompt (should not normally be reached)
    return textwrap.dedent("""\
        You are an expert pavement distress inspector and asphalt repair engineer.
        Analyze the provided image of a roadway/pavement surface.
        Detect all visible cracks and potholes, providing bounding boxes and severity.
        Return ONLY valid JSON with the required schema.""")


SYSTEM_PROMPT = (
    "You are an expert pavement distress inspector and asphalt repair engineer. "
    "You analyze road images and identify cracks and potholes with precise detail. "
    "You must output ONLY strictly valid JSON, no extra text before or after the JSON object."
)

USER_PROMPT_TEMPLATE = load_prompt()

# ---------------------------------------------------------------------------
# Severity → color mapping for box drawing
# ---------------------------------------------------------------------------
SEVERITY_COLORS = {
    "high":     (0, 0, 255),     # Red (BGR)
    "moderate": (0, 140, 255),   # Orange
    "medium":   (0, 140, 255),   # Orange (alias)
    "low":      (0, 200, 0),     # Green
    "unknown":  (200, 200, 0),   # Cyan-ish
}

CATEGORY_COLORS = {
    "pothole": (0, 0, 255),      # Red
    "crack":   (255, 100, 0),    # Blue-ish
}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class LocationModel(BaseModel):
    lat: float
    lon: float


class AnalyzeRequest(BaseModel):
    image_b64: str
    location: Optional[Union[LocationModel, List[float]]] = None

    @field_validator("location", mode="before")
    @classmethod
    def validate_location(cls, v):
        if isinstance(v, list):
            if len(v) != 2:
                raise ValueError("Location list must have exactly 2 elements [lat, lon]")
            return LocationModel(lat=v[0], lon=v[1])
        return v


class AnalyzeResponse(BaseModel):
    image_b64_out: str
    report: dict


# ---------------------------------------------------------------------------
# VLM Engine + Processor (global singletons)
# ---------------------------------------------------------------------------
vlm_engine: Optional[LLM] = None
vlm_processor: Optional[AutoProcessor] = None


def init_vlm() -> tuple[LLM, AutoProcessor]:
    """Initialize the vLLM engine and processor with Qwen2.5-VL."""
    print(f"[INIT] Loading VLM model: {MODEL_NAME}")
    print(f"[INIT] GPU memory utilization: {GPU_MEM_UTIL}")
    print(f"[INIT] Max model length: {MAX_MODEL_LEN}")

    processor = AutoProcessor.from_pretrained(MODEL_NAME, trust_remote_code=True)
    print("[INIT] Processor loaded.")

    engine = LLM(
        model=MODEL_NAME,
        gpu_memory_utilization=GPU_MEM_UTIL,
        max_model_len=MAX_MODEL_LEN,
        trust_remote_code=True,
        dtype="auto",
        max_num_seqs=4,
    )
    print("[INIT] VLM model loaded successfully!")
    return engine, processor


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    yield
    # Cleanup
    global vlm_engine, vlm_processor, yolo_model_v8, yolo_model_v12
    vlm_engine = None
    vlm_processor = None
    yolo_model_v8 = None
    yolo_model_v12 = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Road Inspection VLM API",
    description="Analyze road images for cracks and potholes using Qwen2.5-VL",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS Middleware to allow requests from browsers on different domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API Key security
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Provide X-API-Key header.")
    if not secrets.compare_digest(api_key, API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key.")
    return api_key


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------
def decode_base64_image(b64_string: str) -> Image.Image:
    """Decode a base64 string to a PIL Image."""
    # Remove optional data URI prefix
    if "," in b64_string and b64_string.startswith("data:"):
        b64_string = b64_string.split(",", 1)[1]
    image_bytes = base64.b64decode(b64_string)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image


def encode_image_to_base64(image: np.ndarray, fmt: str = ".jpg") -> str:
    """Encode an OpenCV image (BGR) to base64 JPEG string."""
    success, buffer = cv2.imencode(fmt, image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not success:
        raise RuntimeError("Failed to encode image")
    return base64.b64encode(buffer).decode("utf-8")


def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
    """Convert PIL Image (RGB) to OpenCV format (BGR)."""
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# ML Models (YOLO & VLM)
# ---------------------------------------------------------------------------
yolo_model_v8: Optional[YOLO] = None
yolo_model_v12: Optional[YOLO] = None
vlm_engine: Optional[LLM] = None
vlm_processor: Optional[AutoProcessor] = None

def init_models():
    """Initialize YOLO models and vLLM engine."""
    global yolo_model_v8, yolo_model_v12, vlm_engine, vlm_processor

    if ENABLE_VLM:
        if AutoProcessor is None or LLM is None or SamplingParams is None or process_vision_info is None:
            raise RuntimeError("ENABLE_VLM=true but VLM dependencies are not installed on this host.")
        print(f"[INIT] Loading VLM model: {MODEL_NAME}")
        vlm_processor = AutoProcessor.from_pretrained(MODEL_NAME, trust_remote_code=True)
        vlm_engine = LLM(
            model=MODEL_NAME,
            gpu_memory_utilization=GPU_MEM_UTIL,
            max_model_len=MAX_MODEL_LEN,
            trust_remote_code=True,
            dtype="auto",
            max_num_seqs=4,
        )
    else:
        print("[INIT] ENABLE_VLM=false, skipping VLM load and running in YOLO-only mode.")
        vlm_processor = None
        vlm_engine = None
    
    if ENABLE_YOLO_V8:
        print(f"[INIT] Loading YOLOv8 model: {config.YOLO_MODEL_V8}")
        yolo_model_v8 = YOLO(config.YOLO_MODEL_V8)
    else:
        print("[INIT] ENABLE_YOLO_V8=false, skipping YOLOv8 load.")
        yolo_model_v8 = None

    print(f"[INIT] Loading YOLOv12 model: {config.YOLO_MODEL_V12}")
    try:
        from huggingface_hub import hf_hub_download
        if "rezzzq" in config.YOLO_MODEL_V12:
            path = hf_hub_download(repo_id=config.YOLO_MODEL_V12, filename="yolo12s_RDD2022_best.pt")
        else:
            path = hf_hub_download(repo_id=config.YOLO_MODEL_V12, filename="best.pt")
        yolo_model_v12 = YOLO(path)
    except Exception as e:
        print(f"[INIT] Falling back to standard YOLO load due to: {e}")
        yolo_model_v12 = YOLO(config.YOLO_MODEL_V12)

    print("[INIT] Models loaded successfully!")

# ---------------------------------------------------------------------------
# Inference Pipeline
# ---------------------------------------------------------------------------
def run_hybrid_inference(pil_image: Image.Image, lat: Optional[float] = None, lon: Optional[float] = None) -> tuple[Image.Image, dict, list]:
    """Run BOTH YOLO models for boxes -> NMS merge -> Draw -> Run VLM for report."""
    if not yolo_model_v8 and not yolo_model_v12:
        raise RuntimeError("No YOLO model is initialized")

    w, h = pil_image.size
    cv2_img = pil_to_cv2(pil_image)

    # 1. YOLO Detection
    print("[PIPELINE] Running YOLO detection...")
    res_v8 = None
    res_v12 = None
    if yolo_model_v8:
        print("[PIPELINE] Running YOLOv8 detection...")
        res_v8 = yolo_model_v8(cv2_img, conf=config.YOLO_CONF_THRESH, iou=config.YOLO_IOU_THRESH, verbose=False)[0]
    if yolo_model_v12:
        print("[PIPELINE] Running YOLOv12 detection...")
        res_v12 = yolo_model_v12(cv2_img, conf=config.YOLO_CONF_THRESH, iou=config.YOLO_IOU_THRESH, verbose=False)[0]
    
    all_boxes = []
    all_scores = []
    all_labels = []
    
    # Process YOLO boxes into normalized NMS format
    def extract_res(results):
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            
            if hasattr(results.names, 'get'):
                raw_label = results.names.get(cls_id, str(cls_id))
            else:
                raw_label = results.names[cls_id]
                 
            label = config.YOLO_CLASSES.get(raw_label, raw_label)
            all_boxes.append([x1, y1, x2 - x1, y2 - y1]) # NMS expects [x, y, w, h]
            all_scores.append(conf)
            all_labels.append(label)

    if res_v8 is not None:
        extract_res(res_v8)
    if res_v12 is not None:
        extract_res(res_v12)
    
    detections = []
    draw_items = []
    
    # Apply unified NMS
    if len(all_boxes) > 0:
        indices = cv2.dnn.NMSBoxes(all_boxes, all_scores, config.YOLO_CONF_THRESH, config.YOLO_IOU_THRESH)
        if len(indices) > 0:
            for idx_enum, i in enumerate(indices.flatten()):
                x, y, bw, bh = all_boxes[i]
                x1, y1, x2, y2 = x, y, x + bw, y + bh
                label = all_labels[i]
                box_id = f"D{idx_enum}"
                
                det = {
                    "id": box_id,
                    "label": label,
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "confidence": all_scores[i],
                    "severity": "unknown" 
                }
                detections.append(det)
                
                draw_items.append({
                    "id": box_id,
                    "label": label,
                    "severity": "unknown",
                    "category": "crack",
                    "location": {"approx_bbox_px": [x1, y1, x2, y2]}
                })

    # 2. Draw boxes for VLM (without severity)
    print(f"[PIPELINE] Drawing {len(detections)} YOLO boxes...")

    if ENABLE_VLM and vlm_engine and vlm_processor:
        temp_cv2 = draw_boxes_on_image(cv2_img, draw_items)
        temp_pil = Image.fromarray(cv2.cvtColor(temp_cv2, cv2.COLOR_BGR2RGB))

        # 3. VLM Reporting
        print("[PIPELINE] Running VLM for report generation...")
        
        box_infos = []
        for d in detections:
            x1, y1, x2, y2 = d['bbox_xyxy']
            w_px = max(1, x2 - x1)
            h_px = max(1, y2 - y1)
            area = w_px * h_px
            conf = round(d.get('confidence', 0.0) * 100, 1)
            
            info = f"- ID: {d['id']}, Type: {d['label']}, YOLO Confidence: {conf}%, Dimensions: {w_px}x{h_px} pixels (Area: {area}), Coords: [x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}]"
            box_infos.append(info)
            
        box_list_str = "\n".join(box_infos)
        if not box_list_str:
            box_list_str = "No defects detected by YOLO."
        
        gps_str = f"GPS location (lat, lon): {lat}, {lon}." if lat is not None and lon is not None else "GPS location: Not provided."
        user_prompt = USER_PROMPT_TEMPLATE + f"\n\n{gps_str}\nImage resolution: {w} x {h} pixels.\n\n### DETECTED BOUNDING BOXES (From YOLO):\n{box_list_str}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": temp_pil},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ]

        image_inputs, _ = process_vision_info(messages)
        text_prompt = vlm_processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        sampling_params = SamplingParams(
            temperature=config.VLM_TEMP,
            top_p=config.VLM_TOP_P,
            max_tokens=1500,
            repetition_penalty=1.2,
        )

        outputs = vlm_engine.generate(
            [{"prompt": text_prompt, "multi_modal_data": {"image": image_inputs}}],
            sampling_params=sampling_params,
        )
        raw_vlm_text = outputs[0].outputs[0].text

        try:
            report_json = extract_json_from_text(raw_vlm_text)
        except Exception as e:
            print(f"[PIPELINE] Failed to parse VLM JSON: {e}")
            report_json = {"report_markdown": raw_vlm_text, "severities": {}}

        severities = report_json.get("severities", {})
        for d in detections:
            d["severity"] = severities.get(d["id"], "unknown")
            
        for item in draw_items:
            item["severity"] = severities.get(item["id"], "unknown")
        report_markdown = report_json.get("report_markdown", "")
    else:
        print("[PIPELINE] ENABLE_VLM=false, producing YOLO-only report.")
        image_area = max(1, w * h)
        summary_lines = []
        for d, item in zip(detections, draw_items):
            x1, y1, x2, y2 = d["bbox_xyxy"]
            bbox_area = max(1, (x2 - x1) * (y2 - y1))
            ratio = bbox_area / image_area
            severity = "high" if ratio >= 0.08 else "low"
            d["severity"] = severity
            item["severity"] = severity
            summary_lines.append(
                f"- {d['id']}: {d['label']} at [{x1}, {y1}, {x2}, {y2}] "
                f"covering {ratio:.1%} of the image, severity={severity}"
            )

        if not summary_lines:
            summary_lines.append("- No defects detected by YOLO.")

        report_markdown = (
            "# YOLO-Only Inspection Report\n\n"
            "This run skipped the VLM and validated remote startup plus YOLO inference only.\n\n"
            f"Detected items: {len(detections)}\n\n"
            + "\n".join(summary_lines)
        )

    # 5. Draw FINAL boxes containing the severity label
    annotated_cv2 = draw_boxes_on_image(cv2_img, draw_items)
    annotated_pil = Image.fromarray(cv2.cvtColor(annotated_cv2, cv2.COLOR_BGR2RGB))

    return annotated_pil, {"report_markdown": report_markdown}, detections


# ---------------------------------------------------------------------------
# JSON parsing from VLM output
# ---------------------------------------------------------------------------
def extract_json_from_text(text: str) -> dict:
    """
    Robustly extract JSON from VLM output text.
    Handles markdown code fences, extra whitespace, etc.
    """
    # Try to find JSON in code fence
    code_fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if code_fence_match:
        json_str = code_fence_match.group(1).strip()
    else:
        # Try to find JSON object directly
        # Find the first { and the last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace : last_brace + 1]
        else:
            json_str = text.strip()

    # Clean up common issues
    # Remove trailing commas before ] or }
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse VLM JSON output: {e}")
        print(f"[ERROR] Raw text (first 2000 chars): {text[:2000]}")
        raise ValueError(f"VLM output is not valid JSON: {e}")


# ---------------------------------------------------------------------------
# Bounding box drawing
# ---------------------------------------------------------------------------
def draw_boxes_on_image(
    cv2_image: np.ndarray,
    distress_items: list[dict],
) -> np.ndarray:
    """
    Draw bounding boxes on the image based on distress items.
    Handles absolute pixel bboxes from the VLM output.
    """
    h, w = cv2_image.shape[:2]
    annotated = cv2_image.copy()

    for item in distress_items:
        item_id = item.get("id", "?")
        label = item.get("label", "unknown")
        severity = item.get("severity", "unknown")
        category = item.get("category", "crack")

        # Get bounding box — uses absolute pixel coords from prompt
        location = item.get("location", {})
        bbox_px = location.get("approx_bbox_px", None)

        if bbox_px is None or len(bbox_px) != 4:
            continue

        # Clip pixel coordinates to image bounds
        x1 = int(max(0, min(bbox_px[0], w - 1)))
        y1 = int(max(0, min(bbox_px[1], h - 1)))
        x2 = int(max(0, min(bbox_px[2], w - 1)))
        y2 = int(max(0, min(bbox_px[3], h - 1)))

        # Ensure valid box
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        # Choose color based on severity
        color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["unknown"])

        # Draw rectangle (Make thickness significantly larger, minimum 4 pixels)
        thickness = max(4, min(10, w // 200))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

        # Draw label background + text
        label_text = f"{item_id}: {label} ({severity})"
        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = max(1.0, min(2.5, w / 800))  # Larger base scale for readability
        text_thickness = max(2, thickness - 1)
        (tw, th), baseline = cv2.getTextSize(label_text, font, font_scale, text_thickness)

        # Label position (above the box, or inside if at top edge)
        label_y = y1 - 12 if y1 - th - 15 > 0 else y1 + th + 12
        label_x = x1

        # Background rectangle for text
        cv2.rectangle(
            annotated,
            (label_x, label_y - th - 4),
            (label_x + tw + 4, label_y + 4),
            color,
            -1,
        )
        # Text
        cv2.putText(
            annotated,
            label_text,
            (label_x + 2, label_y),
            font,
            font_scale,
            (255, 255, 255),
            text_thickness,
            cv2.LINE_AA,
        )

    return annotated


# ---------------------------------------------------------------------------
# Build API response report matching the contract
# ---------------------------------------------------------------------------
def build_response_report(vlm_output: dict) -> dict:
    """
    Transform the VLM output into the API response report format.
    Maps the detailed prompt schema to the simpler API contract while
    preserving all the rich detail.
    """
    # Build boxes in the simplified API format
    boxes = []
    for item in vlm_output.get("distress_items", []):
        location = item.get("location", {})
        bbox_px = location.get("approx_bbox_px", [0, 0, 0, 0])

        # Map category
        category = item.get("category", "crack")
        if "pothole" in item.get("label", ""):
            category = "pothole"
        elif category != "pothole":
            category = "crack"

        box_entry = {
            "id": item.get("id", "?"),
            "class": category,
            "label": item.get("label", "unknown"),
            "bbox_xyxy": bbox_px,
            "severity": item.get("severity", "unknown"),
            "evidence": item.get("evidence", ""),
            "confidence": item.get("confidence", 0.0),
        }
        boxes.append(box_entry)

    # Build recommended actions from all repair items
    recommended_actions = []
    for item in vlm_output.get("distress_items", []):
        for repair in item.get("recommended_repairs", []):
            action = f"[{repair.get('timeframe', 'short_term')}] {repair.get('action', '')}"
            if action not in recommended_actions:
                recommended_actions.append(action)

    # Build summary from the markdown report or distress checklist
    report_md = vlm_output.get("report_markdown", "")

    # Construct a summary line
    n_items = len(vlm_output.get("distress_items", []))
    surface = vlm_output.get("pavement_surface_type", "unknown")
    high_sev = sum(1 for i in vlm_output.get("distress_items", []) if i.get("severity") == "high")
    summary_parts = [f"{n_items} distress item(s) detected on {surface} surface."]
    if high_sev:
        summary_parts.append(f"{high_sev} high-severity issue(s) requiring immediate attention.")

    report = {
        "summary": " ".join(summary_parts),
        "boxes": boxes,
        "recommended_actions": recommended_actions,
        "pavement_surface_type": surface,
        "distress_checklist": vlm_output.get("distress_checklist", {}),
        "report_markdown": report_md,
    }
    return report


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------
class AnalyzeResponse(BaseModel):
    report: dict = Field(..., description="Structured report and detections")


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, api_key: str = Security(verify_api_key)):
    """
    1) Decode image.
    2) Run Hybrid Pipeline (YOLO + VLM).
    3) Return detections and report.
    """
    # 1) Decode
    try:
        image_data = base64.b64decode(req.image_b64)
        pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image: {e}")

    w, h = pil_image.size
    lat = req.location.lat if req.location else None
    lon = req.location.lon if req.location else None
    
    print(f"[ANALYZE] Received image: {w}x{h}, location: ({lat}, {lon})")

    # 2) Run Hybrid Pipeline (YOLO + VLM)
    print("[ANALYZE] Running hybrid YOLO + VLM inference...")
    try:
        annotated_pil, report_dict, detections = run_hybrid_inference(
            pil_image, lat, lon
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference pipeline failed: {e}")

    # 3) Merge response
    boxes = []
    for d in detections:
        category = "pothole" if "pothole" in d["label"].lower() else "crack"
        boxes.append({
            "id": d["id"],
            "class": category,
            "label": d["label"],
            "bbox_xyxy": d["bbox_xyxy"],
            "severity": d["severity"],
        })

    n_boxes = len(boxes)
    high_sev = sum(1 for b in boxes if b.get("severity") == "high")
    summary_parts = [f"{n_boxes} defect(s) detected."]
    if high_sev:
        summary_parts.append(f"{high_sev} high-severity issue(s) requiring immediate attention.")

    report = {
        "summary": " ".join(summary_parts),
        "boxes": boxes,
        "report_markdown": report_dict.get("report_markdown", ""),
    }

    print(f"[ANALYZE] Done: {n_boxes} boxes")
    
    # 4) Explicit Memory Management
    # The models themselves stay permanently loaded in VRAM (vLM + YOLO).
    # However, PyTorch caches intermediate tensors during the forward pass. 
    # Calling python GC and emptying the CUDA cache prevents VRAM fragmentation over thousands of requests.
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        
    return AnalyzeResponse(report=report)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "vlm_loaded": vlm_engine is not None,
        "enable_vlm": ENABLE_VLM,
        "enable_yolo_v8": ENABLE_YOLO_V8,
        "yolo_v8_loaded": yolo_model_v8 is not None,
        "yolo_v12_loaded": yolo_model_v12 is not None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[START] Road Inspection VLM API")
    print(f"[START] Model: {MODEL_NAME}")
    print(f"[START] API Key: {API_KEY[:8]}...")
    print(f"[START] Listening on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
