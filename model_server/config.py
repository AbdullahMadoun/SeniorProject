import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Settings
    API_KEY: str = os.getenv("API_KEY", "road-inspector-secret-key-2024")
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 17612))

    # YOLO Model Settings
    YOLO_MODEL_V8: str = "/root/oracl4_rdd/models/YOLOv8_Small_RDD.pt"
    YOLO_MODEL_V12: str = "rezzzq/yolo12s-road-damage-rdd2022"
    YOLO_CONF_THRESH: float = 0.12                  # Lowered to capture more subtle cracks
    YOLO_IOU_THRESH: float = 0.05                   # NMS threshold (lower = aggressively merge overlapping boxes)
    
    # Class Standardization Map (handles both YOLOv12 'D00' and YOLOv8 'Longitudinal Crack' outputs)
    YOLO_CLASSES: dict = {
        "D00": "Longitudinal Crack",
        "D10": "Transverse Crack",
        "D20": "Alligator Crack",
        "D40": "Pothole",
        "Repair": "Repaired Area",
        "Longitudinal Crack": "Longitudinal Crack",
        "Transverse Crack": "Transverse Crack",
        "Alligator Crack": "Alligator Crack",
        "Potholes": "Pothole",
    }

    # VLM Model Settings
    VLM_TYPE: str = "qwen"
    VLM_MODEL: str = os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
    
    # VLM_GPU_UTIL: GPU memory utilization (0.80 is safer for vLLM v1)
    VLM_GPU_UTIL: float = float(os.getenv("GPU_MEM_UTIL", "0.80"))

    # VLM_MAX_LEN: Max context length (increased to 16384 for complex reports)
    VLM_MAX_LEN: int = int(os.getenv("VLM_MAX_LEN", "16384"))
    VLM_MAX_OUT: int = int(os.getenv("MAX_OUTPUT_TOKENS", "16384"))
    VLM_TEMP: float = 0.01
    VLM_TOP_P: float = 0.2

config = Settings()
