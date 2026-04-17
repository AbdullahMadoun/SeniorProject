from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from typing import Any
import urllib.error
import urllib.request

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.interactive_mission import (
    LOW_BATTERY_ACTION_LAND,
    LOW_BATTERY_ACTION_RETURN,
    LOW_BATTERY_ACTION_WARNING,
    WEATHER_PROFILE_MODE_FULL_TRIP,
    WEATHER_PROFILE_MODE_PROOF,
    default_battery_overrides,
    default_environment_overrides,
    default_weather_profile,
    interactive_mission_spec_from_dict,
    interactive_mission_spec_to_dict,
    validate_interactive_mission,
)
from autonomy.drone_system.remote_bridge import (
    RemoteExecutionBridge,
    remote_bridge_from_env,
)
from autonomy.drone_system.runtime_affinity import enforce_cpu_affinity


RUNNER_SCRIPT = AUTONOMY_ROOT / "scripts" / "run_live_interactive_mission.py"
PLANNER_DIR = REPO_ROOT / "artifacts" / "planner"
DASHBOARD_DIR = REPO_ROOT / "artifacts" / "dashboard"
SHOWCASE_DIR = REPO_ROOT / "artifacts" / "showcase"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
JOB_CACHE_DIR = PLANNER_DIR / "job_cache"
DEFAULT_TARGET = "udpin://0.0.0.0:14540"
DEFAULT_BRIDGE_STATUS = "Bridge Active"
DEFAULT_REMOTE_BRIDGE_STATUS = "Remote Ready"
DEFAULT_SHOWCASE_REDIRECT = "../showcase/latest/index.html"
TELEMETRY_PREFIX = "__TELEMETRY__"
DEFAULT_FPV_SOURCE_URL = os.environ.get("SKYLINK_FPV_SOURCE_URL", "http://127.0.0.1:5050/stream")
DEFAULT_FPV_PROXY_PATH = "/api/fpv/stream"
DEFAULT_FPV_ENABLED = os.environ.get("SKYLINK_FPV_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_FPV_MODE = os.environ.get("SKYLINK_FPV_MODE", "simulation")
DEFAULT_CPU_CORE = int(os.environ.get("SKYLINK_API_CPU_CORE", "0"))
DEFAULT_EXECUTION_CPU_CORES = os.environ.get("SKYLINK_EXECUTION_CPU_CORES", "2,3")
CONTROL_FIELD_NAMES = {"remote", "execution_mode"}

baseline = load_system_baseline()
default_environment = default_environment_overrides()
default_battery = default_battery_overrides()


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _constraints_payload() -> dict[str, Any]:
    return {
        "home": {
            "lat": baseline.home.lat,
            "lon": baseline.home.lon,
            "alt_m": baseline.home.alt_m,
        },
        "mission_limits": {
            "max_radius_m": baseline.mission_limits.max_radius_m,
            "max_altitude_m": baseline.mission_limits.max_altitude_m,
            "min_waypoints": 2,
        },
        "speed_band": {
            "min_mps": baseline.speed_band.min_mps,
            "default_cruise_mps": baseline.speed_band.nominal_mps,
            "max_mps": baseline.speed_band.max_mps,
        },
        "safety": {
            "battery_warn_percent": baseline.safety.battery_warn_percent,
            "battery_rtl_percent": baseline.safety.battery_rtl_percent,
            "battery_emergency_percent": baseline.safety.battery_emergency_percent,
            "max_operating_wind_mps": baseline.safety.max_operating_wind_mps,
        },
        "connection": {
            "target": DEFAULT_TARGET,
            "status": DEFAULT_BRIDGE_STATUS,
        },
        "fpv": {
            "enabled": DEFAULT_FPV_ENABLED,
            "mode": DEFAULT_FPV_MODE,
            "source_url": DEFAULT_FPV_SOURCE_URL,
            "proxy_url": DEFAULT_FPV_PROXY_PATH,
        },
        "default_environment": {
            "wind_speed_mps": default_environment.wind_speed_mps,
            "wind_direction_deg": default_environment.wind_direction_deg,
            "gust_multiplier": default_environment.gust_multiplier,
        },
        "default_battery": {
            "initial_battery_percent": default_battery.initial_battery_percent,
            "warn_battery_threshold_percent": default_battery.warn_battery_threshold_percent,
            "rtl_battery_threshold_percent": default_battery.rtl_battery_threshold_percent,
            "emergency_battery_threshold_percent": default_battery.emergency_battery_threshold_percent,
            "low_battery_action": default_battery.low_battery_action,
        },
        "default_simulation": {
            "weather_profile_mode": WEATHER_PROFILE_MODE_PROOF,
        },
        "battery_actions": [
            {"id": LOW_BATTERY_ACTION_WARNING, "label": "Warn Only"},
            {"id": LOW_BATTERY_ACTION_LAND, "label": "Land"},
            {"id": LOW_BATTERY_ACTION_RETURN, "label": "Return"},
        ],
        "weather_profile_modes": [
            {"id": WEATHER_PROFILE_MODE_PROOF, "label": "Proof RTL"},
            {"id": WEATHER_PROFILE_MODE_FULL_TRIP, "label": "Full Trip"},
        ],
        "default_weather_profile": [
            {
                "t_s": point.t_s,
                "steady_wind_mps": point.steady_wind_mps,
                "gust_wind_mps": point.gust_wind_mps,
            }
            for point in default_weather_profile()
        ],
    }


def _normalize_payload(body: Any) -> dict[str, Any]:
    if isinstance(body, list):
        return {
            "mission_id": "interactive-mission",
            "cruise_speed_mps": baseline.speed_band.nominal_mps,
            "waypoints": body,
            "weather_profile": [
                {
                    "t_s": point.t_s,
                    "steady_wind_mps": point.steady_wind_mps,
                    "gust_wind_mps": point.gust_wind_mps,
                }
                for point in default_weather_profile()
            ],
        }
    if isinstance(body, dict):
        normalized = dict(body)
        for key in CONTROL_FIELD_NAMES:
            normalized.pop(key, None)
        normalized.setdefault("mission_id", "interactive-mission")
        normalized.setdefault("cruise_speed_mps", baseline.speed_band.nominal_mps)
        return normalized
    raise HTTPException(status_code=400, detail="Mission payload must be an object or a waypoint list.")


def _execution_mode_from_body(body: Any) -> str:
    if not isinstance(body, dict):
        return "local"
    execution_mode = str(body.get("execution_mode", "")).strip().lower()
    if execution_mode == "remote":
        return "remote"
    if bool(body.get("remote")):
        return "remote"
    return "local"


def _parse_and_validate(body: Any):
    payload = _normalize_payload(body)
    try:
        spec = interactive_mission_spec_from_dict(payload, baseline)
        validate_interactive_mission(spec, baseline)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return spec


def _format_sse(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


def _extract_telemetry_payload(line: str) -> dict[str, Any] | None:
    prefix_index = line.find(TELEMETRY_PREFIX)
    if prefix_index < 0:
        return None
    raw_payload = line[prefix_index + len(TELEMETRY_PREFIX) :]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _fpv_stream_target(source_url: str | None) -> str:
    return source_url or DEFAULT_FPV_SOURCE_URL


@dataclass
class MissionExecutionJob:
    job_id: str
    spec_path: Path
    created_at: str
    spec: dict[str, Any]
    status: str = "queued"
    redirect_url: str = "../dashboard/index.html"
    execution_mode: str = "local"
    target: str = DEFAULT_TARGET
    bridge_status: str = DEFAULT_BRIDGE_STATUS
    events: list[dict[str, Any]] = field(default_factory=list)
    telemetry_events: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int | None = None
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    event_offset: int = 0
    telemetry_offset: int = 0
    total_event_count: int = 0
    total_telemetry_count: int = 0
    max_event_buffer: int = 5000
    max_telemetry_buffer: int = 1024

    def append_event(self, event_name: str, data: dict[str, Any]) -> None:
        with self.lock:
            payload = {
                "seq": self.total_event_count,
                "event": event_name,
                "data": data,
            }
            self.events.append(payload)
            self.total_event_count += 1
            overflow = len(self.events) - self.max_event_buffer
            if overflow > 0:
                del self.events[:overflow]
                self.event_offset += overflow

    def append_telemetry(self, data: dict[str, Any]) -> None:
        with self.lock:
            payload = {
                "seq": self.total_telemetry_count,
                "event": "telemetry",
                "data": data,
            }
            self.telemetry_events.append(payload)
            self.total_telemetry_count += 1
            overflow = len(self.telemetry_events) - self.max_telemetry_buffer
            if overflow > 0:
                del self.telemetry_events[:overflow]
                self.telemetry_offset += overflow

    def events_since(self, cursor: int) -> tuple[list[dict[str, Any]], str]:
        with self.lock:
            effective_cursor = max(cursor, self.event_offset)
            start_index = max(0, effective_cursor - self.event_offset)
            return list(self.events[start_index:]), self.status

    def telemetry_since(self, cursor: int) -> tuple[list[dict[str, Any]], str]:
        with self.lock:
            effective_cursor = max(cursor, self.telemetry_offset)
            start_index = max(0, effective_cursor - self.telemetry_offset)
            return list(self.telemetry_events[start_index:]), self.status

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "status": self.status,
                "created_at": self.created_at,
                "redirect_url": self.redirect_url,
                "execution_mode": self.execution_mode,
                "target": self.target,
                "bridge_status": self.bridge_status,
                "exit_code": self.exit_code,
                "event_count": self.total_event_count,
                "telemetry_event_count": self.total_telemetry_count,
                "spec": self.spec,
            }


class MissionExecutionManager:
    def __init__(self) -> None:
        self._jobs: dict[str, MissionExecutionJob] = {}
        self._lock = threading.Lock()
        JOB_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _remote_bridge(self) -> RemoteExecutionBridge | None:
        return remote_bridge_from_env(REPO_ROOT)

    def remote_status(self) -> dict[str, Any]:
        bridge = self._remote_bridge()
        if bridge is None:
            return {
                "configured": False,
                "reachable": False,
                "status": "unavailable",
                "status_label": "Remote Unavailable",
                "detail": "Remote execution is not configured.",
                "target": "",
                "target_label": "",
                "repo_root": "",
                "repo_present": False,
                "venv_present": False,
                "runner_present": False,
                "px4_binary_present": False,
                "sitl_running": False,
                "mavlink_ready": False,
                "ready_for_remote_execution": False,
            }
        return bridge.check_status()

    def start_job(self, spec, *, execution_mode: str = "local") -> MissionExecutionJob:
        with self._lock:
            active = self.active_job()
            if active is not None:
                raise RuntimeError(f"Mission job {active.job_id} is already running.")
            job_id = uuid.uuid4().hex[:12]
            job_dir = JOB_CACHE_DIR / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            spec_path = job_dir / "mission_request.json"
            spec_path.write_text(
                json.dumps(interactive_mission_spec_to_dict(spec), indent=2),
                encoding="utf-8",
            )
            execution_mode = execution_mode if execution_mode == "remote" else "local"
            target = DEFAULT_TARGET
            bridge_status = DEFAULT_BRIDGE_STATUS
            redirect_url = "../dashboard/index.html"
            remote_status: dict[str, Any] | None = None
            if execution_mode == "remote":
                remote_status = self.remote_status()
                if not remote_status.get("configured", False):
                    raise RuntimeError(str(remote_status.get("detail", "Remote execution is not configured.")))
                if not remote_status.get("ready_for_remote_execution", False):
                    raise RuntimeError(str(remote_status.get("detail", "Remote execution host is not ready.")))
                target = str(remote_status.get("target_label") or remote_status.get("target") or DEFAULT_TARGET)
                bridge_status = str(remote_status.get("status_label") or DEFAULT_REMOTE_BRIDGE_STATUS)
                redirect_url = DEFAULT_SHOWCASE_REDIRECT
            job = MissionExecutionJob(
                job_id=job_id,
                spec_path=spec_path,
                created_at=_timestamp_utc(),
                spec=interactive_mission_spec_to_dict(spec),
                execution_mode=execution_mode,
                target=target,
                bridge_status=bridge_status,
                redirect_url=redirect_url,
            )
            job.status = "running"
            job.append_event(
                "metadata",
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "execution_mode": execution_mode,
                    "target": target,
                    "bridge_status": bridge_status,
                    "redirect_url": job.redirect_url,
                    "created_at": job.created_at,
                    "spec": job.spec,
                    "remote_status": remote_status,
                },
            )
            self._jobs[job_id] = job
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"mission-job-{job_id}",
                daemon=True,
            )
            thread.start()
            return job

    def active_job(self) -> MissionExecutionJob | None:
        for job in self._jobs.values():
            if job.status == "running":
                return job
        return None

    def get_job(self, job_id: str) -> MissionExecutionJob | None:
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> MissionExecutionJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise RuntimeError(f"Mission job {job_id} was not found.")
            if job.status != "running":
                return job
            job.cancel_requested = True
            job.append_event(
                "status",
                {
                    "message": "Cancellation requested.",
                    "status": "cancelling",
                },
            )
            if job.execution_mode == "remote":
                bridge = self._remote_bridge()
                if bridge is not None:
                    bridge.cancel_remote_job(job.job_id)
            if job.process is not None and job.process.poll() is None:
                with contextlib.suppress(Exception):
                    job.process.terminate()
            return job

    def _run_job(self, job: MissionExecutionJob) -> None:
        try:
            if job.execution_mode == "remote":
                exit_code = self._run_remote_job(job)
            else:
                exit_code = self._run_local_job(job)
        except Exception as exc:
            job.exit_code = -1
            if job.cancel_requested:
                job.status = "cancelled"
                job.append_event(
                    "cancelled",
                    {
                        "job_id": job.job_id,
                        "status": job.status,
                        "success": False,
                        "redirect_url": job.redirect_url,
                        "detail": str(exc),
                    },
                )
                return
            job.status = "failed"
            job.append_event(
                "failed",
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "success": False,
                    "exit_code": job.exit_code,
                    "redirect_url": job.redirect_url,
                    "detail": str(exc),
                },
            )
            return

        job.exit_code = exit_code
        if job.cancel_requested:
            job.status = "cancelled"
            job.append_event(
                "cancelled",
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "success": False,
                    "exit_code": exit_code,
                    "redirect_url": job.redirect_url,
                },
            )
            return
        if exit_code == 0:
            job.status = "completed"
            job.append_event(
                "complete",
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "success": True,
                    "redirect_url": job.redirect_url,
                },
            )
            return

        job.status = "failed"
        job.append_event(
            "failed",
            {
                "job_id": job.job_id,
                "status": job.status,
                "success": False,
                "exit_code": exit_code,
                "redirect_url": job.redirect_url,
            },
        )

    def _run_local_job(self, job: MissionExecutionJob) -> int:
        command = [
            sys.executable,
            str(RUNNER_SCRIPT),
            "--mission-spec",
            str(job.spec_path),
            "--cpu-cores",
            DEFAULT_EXECUTION_CPU_CORES,
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
        )
        job.process = process
        job.append_event(
            "status",
            {
                "message": "Mission execution started.",
                "status": "running",
            },
        )

        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            telemetry_payload = _extract_telemetry_payload(line)
            if telemetry_payload is not None:
                job.append_telemetry(telemetry_payload)
                continue
            job.append_event(
                "log",
                {
                    "message": line,
                },
            )
        return process.wait()

    def _run_remote_job(self, job: MissionExecutionJob) -> int:
        bridge = self._remote_bridge()
        if bridge is None:
            raise RuntimeError("Remote execution is not configured.")
        remote_spec_path = bridge.upload_mission_spec(job.spec_path, job_id=job.job_id)
        job.append_event(
            "status",
            {
                "message": "Mission spec uploaded to remote SITL host.",
                "status": "running",
                "execution_mode": "remote",
            },
        )
        process = bridge.start_remote_mission_process(
            remote_spec_path,
            job_id=job.job_id,
            cpu_cores=DEFAULT_EXECUTION_CPU_CORES,
        )
        job.process = process
        job.append_event(
            "status",
            {
                "message": "Remote mission execution started.",
                "status": "running",
                "execution_mode": "remote",
            },
        )

        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            telemetry_payload = _extract_telemetry_payload(line)
            if telemetry_payload is not None:
                job.append_telemetry(telemetry_payload)
                continue
            job.append_event(
                "log",
                {
                    "message": line,
                },
            )

        exit_code = process.wait()
        if exit_code == 0 and not job.cancel_requested:
            job.append_event(
                "status",
                {
                    "message": "Remote mission complete. Syncing artifacts locally.",
                    "status": "running",
                    "execution_mode": "remote",
                },
            )
            bridge.download_artifacts(local_repo_root=REPO_ROOT)
            job.append_event(
                "status",
                {
                    "message": "Remote artifacts synced locally.",
                    "status": "running",
                    "execution_mode": "remote",
                },
            )
        return exit_code


job_manager = MissionExecutionManager()

app = FastAPI(title="SkyLink Interactive Mission API")
PLANNER_DIR.mkdir(parents=True, exist_ok=True)
DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")
app.mount("/planner", StaticFiles(directory=PLANNER_DIR), name="planner")
app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR), name="dashboard")
app.mount("/showcase", StaticFiles(directory=SHOWCASE_DIR), name="showcase")


@app.get("/", response_class=RedirectResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/index.html", status_code=307)


@app.get("/api/constraints")
async def constraints() -> dict[str, Any]:
    return _constraints_payload()


@app.post("/api/mission/validate")
async def validate_mission(body: Any = Body(...)) -> dict[str, Any]:
    spec = _parse_and_validate(body)
    return {
        "valid": True,
        "mission": interactive_mission_spec_to_dict(spec),
        "constraints": _constraints_payload(),
        "checks": {
            "geofence": True,
            "min_waypoints": len(spec.waypoints) >= 2,
            "altitude": True,
        },
    }


@app.post("/api/mission/execute")
async def execute_mission(
    body: Any = Body(...),
    remote: bool = Query(default=False),
) -> dict[str, Any]:
    execution_mode = "remote" if remote else _execution_mode_from_body(body)
    if PREPARED_SPEC_PATH.exists():
        try:
            spec_dict = json.loads(PREPARED_SPEC_PATH.read_text(encoding="utf-8-sig"))
            baseline = load_system_baseline()
            spec = interactive_mission_spec_from_dict(spec_dict, baseline)
            validate_interactive_mission(spec, baseline)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            PREPARED_SPEC_PATH.unlink(missing_ok=True)
    else:
        spec = _parse_and_validate(body)
    try:
        job = job_manager.start_job(spec, execution_mode=execution_mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "job_id": job.job_id,
        "status": job.status,
        "redirect_url": job.redirect_url,
        "execution_mode": job.execution_mode,
        "target": job.target,
        "bridge_status": job.bridge_status,
        "spec": job.spec,
    }


PREPARED_SPEC_PATH = JOB_CACHE_DIR / "_prepared_mission.json"


@app.post("/api/mission/prepare")
async def prepare_mission(body: Any = Body(...)) -> dict[str, Any]:
    spec = _parse_and_validate(body)
    PREPARED_SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREPARED_SPEC_PATH.write_text(
        json.dumps(interactive_mission_spec_to_dict(spec), indent=2),
        encoding="utf-8",
    )
    return {
        "job_id": "prepared",
        "status": "prepared",
        "message": "Simulation prepared. Click Launch to execute.",
        "spec": interactive_mission_spec_to_dict(spec),
    }


@app.get("/api/remote/status")
async def remote_status() -> dict[str, Any]:
    return job_manager.remote_status()


@app.post("/api/mission/cancel")
async def cancel_mission(job_id: str = Query(...)) -> dict[str, Any]:
    try:
        job = job_manager.cancel_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return job.snapshot()


@app.get("/api/fpv/stream")
async def fpv_stream(source_url: str | None = Query(default=None)) -> StreamingResponse:
    if not DEFAULT_FPV_ENABLED and source_url is None:
        raise HTTPException(status_code=503, detail="FPV stream is disabled.")

    target = _fpv_stream_target(source_url)
    try:
        probe = urllib.request.urlopen(target, timeout=5.0)
        content_type = probe.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        probe.close()
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"FPV stream unavailable: {target}") from exc

    def _stream() -> Any:
        with urllib.request.urlopen(target, timeout=30.0) as response:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _stream(),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": content_type,
        },
    )


@app.get("/api/system/logs")
async def system_logs(job_id: str | None = Query(default=None)) -> StreamingResponse:
    job = job_manager.get_job(job_id) if job_id else job_manager.active_job()
    if job is None:
        raise HTTPException(status_code=404, detail="Mission job not found.")

    async def _event_stream() -> Any:
        cursor = 0
        heartbeat_at = asyncio.get_running_loop().time()
        while True:
            pending, status = job.events_since(cursor)
            for event in pending:
                cursor = event["seq"] + 1
                yield _format_sse(event["event"], event["data"])
                heartbeat_at = asyncio.get_running_loop().time()
            if status in {"completed", "failed", "cancelled"} and not pending:
                break
            now = asyncio.get_running_loop().time()
            if now - heartbeat_at >= 5.0:
                yield ": keep-alive\n\n"
                heartbeat_at = now
            await asyncio.sleep(0.2)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/telemetry/live")
async def telemetry_live(job_id: str | None = Query(default=None)) -> StreamingResponse:
    job = job_manager.get_job(job_id) if job_id else job_manager.active_job()
    if job is None:
        raise HTTPException(status_code=404, detail="Mission job not found.")

    async def _event_stream() -> Any:
        cursor = 0
        heartbeat_at = asyncio.get_running_loop().time()
        while True:
            pending, status = job.telemetry_since(cursor)
            for event in pending:
                cursor = event["seq"] + 1
                yield _format_sse("telemetry", event["data"])
                heartbeat_at = asyncio.get_running_loop().time()
            if status in {"completed", "failed", "cancelled"} and not pending:
                break
            now = asyncio.get_running_loop().time()
            if now - heartbeat_at >= 5.0:
                yield ": keep-alive\n\n"
                heartbeat_at = now
            await asyncio.sleep(0.15)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/system/job/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Mission job not found.")
    return job.snapshot()


@app.get("/api/planner", response_class=HTMLResponse)
async def planner_redirect() -> RedirectResponse:
    return RedirectResponse(url="/planner/index.html", status_code=307)


@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/index.html", status_code=307)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8625)
    parser.add_argument("--cpu-core", type=int, default=DEFAULT_CPU_CORE)
    args = parser.parse_args(argv)

    enforce_cpu_affinity(args.cpu_core, label="mission_api")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
