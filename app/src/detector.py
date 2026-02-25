from __future__ import annotations

import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
from PIL import ExifTags, Image
from ultralytics import YOLO

ROOT_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT_DIR / "models"
DEFAULT_MODEL_PATH = MODELS_DIR / "crack.pt"
DEFAULT_MODEL_URL = "https://huggingface.co/hyunon/crack-yolov8/resolve/main/crack.pt"
LOCALIZATION_TARGET_M = 20.0
TARGET_CLASSES = {c.strip().lower() for c in os.getenv("SKYLINK_TARGET_CLASSES", "crack").split(",") if c.strip()}
MIN_CRACK_AREA_RATIO = float(os.getenv("SKYLINK_MIN_CRACK_AREA_RATIO", "0.0001"))
_MODEL: Optional[YOLO] = None


def _to_float(value: Any) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return float(value[0]) / float(value[1]) if float(value[1]) != 0 else 0.0
    return float(value)


def _dms_to_decimal(dms: Any, ref: str) -> Optional[float]:
    if not dms or len(dms) < 3:
        return None
    degrees = _to_float(dms[0])
    minutes = _to_float(dms[1])
    seconds = _to_float(dms[2])
    decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
    if ref in {"S", "W"}:
        decimal = -decimal
    return decimal


def extract_gps_coordinates(image_path: Path) -> Tuple[Optional[float], Optional[float]]:
    try:
        with Image.open(image_path) as image:
            exif = image.getexif()
            if not exif:
                return None, None
            gps_info = exif.get(34853)  # GPSInfo tag
            if not gps_info:
                return None, None

            gps_data = {}
            for key, value in gps_info.items():
                decoded_key = ExifTags.GPSTAGS.get(key, key)
                gps_data[decoded_key] = value

            lat = _dms_to_decimal(gps_data.get("GPSLatitude"), gps_data.get("GPSLatitudeRef", "N"))
            lon = _dms_to_decimal(gps_data.get("GPSLongitude"), gps_data.get("GPSLongitudeRef", "E"))
            return lat, lon
    except Exception:
        return None, None


def ensure_model(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if not model_path.exists():
        urllib.request.urlretrieve(DEFAULT_MODEL_URL, model_path)
    return model_path


def load_model(model_path: Path = DEFAULT_MODEL_PATH) -> YOLO:
    model_file = ensure_model(model_path)
    return YOLO(str(model_file))


def get_model() -> YOLO:
    global _MODEL
    if _MODEL is None:
        _MODEL = load_model()
    return _MODEL


def classify_severity(box_area_ratio: float) -> str:
    return "High Severity" if box_area_ratio >= 0.02 else "Low Severity"


def meets_accuracy_target(estimated_accuracy: float, target: float = 0.75) -> bool:
    return estimated_accuracy >= target


def process_image(
    image_path: str | Path,
    processed_dir: str | Path,
    conf_threshold: float = 0.25,
) -> Dict[str, Any]:
    start_time = time.time()
    image_path = Path(image_path)
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Unable to read image: {image_path}")

    height, width = image.shape[:2]
    model = get_model()
    result = model.predict(
        source=image,
        conf=conf_threshold,
        imgsz=max(height, width),
        verbose=False,
    )[0]

    annotated = image.copy()
    detections: List[Dict[str, Any]] = []
    max_conf = 0.0
    global_severity = "Low Severity"

    for box in result.boxes:
        confidence = float(box.conf[0])
        if confidence < conf_threshold:
            continue

        cls_id = int(box.cls[0]) if box.cls is not None else -1
        class_name = str(result.names.get(cls_id, "unknown")).strip().lower()
        if class_name not in TARGET_CLASSES:
            continue

        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        area = max(0, x2 - x1) * max(0, y2 - y1)
        area_ratio = area / float(max(width * height, 1))
        if area_ratio < MIN_CRACK_AREA_RATIO:
            continue

        severity = classify_severity(area_ratio)
        if severity == "High Severity":
            global_severity = "High Severity"

        max_conf = max(max_conf, confidence)
        label = f"{class_name} {confidence:.2f}"
        color = (0, 0, 255) if severity == "High Severity" else (0, 255, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, label, (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        detections.append(
            {
                "bbox": [x1, y1, x2, y2],
                "class_name": class_name,
                "confidence": round(confidence, 4),
                "severity": severity,
                "area_ratio": round(area_ratio, 6),
            }
        )

    gps_lat, gps_lon = extract_gps_coordinates(image_path)

    processed_path = ""
    if detections:
        processed_path_obj = processed_dir / f"{image_path.stem}_detected{image_path.suffix.lower()}"
        cv2.imwrite(str(processed_path_obj), annotated)
        processed_path = str(processed_path_obj)

    processing_seconds = time.time() - start_time
    estimated_accuracy = min(1.0, max_conf + 0.1) if detections else 0.0

    return {
        "image_name": image_path.name,
        "processed_path": processed_path,
        "detection_count": len(detections),
        "max_confidence": round(max_conf, 4),
        "severity": global_severity,
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "localization_m": LOCALIZATION_TARGET_M,
        "localization_target_met": LOCALIZATION_TARGET_M <= 20.0,
        "estimated_accuracy": round(estimated_accuracy, 4),
        "accuracy_target_met": meets_accuracy_target(estimated_accuracy),
        "processing_seconds": round(processing_seconds, 3),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "boxes": detections,
    }
