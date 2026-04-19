"""
upload_run.py — SkyLink companion upload script for R14 Gate 2 / IS5.

Purpose:
    Uploads one video_logger session's artifacts and metadata to Supabase.
    Inserts (or upserts) a row into the skylink_runs table and uploads 4
    artifact files to the skylink_runs storage bucket. Designed to run on
    the Pi companion after video_logger exits.

IS5 reference:
    End-to-end latency from last telemetry frame (ended_at = max frame_ts_unix)
    to Supabase row visibility must be <=300s. The skylink_runs table's
    upload_latency_seconds generated column measures this automatically.

Credentials:
    Reads SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and optionally
    SUPABASE_BUCKET from os.environ. Does NOT load env files itself.
    On the Pi, source credentials before invoking:
        set -a; source ~/.skylink_env; set +a
        .venv-pi/bin/python upload_run.py <output-dir>

Usage:
    upload_run.py <output-dir> [--run-id RUN_ID] [--mission-id UUID]
                               [--dry-run] [--verbose]

    Example:
        set -a; source ~/.skylink_env; set +a
        ~/SeniorProject/autonomy/companion/.venv-pi/bin/python \\
            ~/SeniorProject/autonomy/companion/upload_run.py \\
            ~/skylink_output/run_20260419_201241 \\
            --mission-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \\
            --verbose

Exit codes:
    0 — success
    1 — missing env vars or CLI argument error
    2 — MissingArtifactError (required artifact file absent)
    3 — TelemetryParseError or SummaryParseError (malformed JSONL or summary)
    4 — ArtifactUploadError (storage upload failure)
    5 — RowUpsertError (database upsert failure)
"""

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUCKET_NAME = "skylink_runs"
TABLE_NAME = "skylink_runs"  # Same string by convention; bucket mirrors table name.

ARTIFACTS: dict[str, str] = {
    "jsonl":   "telemetry.jsonl",
    "csv":     "telemetry_log.csv",
    "summary": "summary.json",
    "frame":   "latest_frame.jpg",
}

# Maps ARTIFACTS keys to skylink_runs table columns.
ARTIFACT_COLUMN_MAP: dict[str, str] = {
    "jsonl":   "artifact_jsonl_path",
    "csv":     "artifact_csv_path",
    "summary": "artifact_summary_path",
    "frame":   "artifact_frame_path",
}

# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------

class SummaryFields(TypedDict):
    processed_frames: int
    telemetry_updates: int
    telemetry_errors_count: int
    used_mock_mavlink: bool
    used_mock_camera: bool


class SkylinkRunRow(TypedDict, total=False):
    run_id: str
    started_at: str            # ISO8601 UTC
    ended_at: str              # ISO8601 UTC
    source_host: str
    frame_count: int
    telemetry_updates: int
    telemetry_errors_count: int
    used_mock_mavlink: bool
    used_mock_camera: bool
    artifact_jsonl_path: str
    artifact_csv_path: str
    artifact_summary_path: str
    artifact_frame_path: str
    mission_id: str            # UUID string or absent

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UploadRunError(Exception):
    """Base class for all upload_run errors."""
    pass

class MissingArtifactError(UploadRunError):
    """One or more required artifact files are absent from the output directory."""
    pass

class TelemetryParseError(UploadRunError):
    """JSONL telemetry file is malformed, empty, or missing required fields."""
    pass

class SummaryParseError(UploadRunError):
    """summary.json is missing, unreadable, or lacks required fields."""
    pass

class ArtifactUploadError(UploadRunError):
    """A storage upload to Supabase failed; no further artifacts were attempted.

    Attributes:
        artifact_key: Key from ARTIFACTS identifying which upload failed.
        cause: Underlying exception, if any.
    """
    def __init__(self, artifact_key: str, message: str,
                 cause: Exception | None = None):
        super().__init__(f"upload failed for '{artifact_key}': {message}")
        self.artifact_key = artifact_key
        self.cause = cause

class RowUpsertError(UploadRunError):
    """The skylink_runs table upsert failed."""
    pass

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def validate_output_dir(path: Path) -> dict[str, Path]:
    """Verify that all 4 required artifact files exist under path.

    Args:
        path: Absolute or relative path to the video_logger output directory.

    Returns:
        Mapping of artifact key (e.g. "jsonl", "csv") to absolute Path for
        each file in ARTIFACTS.

    Raises:
        MissingArtifactError: If path is not a directory or any required
            artifact file is absent.
    """
    raise NotImplementedError("skeleton")


def parse_telemetry(jsonl_path: Path) -> tuple[float, float, int]:
    """Parse the telemetry JSONL file and extract timing and frame statistics.

    Args:
        jsonl_path: Absolute path to the telemetry.jsonl artifact.

    Returns:
        Tuple of (min_frame_ts_unix, max_frame_ts_unix, frame_count) where
        timestamps are Unix epoch floats and frame_count is the number of
        valid lines parsed.

    Raises:
        TelemetryParseError: If the file is empty, any line is not valid JSON,
            or any line is missing the frame_ts_unix field.
    """
    raise NotImplementedError("skeleton")


def parse_summary(summary_path: Path) -> SummaryFields:
    """Parse summary.json and validate required fields are present.

    Args:
        summary_path: Absolute path to the summary.json artifact.

    Returns:
        SummaryFields TypedDict containing: processed_frames,
        telemetry_updates, telemetry_errors_count, used_mock_mavlink,
        used_mock_camera.

    Raises:
        SummaryParseError: If the file is missing, not valid JSON, or any
            required field is absent.
    """
    raise NotImplementedError("skeleton")


def compute_run_id(hostname: str, min_ts: float) -> str:
    """Derive the human-readable run identifier from hostname and session start time.

    Args:
        hostname: Machine hostname (e.g. from socket.gethostname()).
        min_ts: Unix epoch float representing the earliest frame timestamp
            (i.e. session start), used to derive the UTC date/time suffix.

    Returns:
        String of the form "run_{hostname}_{YYYYMMDD}_{HHMMSS}" in UTC.
    """
    raise NotImplementedError("skeleton")


def upload_artifacts(
    client: Client,
    run_id: str,
    paths: dict[str, Path],
    verbose: bool = False,
) -> dict[str, str]:
    """Upload all 4 artifact files to BUCKET_NAME/{run_id}/ in Supabase Storage.

    Fails fast: stops at the first upload failure without attempting remaining
    artifacts, so the caller can decide whether to retry.

    Args:
        client: Authenticated Supabase client (service role).
        run_id: Run identifier used as the storage path prefix.
        paths: Mapping of artifact key -> absolute local Path, as returned
            by validate_output_dir().
        verbose: If True, print per-artifact progress lines to stderr.

    Returns:
        Mapping of artifact key -> bucket object path (e.g.
        "run_pi_20260419_201241/telemetry.jsonl") for each uploaded file.

    Raises:
        ArtifactUploadError: On the first upload failure. artifact_key
            identifies which artifact failed; cause holds the underlying
            exception.
    """
    raise NotImplementedError("skeleton")


def upsert_run_row(client: Client, row: SkylinkRunRow) -> None:
    """Upsert a skylink_runs row, refreshing uploaded_at and artifact paths on conflict.

    On conflict on run_id, updates uploaded_at=now() and all four
    artifact_*_path columns so re-uploads reflect the latest storage paths.

    Args:
        client: Authenticated Supabase client (service role).
        row: SkylinkRunRow mapping skylink_runs column names to values. Must
            include at minimum: run_id, started_at, ended_at, source_host,
            frame_count, telemetry_updates, telemetry_errors_count,
            used_mock_mavlink, used_mock_camera, and the four
            artifact_*_path values.

    Returns:
        None

    Raises:
        RowUpsertError: If the Supabase PostgREST call returns an error
            or raises an exception.
    """
    raise NotImplementedError("skeleton")


def main() -> int:
    """Parse CLI args, load env, orchestrate validation, upload, and upsert.

    Exit codes:
        0 — success; prints SUCCESS line to stdout
        1 — missing env vars or CLI argument error
        2 — MissingArtifactError
        3 — TelemetryParseError or SummaryParseError
        4 — ArtifactUploadError
        5 — RowUpsertError

    Stdout contract on success (last line):
        SUCCESS: run_id=<id> uploaded_at=<ISO8601 Z> latency_s=<float>
    """
    parser = argparse.ArgumentParser(
        description="Upload a video_logger session to Supabase (R14 IS5).",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to video_logger output directory containing the 4 artifacts.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Override computed run_id (for re-upload / idempotency replay).",
    )
    parser.add_argument(
        "--mission-id",
        type=str,
        default=None,
        help="UUID FK to missions.id; default None (NULL in DB).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print computed payload, do not upload or upsert.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-artifact progress to stderr.",
    )
    args = parser.parse_args()
    raise NotImplementedError("skeleton — implementation pending")


if __name__ == "__main__":
    sys.exit(main())
