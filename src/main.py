from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List

from cloud_sync import ensure_database_schema, sync_detection_to_supabase
from detector import process_image
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
CSV_OUTPUT = PROCESSED_DIR / "detections.csv"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
load_dotenv(ROOT_DIR / ".env")


def list_images(raw_dir: Path) -> Iterable[Path]:
    for path in sorted(raw_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def calculate_drag_force(rho: float, c_d: float, area: float, velocity: float) -> float:
    return 0.5 * rho * c_d * area * (velocity**2)


def thrust_to_weight_ratio(thrust: float, weight: float) -> float:
    return thrust / weight if weight else 0.0


def write_results_csv(rows: List[Dict[str, object]], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "image_name",
        "processed_path",
        "detection_count",
        "max_confidence",
        "severity",
        "gps_lat",
        "gps_lon",
        "localization_m",
        "localization_target_met",
        "estimated_accuracy",
        "accuracy_target_met",
        "processing_seconds",
        "timestamp_utc",
        "supabase_status",
        "supabase_url",
        "storage_path",
        "db_row_id",
        "upload_seconds",
        "total_elapsed_seconds",
        "boxes",
    ]
    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row["boxes"] = json.dumps(row.get("boxes", []), ensure_ascii=True)
            writer.writerow(row)


def run_pipeline(raw_dir: Path, processed_dir: Path, conf_threshold: float, do_sync: bool) -> Path:
    start_time = time.time()
    rows: List[Dict[str, object]] = []
    if do_sync:
        ensure_database_schema()

    for image_path in list_images(raw_dir):
        result = process_image(image_path=image_path, processed_dir=processed_dir, conf_threshold=conf_threshold)
        if result["detection_count"] == 0:
            continue

        result["supabase_status"] = "skipped"
        result["supabase_url"] = ""
        result["storage_path"] = ""
        result["db_row_id"] = ""
        result["upload_seconds"] = ""
        result["total_elapsed_seconds"] = ""

        if do_sync and result["processed_path"]:
            try:
                sync_result = sync_detection_to_supabase(
                    detection=result,
                    process_started_at=start_time,
                    max_total_seconds=300,
                )
                result["supabase_status"] = sync_result.get("status", "uploaded")
                result["supabase_url"] = sync_result.get("image_url", "")
                result["storage_path"] = sync_result.get("storage_path", "")
                result["db_row_id"] = sync_result.get("db_row_id", "")
                result["upload_seconds"] = sync_result.get("upload_seconds", "")
                result["total_elapsed_seconds"] = sync_result.get("total_elapsed_seconds", "")
            except Exception as exc:
                result["supabase_status"] = f"error: {exc}"

        rows.append(result)

    write_results_csv(rows, CSV_OUTPUT)

    elapsed = time.time() - start_time
    print(f"Processed images with detections: {len(rows)}")
    print(f"Results CSV: {CSV_OUTPUT}")
    print(f"Total elapsed time: {elapsed:.2f}s")
    if elapsed > 300:
        print("WARNING: Processing + upload exceeded the 5-minute requirement.")

    # Optional technical grounding output.
    drag_force = calculate_drag_force(rho=1.225, c_d=1.1, area=0.04, velocity=7.0)
    tw_ratio = thrust_to_weight_ratio(thrust=20.0, weight=9.0)
    print(f"Drag force estimate at 7 m/s: {drag_force:.3f} N")
    print(f"Thrust-to-weight ratio: {tw_ratio:.3f} (target >= 2.0)")
    return CSV_OUTPUT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkyLink MVP detection pipeline")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR, help="Path to raw drone images")
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR, help="Path for processed images")
    parser.add_argument("--conf-threshold", type=float, default=0.25, help="YOLO confidence threshold")
    parser.add_argument("--sync", action="store_true", help="Sync processed images + metadata to Supabase")
    parser.add_argument("--upload", action="store_true", help="Alias for --sync")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        run_pipeline(
            raw_dir=args.raw_dir,
            processed_dir=args.processed_dir,
            conf_threshold=args.conf_threshold,
            do_sync=(args.sync or args.upload),
        )
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
