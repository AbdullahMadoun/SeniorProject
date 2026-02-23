from __future__ import annotations

import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool
from supabase import Client, create_client

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

_SUPABASE_CLIENT: Optional[Client] = None
_DB_POOL: Optional[ConnectionPool] = None
_SCHEMA_READY = False
_BUCKET_READY = False


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required env var: {name}")
    return value


def _extract_url(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("signedURL", "signedUrl", "publicURL", "publicUrl", "url"):
            value = payload.get(key)
            if value:
                break
        else:
            value = ""
        if value.startswith("/"):
            return f"{_require_env('SUPABASE_URL').rstrip('/')}{value}"
        return value
    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return _extract_url(data)
    return ""


def _bucket_name() -> str:
    return os.getenv("SUPABASE_BUCKET", "skylink-images")


def _bucket_is_public() -> bool:
    return _bool_env("SUPABASE_BUCKET_PUBLIC", True)


def _signed_url_ttl() -> int:
    return int(os.getenv("SUPABASE_SIGNED_URL_TTL", "3600"))


def get_supabase_client() -> Client:
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        supabase_url = _require_env("SUPABASE_URL")
        service_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
        _SUPABASE_CLIENT = create_client(supabase_url, service_key)
    return _SUPABASE_CLIENT


def get_db_pool() -> ConnectionPool:
    global _DB_POOL
    if _DB_POOL is None:
        conninfo = os.getenv("SUPABASE_DB_POOLER_URL") or os.getenv("SUPABASE_DB_URL")
        if not conninfo:
            raise ValueError("Set SUPABASE_DB_POOLER_URL (recommended) or SUPABASE_DB_URL.")

        min_size = int(os.getenv("SUPABASE_DB_POOL_MIN", "1"))
        max_size = int(os.getenv("SUPABASE_DB_POOL_MAX", "5"))

        # Supavisor transaction mode is incompatible with prepared statements.
        _DB_POOL = ConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            open=True,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )
    return _DB_POOL


def _ensure_bucket_exists() -> None:
    global _BUCKET_READY
    if _BUCKET_READY:
        return

    client = get_supabase_client()
    bucket = _bucket_name()
    existing_names = set()
    for item in client.storage.list_buckets():
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = getattr(item, "name", None)
        if name:
            existing_names.add(name)

    if bucket not in existing_names:
        client.storage.create_bucket(bucket, options={"public": _bucket_is_public()})
    _BUCKET_READY = True


def ensure_database_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    pool = get_db_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.detections (
                    id BIGSERIAL PRIMARY KEY,
                    image_name TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    image_url TEXT,
                    detection_count INTEGER NOT NULL,
                    max_confidence DOUBLE PRECISION NOT NULL,
                    severity TEXT NOT NULL,
                    gps_lat DOUBLE PRECISION,
                    gps_lon DOUBLE PRECISION,
                    localization_m DOUBLE PRECISION,
                    localization_target_met BOOLEAN,
                    estimated_accuracy DOUBLE PRECISION,
                    accuracy_target_met BOOLEAN,
                    processing_seconds DOUBLE PRECISION,
                    timestamp_utc TIMESTAMPTZ NOT NULL,
                    boxes JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detections_timestamp_utc ON public.detections (timestamp_utc DESC)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_detections_severity ON public.detections (severity)")

    _SCHEMA_READY = True


def resolve_image_url(storage_path: str) -> str:
    if not storage_path:
        return ""

    client = get_supabase_client()
    bucket = _bucket_name()
    if _bucket_is_public():
        return _extract_url(client.storage.from_(bucket).get_public_url(storage_path))
    signed = client.storage.from_(bucket).create_signed_url(storage_path, _signed_url_ttl())
    return _extract_url(signed)


def upload_to_supabase_storage(
    file_path: str | Path,
    process_started_at: Optional[float] = None,
    max_total_seconds: int = 300,
) -> Dict[str, str]:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Cannot upload missing file: {file_path}")

    upload_start = time.time()
    if process_started_at and (upload_start - process_started_at) > max_total_seconds:
        raise TimeoutError("Processing + upload already exceeded 5 minutes before upload.")

    _ensure_bucket_exists()
    client = get_supabase_client()
    bucket = _bucket_name()

    now = datetime.now(timezone.utc)
    storage_path = (
        f"detections/{now:%Y/%m/%d}/{file_path.stem}_{int(upload_start * 1000)}{file_path.suffix.lower()}"
    )
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    with file_path.open("rb") as file_obj:
        client.storage.from_(bucket).upload(
            path=storage_path,
            file=file_obj,
            file_options={"cache-control": "3600", "upsert": "true", "content-type": content_type},
        )

    image_url = resolve_image_url(storage_path)
    upload_seconds = time.time() - upload_start
    total_elapsed = time.time() - process_started_at if process_started_at else upload_seconds

    if total_elapsed > max_total_seconds:
        raise TimeoutError("Processing + upload exceeded the 5-minute requirement.")

    return {
        "status": "uploaded",
        "storage_path": storage_path,
        "image_url": image_url,
        "upload_seconds": f"{upload_seconds:.3f}",
        "total_elapsed_seconds": f"{total_elapsed:.3f}",
    }


def _insert_detection_row(
    detection: Dict[str, Any],
    upload: Dict[str, str],
    process_started_at: Optional[float],
    max_total_seconds: int,
) -> int:
    pool = get_db_pool()
    started = time.time()
    if process_started_at and (started - process_started_at) > max_total_seconds:
        raise TimeoutError("Processing + upload already exceeded 5 minutes before DB insert.")

    ts = detection.get("timestamp_utc", datetime.now(timezone.utc).isoformat())
    timestamp_utc = datetime.fromisoformat(str(ts))

    with pool.connection() as conn:
        with conn.transaction():
            cursor = conn.execute(
                """
                INSERT INTO public.detections (
                    image_name, storage_path, image_url, detection_count, max_confidence, severity,
                    gps_lat, gps_lon, localization_m, localization_target_met, estimated_accuracy,
                    accuracy_target_met, processing_seconds, timestamp_utc, boxes
                )
                VALUES (
                    %(image_name)s, %(storage_path)s, %(image_url)s, %(detection_count)s, %(max_confidence)s,
                    %(severity)s, %(gps_lat)s, %(gps_lon)s, %(localization_m)s, %(localization_target_met)s,
                    %(estimated_accuracy)s, %(accuracy_target_met)s, %(processing_seconds)s, %(timestamp_utc)s,
                    %(boxes)s
                )
                RETURNING id
                """,
                {
                    "image_name": detection.get("image_name"),
                    "storage_path": upload.get("storage_path"),
                    "image_url": upload.get("image_url"),
                    "detection_count": int(detection.get("detection_count", 0)),
                    "max_confidence": float(detection.get("max_confidence", 0.0)),
                    "severity": detection.get("severity", "Unknown"),
                    "gps_lat": detection.get("gps_lat"),
                    "gps_lon": detection.get("gps_lon"),
                    "localization_m": detection.get("localization_m"),
                    "localization_target_met": bool(detection.get("localization_target_met", False)),
                    "estimated_accuracy": float(detection.get("estimated_accuracy", 0.0)),
                    "accuracy_target_met": bool(detection.get("accuracy_target_met", False)),
                    "processing_seconds": float(detection.get("processing_seconds", 0.0)),
                    "timestamp_utc": timestamp_utc,
                    "boxes": Json(detection.get("boxes", [])),
                },
            )
            row = cursor.fetchone()

    if process_started_at and (time.time() - process_started_at) > max_total_seconds:
        raise TimeoutError("Processing + upload + DB insert exceeded the 5-minute requirement.")
    return int(row["id"]) if row else 0


def sync_detection_to_supabase(
    detection: Dict[str, Any],
    process_started_at: Optional[float] = None,
    max_total_seconds: int = 300,
) -> Dict[str, str]:
    ensure_database_schema()
    upload: Dict[str, str] = {}

    try:
        upload = upload_to_supabase_storage(
            file_path=detection["processed_path"],
            process_started_at=process_started_at,
            max_total_seconds=max_total_seconds,
        )
        row_id = _insert_detection_row(
            detection=detection,
            upload=upload,
            process_started_at=process_started_at,
            max_total_seconds=max_total_seconds,
        )
        upload["db_row_id"] = str(row_id)
        return upload
    except Exception:
        # Best-effort compensation: remove uploaded object if DB transaction failed.
        if upload.get("storage_path"):
            try:
                client = get_supabase_client()
                client.storage.from_(_bucket_name()).remove([upload["storage_path"]])
            except Exception:
                pass
        raise


def fetch_recent_detections(limit: int = 200) -> List[Dict[str, Any]]:
    ensure_database_schema()
    pool = get_db_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id, image_name, storage_path, image_url, detection_count, max_confidence, severity,
                gps_lat, gps_lon, localization_m, localization_target_met, estimated_accuracy,
                accuracy_target_met, processing_seconds, timestamp_utc, boxes, created_at
            FROM public.detections
            ORDER BY timestamp_utc DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()

    records: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if not item.get("image_url") and item.get("storage_path"):
            item["image_url"] = resolve_image_url(item["storage_path"])
        records.append(item)
    return records
