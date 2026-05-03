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
    Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from os.environ.
    Does NOT load env files itself. The storage bucket is the hardcoded
    constant BUCKET_NAME ("skylink_runs") below; it is not configurable
    via environment.
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
from storage3.exceptions import StorageApiError
from postgrest.exceptions import APIError

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

# MIME types per artifact for Supabase Storage uploads.
# Symmetric with ARTIFACTS / ARTIFACT_COLUMN_MAP — if you add an
# artifact, add it here too.
_CONTENT_TYPES: dict[str, str] = {
    "jsonl":   "application/json",
    "csv":     "text/csv",
    "summary": "application/json",
    "frame":   "image/jpeg",
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


class UpsertResult(TypedDict):
    """Return value of upsert_run_row — the fields main() needs
    for the IS5 SUCCESS stdout contract.
    """
    uploaded_at: str              # ISO 8601 from PostgREST
    upload_latency_seconds: float # generated column; IS5 metric

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
    resolved = path.resolve()
    if not resolved.is_dir():
        raise MissingArtifactError(
            f"output directory not found or not a directory: {resolved}"
        )
    # Report all missing files at once — do not fail fast on the first,
    # so users see the full picture.
    missing = [
        filename
        for filename in ARTIFACTS.values()
        if not (resolved / filename).is_file()
    ]
    if missing:
        raise MissingArtifactError(
            f"missing artifacts in {resolved}: {', '.join(missing)}"
        )
    return {key: resolved / filename for key, filename in ARTIFACTS.items()}


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
    min_ts: float | None = None
    max_ts: float | None = None
    count = 0

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            stripped = raw_line.strip()
            if not stripped:
                # Blank or whitespace-only lines are tolerated (trailing
                # newlines, mid-file blanks). They do not count toward
                # frame_count and do not raise.
                continue

            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TelemetryParseError(
                    f"{jsonl_path}:line {line_num}: invalid JSON ({exc.msg})"
                ) from exc

            ts = entry.get("frame_ts_unix") if isinstance(entry, dict) else None
            # Reject booleans explicitly: isinstance(True, int) is True in
            # Python, which would otherwise let a malformed entry through.
            if ts is None or isinstance(ts, bool) or not isinstance(ts, (int, float)):
                raise TelemetryParseError(
                    f"{jsonl_path}:line {line_num}: missing or non-numeric "
                    f"frame_ts_unix"
                )

            ts_float = float(ts)
            if min_ts is None or ts_float < min_ts:
                min_ts = ts_float
            if max_ts is None or ts_float > max_ts:
                max_ts = ts_float
            count += 1

    if count == 0:
        raise TelemetryParseError(
            f"{jsonl_path}: no valid telemetry entries found (empty file or "
            f"all lines blank)"
        )

    # After the count check above, min_ts and max_ts are guaranteed non-None.
    assert min_ts is not None and max_ts is not None
    return (min_ts, max_ts, count)


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
    # Required fields and their expected types. Order matters for the
    # bool-before-int check: isinstance(True, int) is True in Python, so
    # validate bool-typed fields with an explicit isinstance(v, bool).
    required: dict[str, type] = {
        "processed_frames": int,
        "telemetry_updates": int,
        "telemetry_errors_count": int,
        "used_mock_mavlink": bool,
        "used_mock_camera": bool,
    }

    try:
        with summary_path.open("r", encoding="utf-8") as f:
            parsed = json.load(f)
    except FileNotFoundError as exc:
        raise SummaryParseError(f"{summary_path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise SummaryParseError(
            f"{summary_path}: invalid JSON ({exc.msg})"
        ) from exc

    if not isinstance(parsed, dict):
        raise SummaryParseError(
            f"{summary_path}: top-level JSON must be an object, "
            f"got {type(parsed).__name__}"
        )

    # Collect all problems at once — do not fail fast on the first, so
    # users see the full picture.
    problems: list[str] = []
    for key, expected_type in required.items():
        if key not in parsed:
            problems.append(f"missing key '{key}'")
            continue
        value = parsed[key]
        if expected_type is bool:
            if not isinstance(value, bool):
                problems.append(
                    f"'{key}' expected bool, got {type(value).__name__}"
                )
        elif expected_type is int:
            # Reject bool for int fields (isinstance(True, int) is True).
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(
                    f"'{key}' expected int, got {type(value).__name__}"
                )

    if problems:
        raise SummaryParseError(
            f"{summary_path}: {'; '.join(problems)}"
        )

    # Return only the required fields, not the full summary dict.
    # Keeps the SummaryFields TypedDict honest.
    return {
        "processed_frames": parsed["processed_frames"],
        "telemetry_updates": parsed["telemetry_updates"],
        "telemetry_errors_count": parsed["telemetry_errors_count"],
        "used_mock_mavlink": parsed["used_mock_mavlink"],
        "used_mock_camera": parsed["used_mock_camera"],
    }


def compute_run_id(hostname: str, min_ts: float) -> str:
    """Derive the human-readable run identifier from hostname and session start time.

    Args:
        hostname: Machine hostname (e.g. from socket.gethostname()).
        min_ts: Unix epoch float representing the earliest frame timestamp
            (i.e. session start), used to derive the UTC date/time suffix.

    Returns:
        String of the form "run_{hostname}_{YYYYMMDD}_{HHMMSS}" in UTC.
    """
    dt = datetime.fromtimestamp(min_ts, tz=timezone.utc)
    date_str = dt.strftime("%Y%m%d_%H%M%S")
    return f"run_{hostname}_{date_str}"


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
    bucket = client.storage.from_(BUCKET_NAME)
    uploaded: dict[str, str] = {}

    # Iterate ARTIFACTS.items() (not paths.items()) so upload order
    # is deterministic regardless of how paths was constructed.
    for key, filename in ARTIFACTS.items():
        local_path = paths[key]
        object_path = f"{run_id}/{filename}"

        # Read file contents as bytes. Surfacing read errors here
        # (before the HTTP call) gives a clearer ArtifactUploadError
        # cause than a mid-upload network failure would.
        try:
            content = local_path.read_bytes()
        except OSError as exc:
            raise ArtifactUploadError(
                artifact_key=key,
                message=f"failed to read {local_path}: {exc}",
                cause=exc,
            ) from exc

        if verbose:
            print(
                f"[upload] {key}: {local_path} "
                f"-> {BUCKET_NAME}/{object_path} ({len(content)} bytes)",
                file=sys.stderr,
            )

        # Fresh dict per call: supabase-py's _upload_or_update
        # pops keys from file_options, mutating it.
        file_options = {
            "content-type": _CONTENT_TYPES[key],
            "upsert": "true",
        }

        try:
            resp = bucket.upload(
                path=object_path,
                file=content,
                file_options=file_options,
            )
        except StorageApiError as exc:
            # exc.status (int) and exc.message (str) are reliable;
            # exc.statusCode / exc.error may be absent in 2.24.0.
            status = getattr(exc, "status", "?")
            message = getattr(exc, "message", str(exc))
            raise ArtifactUploadError(
                artifact_key=key,
                message=f"upload failed (status={status}): {message}",
                cause=exc,
            ) from exc

        if verbose:
            print(f"[upload] {key}: OK -> {resp.full_path}",
                  file=sys.stderr)

        uploaded[key] = resp.full_path

    return uploaded


def upsert_run_row(client: Client, row: SkylinkRunRow) -> UpsertResult:
    """Upsert a skylink_runs row, returning uploaded_at and latency.

    On conflict on run_id, PostgREST updates uploaded_at=now() and
    re-populates the generated upload_latency_seconds column so
    re-uploads reflect the latest upload cycle, not the first.

    Args:
        client: Authenticated Supabase client (service role).
        row: SkylinkRunRow of column -> value pairs. Must include at
            minimum: run_id, started_at, ended_at, source_host,
            frame_count, telemetry_updates, telemetry_errors_count,
            used_mock_mavlink, used_mock_camera, and the four
            artifact_*_path values. mission_id is optional.

    Returns:
        UpsertResult with uploaded_at (ISO 8601) and
        upload_latency_seconds (float).

    Raises:
        RowUpsertError: If PostgREST returns an error, if the
            response data is not a single-row list, or if the
            returned row is missing uploaded_at or
            upload_latency_seconds.
    """
    try:
        resp = (
            client.table(TABLE_NAME)
            .upsert(row, on_conflict="run_id")
            .execute()
        )
    except APIError as exc:
        # APIError attributes are all Optional[str]; format what we have.
        detail_parts = []
        if getattr(exc, "code", None):
            detail_parts.append(f"code={exc.code}")
        if getattr(exc, "message", None):
            detail_parts.append(f"message={exc.message}")
        if getattr(exc, "details", None):
            detail_parts.append(f"details={exc.details}")
        if getattr(exc, "hint", None):
            detail_parts.append(f"hint={exc.hint}")
        joined = "; ".join(detail_parts) or str(exc)
        raise RowUpsertError(
            f"PostgREST upsert to {TABLE_NAME} failed: {joined}"
        ) from exc

    # resp.data is a list of dicts when returning='representation'
    # (the default). For a single-row upsert it must be length 1.
    if not isinstance(resp.data, list) or len(resp.data) != 1:
        raise RowUpsertError(
            f"upsert to {TABLE_NAME} returned unexpected data shape: "
            f"type={type(resp.data).__name__} len="
            f"{len(resp.data) if isinstance(resp.data, list) else 'n/a'}"
        )

    returned_row = resp.data[0]
    if not isinstance(returned_row, dict):
        raise RowUpsertError(
            f"upsert to {TABLE_NAME} returned non-dict row: "
            f"{type(returned_row).__name__}"
        )

    uploaded_at = returned_row.get("uploaded_at")
    latency = returned_row.get("upload_latency_seconds")
    if uploaded_at is None or latency is None:
        raise RowUpsertError(
            f"upsert to {TABLE_NAME} returned row missing required "
            f"fields: uploaded_at={uploaded_at!r}, "
            f"upload_latency_seconds={latency!r}"
        )

    return {
        "uploaded_at": str(uploaded_at),
        # PostgREST may return numeric as int/float/string depending
        # on client parsing — coerce to float for stable downstream use.
        "upload_latency_seconds": float(latency),
    }


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

    # ---- Load credentials from environment ----
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
            "in the environment. Source ~/.skylink_env first "
            "(use `set -a; source ~/.skylink_env; set +a`).",
            file=sys.stderr,
        )
        return 1

    if args.verbose:
        print(f"[main] config loaded; output_dir={args.output_dir}",
              file=sys.stderr)

    # ---- Validate output directory ----
    try:
        paths = validate_output_dir(args.output_dir)
    except MissingArtifactError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # ---- Parse telemetry + summary ----
    try:
        min_ts, max_ts, frame_count = parse_telemetry(paths["jsonl"])
    except TelemetryParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    try:
        summary = parse_summary(paths["summary"])
    except SummaryParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    # ---- Compute run_id ----
    hostname = socket.gethostname()
    run_id = args.run_id or compute_run_id(hostname, min_ts)

    # ---- Build the DB row ----
    # artifact_*_path fields are populated after successful upload, below.
    row: SkylinkRunRow = {
        "run_id": run_id,
        "started_at": datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat(),
        "ended_at": datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat(),
        "source_host": hostname,
        "frame_count": frame_count,
        "telemetry_updates": summary["telemetry_updates"],
        "telemetry_errors_count": summary["telemetry_errors_count"],
        "used_mock_mavlink": summary["used_mock_mavlink"],
        "used_mock_camera": summary["used_mock_camera"],
    }
    # Only include mission_id if provided — TypedDict(total=False) permits
    # omission so the column stays NULL (matching FK ON DELETE SET NULL).
    if args.mission_id is not None:
        row["mission_id"] = args.mission_id

    # ---- Dry-run branch ----
    if args.dry_run:
        # Print the computed row payload as pretty JSON so the caller can
        # verify field derivation without writing anything to Supabase.
        # Artifact paths are absent because no upload occurred.
        print("DRY RUN: would upsert the following row "
              "(no actual writes performed):")
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0

    # ---- Create Supabase client and perform real upload + upsert ----
    if args.verbose:
        print(f"[main] starting upload: run_id={run_id} "
              f"frames={frame_count}",
              file=sys.stderr)

    client = create_client(url, key)

    try:
        uploaded = upload_artifacts(client, run_id, paths,
                                    verbose=args.verbose)
    except ArtifactUploadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    # Merge uploaded bucket paths into the row using ARTIFACT_COLUMN_MAP
    # so the column names match the table schema exactly.
    for artifact_key, bucket_path in uploaded.items():
        column_name = ARTIFACT_COLUMN_MAP[artifact_key]
        row[column_name] = bucket_path  # type: ignore[literal-required]

    if args.verbose:
        print(f"[main] upload complete; upserting row", file=sys.stderr)

    try:
        result = upsert_run_row(client, row)
    except RowUpsertError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5

    # ---- Success — print SUCCESS line per stdout contract ----
    latency = result["upload_latency_seconds"]
    print(
        f"SUCCESS: run_id={run_id} "
        f"uploaded_at={result['uploaded_at']} "
        f"latency_s={latency:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
