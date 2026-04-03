"""
Job state persistence with atomic writes and crash recovery.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path("artifacts/planner/job_cache")
PERSIST_INTERVAL_S = 5.0
MAX_PERSIST_ITEMS = 100

@dataclass(frozen=True)
class PersistedJobState:
    job_id: str
    status: str
    created_at: str
    phase: str | None
    events: list[dict[str, Any]]
    telemetry: list[dict[str, Any]]
    persist_time: float
    version: str = "1.0"

@dataclass
class PersistedJobMetadata:
    job_id: str
    spec_path: Path
    created_at: str
    status: str

class JobStateStore:
    """Persistent storage for job state with atomic writes."""
    
    def __init__(self, state_dir: Path = STATE_DIR) -> None:
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, job_id: str, state: PersistedJobState) -> None:
        """Atomic write: temp file + rename."""
        job_dir = self._state_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        
        temp_path = job_dir / "job_state.tmp"
        state_path = job_dir / "job_state.json"
        
        temp_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        temp_path.rename(state_path)
    
    def load(self, job_id: str) -> PersistedJobState | None:
        """Load job state from disk."""
        state_path = self._state_dir / job_id / "job_state.json"
        if not state_path.exists():
            return None
        
        with open(state_path) as f:
            data = json.loads(f.read())
        
        return PersistedJobState(**data)
    
    def list_jobs(self) -> list[PersistedJobMetadata]:
        """List all persisted jobs."""
        jobs = []
        for job_dir in self._state_dir.iterdir():
            if not job_dir.is_dir():
                continue
            
            state_path = job_dir / "job_state.json"
            if state_path.exists():
                with open(state_path) as f:
                    data = json.loads(f.read())
                jobs.append(PersistedJobMetadata(
                    job_id=data["job_id"],
                    spec_path=job_dir / "mission_request.json",
                    created_at=data["created_at"],
                    status=data["status"],
                ))
        
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)
    
    def delete(self, job_id: str) -> None:
        """Delete job state."""
        import shutil
        job_dir = self._state_dir / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)

class BackgroundPersistor:
    """Background task that periodically persists job state."""
    
    def __init__(self, store: JobStateStore, interval_s: float = PERSIST_INTERVAL_S) -> None:
        self._store = store
        self._interval_s = interval_s
        self._jobs: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
    
    def register(self, job: Any) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
    
    def unregister(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
    
    def _persist_loop(self) -> None:
        while self._running:
            time.sleep(self._interval_s)
            with self._lock:
                for job_id, job in list(self._jobs.items()):
                    try:
                        state = PersistedJobState(
                            job_id=job.job_id,
                            status=job.status.value if hasattr(job.status, 'value') else str(job.status),
                            created_at=job.created_at.isoformat() if hasattr(job.created_at, 'isoformat') else str(job.created_at),
                            phase=getattr(job, '_phase', None),
                            events=job._events[-MAX_PERSIST_ITEMS:] if hasattr(job, '_events') else [],
                            telemetry=job._telemetry[-MAX_PERSIST_ITEMS:] if hasattr(job, '_telemetry') else [],
                            persist_time=time.time(),
                        )
                        self._store.save(job_id, state)
                    except Exception as exc:
                        print(f"[PERSISTOR] Failed to persist {job_id}: {exc}", flush=True)
    
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._persist_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
