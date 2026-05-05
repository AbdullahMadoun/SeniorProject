import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list[str]:
    raw = str(os.getenv(name, default) or "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


ROOT_DIR = Path(__file__).resolve().parents[1]
TRAINING_PILOT_DIR = ROOT_DIR / "training_pilot"


class Settings(BaseSettings):
    # API Settings
    API_KEY: str = os.getenv("API_KEY", "road-inspector-secret-key-2024")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 17612))

    # Detector / ensemble settings
    DETECTOR_MODE: str = os.getenv("DETECTOR_MODE", "ensemble").strip().lower()
    ENSEMBLE_ENABLED: bool = _env_flag("ENSEMBLE_ENABLED", True)
    ENSEMBLE_MEMBERS: list[str] = _env_csv(
        "ENSEMBLE_MEMBERS",
        "rezzzq_yolo12s_rdd2022,ozair_yolov8_rdd2022,oracl4_yolov8_rdd2022",
    )
    ENSEMBLE_MODE: str = os.getenv("ENSEMBLE_MODE", "msflip").strip().lower()
    ENSEMBLE_WEIGHT_MODE: str = os.getenv("ENSEMBLE_WEIGHT_MODE", "equal").strip().lower()
    ENSEMBLE_WBF_IOU: float = float(os.getenv("ENSEMBLE_WBF_IOU", "0.30"))
    ENSEMBLE_WBF_SKIP: float = float(os.getenv("ENSEMBLE_WBF_SKIP", "0.05"))
    ENSEMBLE_FINAL_THRESHOLD: float = float(os.getenv("ENSEMBLE_FINAL_THRESHOLD", "0.20"))
    ENSEMBLE_MIN_SUPPORT: int = int(os.getenv("ENSEMBLE_MIN_SUPPORT", "2"))
    ENSEMBLE_BASE_CONF: float = float(os.getenv("ENSEMBLE_BASE_CONF", "0.001"))
    ENSEMBLE_BASE_IOU: float = float(os.getenv("ENSEMBLE_BASE_IOU", "0.90"))
    ENSEMBLE_MAX_DET: int = int(os.getenv("ENSEMBLE_MAX_DET", "1200"))
    ENSEMBLE_TTA_WBF_IOU: float = float(os.getenv("ENSEMBLE_TTA_WBF_IOU", "0.35"))
    ENSEMBLE_TTA_WBF_SKIP: float = float(os.getenv("ENSEMBLE_TTA_WBF_SKIP", "0.00"))
    ENSEMBLE_SUPPORT_IOU: float = float(os.getenv("ENSEMBLE_SUPPORT_IOU", "0.50"))
    ENSEMBLE_MODEL_REZZZQ: str = os.getenv(
        "ENSEMBLE_MODEL_REZZZQ",
        str(TRAINING_PILOT_DIR / "weights" / "rdd_trained_local" / "yolo12s_rezzzq_v5align" / "best.pt"),
    )
    ENSEMBLE_MODEL_OZAIR: str = os.getenv(
        "ENSEMBLE_MODEL_OZAIR",
        str(TRAINING_PILOT_DIR / "weights" / "rdd_trained_local" / "ozair_yolov8_custom" / "best.pt"),
    )
    ENSEMBLE_MODEL_ORACL4: str = os.getenv(
        "ENSEMBLE_MODEL_ORACL4",
        str(TRAINING_PILOT_DIR / "weights" / "rdd_trained_local" / "oracl4_yolov8_custom" / "best.pt"),
    )
    ENSEMBLE_MODEL_OBC: str = os.getenv(
        "ENSEMBLE_MODEL_OBC",
        "",
    )
    ENSEMBLE_CALIBRATION_MANIFEST: str = os.getenv(
        "ENSEMBLE_CALIBRATION_MANIFEST",
        "",
    )
    ENSEMBLE_SELECTION_SUMMARY: str = os.getenv(
        "ENSEMBLE_SELECTION_SUMMARY",
        "",
    )
    ENSEMBLE_SELECTION_KEY: str = os.getenv("ENSEMBLE_SELECTION_KEY", "best_ensemble_val").strip()
    ENSEMBLE_ALIAS_WEIGHTS: str = os.getenv("ENSEMBLE_ALIAS_WEIGHTS", "").strip()

    # Legacy single-model compatibility
    ENABLE_YOLO_V8: bool = _env_flag("ENABLE_YOLO_V8", _env_flag("ENABLE_VLM", True))
    YOLO_MODEL_V8: str = os.getenv("YOLO_MODEL_V8", "/root/oracl4_rdd/models/YOLOv8_Small_RDD.pt")
    YOLO_MODEL_V12: str = os.getenv("YOLO_MODEL_V12", "rezzzq/yolo12s-road-damage-rdd2022")
    YOLO_CONF_THRESH: float = float(os.getenv("YOLO_CONF_THRESH", "0.12"))
    YOLO_IOU_THRESH: float = float(os.getenv("YOLO_IOU_THRESH", "0.05"))

    # Class standardization map
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
        "damage": "Damage",
        "Damage": "Damage",
    }

    # VLM settings
    ENABLE_VLM: bool = _env_flag("ENABLE_VLM", True)
    VLM_TYPE: str = "qwen"
    VLM_BACKEND: str = os.getenv("VLM_BACKEND", "local").strip().lower()
    VLM_MODEL: str = os.getenv("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
    VLM_GPU_UTIL: float = float(os.getenv("GPU_MEM_UTIL", "0.80"))
    VLM_MAX_LEN: int = int(os.getenv("VLM_MAX_LEN", "16384"))
    VLM_MAX_OUT: int = int(os.getenv("MAX_OUTPUT_TOKENS", "16384"))
    VLM_TEMP: float = 0.01
    VLM_TOP_P: float = 0.2
    VLM_API_URL: str = os.getenv("VLM_API_URL", "").strip()
    VLM_API_KEY: str = os.getenv("VLM_API_KEY", "").strip()
    VLM_API_AUTH_SCHEME: str = os.getenv("VLM_API_AUTH_SCHEME", "x-api-key").strip().lower()
    VLM_API_TYPE: str = os.getenv("VLM_API_TYPE", "proprietary").strip().lower()
    VLM_API_TIMEOUT: float = float(os.getenv("VLM_API_TIMEOUT", "180"))
    VLM_API_MODEL_OPTIONS: list[str] = _env_csv(
        "VLM_API_MODEL_OPTIONS",
        "qwen/qwen2.5-vl-72b-instruct,google/gemini-2.5-flash,openai/gpt-4o-mini,anthropic/claude-3.5-sonnet",
    )



config = Settings()
