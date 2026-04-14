"""
Tests for job state persistence.
"""
from __future__ import annotations

import json
import tempfile
import shutil
import time
from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from autonomy.drone_system.job_state import (
    JobStateStore,
    BackgroundPersistor,
    PersistedJobState,
    MAX_PERSIST_ITEMS,
)

class TestJobStateStore:
    """Tests for JobStateStore atomic writes."""
    
    @pytest.fixture
    def temp_dir(self):
        tmp = Path(tempfile.mkdtemp())
        yield tmp
        shutil.rmtree(tmp)
    
    @pytest.fixture
    def store(self, temp_dir):
        return JobStateStore(state_dir=temp_dir)
    
    def test_atomic_write(self, store, temp_dir):
        """Write must be atomic (temp file renamed)."""
        state = PersistedJobState(
            job_id="test123",
            status="running",
            created_at="2026-04-03T00:00:00",
            phase="execute",
            events=[{"type": "start", "time": 0}],
            telemetry=[{"time": 0, "lat": 24.0}],
            persist_time=123456.0,
        )
        
        store.save("test123", state)
        
        assert not (temp_dir / "test123" / "job_state.tmp").exists()
        assert (temp_dir / "test123" / "job_state.json").exists()
    
    def test_load_recovers_state(self, store, temp_dir):
        """Load must recover saved state."""
        state = PersistedJobState(
            job_id="test456",
            status="complete",
            created_at="2026-04-03T00:00:00",
            phase=None,
            events=[{"type": "start"}, {"type": "complete"}],
            telemetry=[{"time": 0}, {"time": 1}],
            persist_time=123456.0,
        )
        
        store.save("test456", state)
        loaded = store.load("test456")
        
        assert loaded.job_id == "test456"
        assert loaded.status == "complete"
        assert len(loaded.events) == 2
    
    def test_load_nonexistent_returns_none(self, store):
        """Load non-existent job returns None."""
        assert store.load("nonexistent") is None
    
    def test_list_jobs_sorted_by_created_at(self, store, temp_dir):
        """List jobs sorted newest first."""
        for i in range(3):
            state = PersistedJobState(
                job_id=f"job{i}",
                status="complete",
                created_at=f"2026-04-0{i+1}T00:00:00",
                phase=None,
                events=[],
                telemetry=[],
                persist_time=123456.0 + i,
            )
            store.save(f"job{i}", state)
        
        jobs = store.list_jobs()
        assert len(jobs) == 3
        assert jobs[0].job_id == "job2"
    
    def test_delete_removes_job(self, store, temp_dir):
        """Delete removes job directory."""
        state = PersistedJobState(
            job_id="delete_me",
            status="complete",
            created_at="2026-04-03T00:00:00",
            phase=None,
            events=[],
            telemetry=[],
            persist_time=123456.0,
        )
        store.save("delete_me", state)
        assert store.load("delete_me") is not None
        
        store.delete("delete_me")
        assert store.load("delete_me") is None


class TestBackgroundPersistor:
    """Tests for BackgroundPersistor."""
    
    @pytest.fixture
    def temp_dir(self):
        tmp = Path(tempfile.mkdtemp())
        yield tmp
        shutil.rmtree(tmp)
    
    @pytest.fixture
    def mock_job(self):
        job = type('MockJob', (), {})()
        job.job_id = "test_job"
        job.status = type('Status', (), {'value': 'running'})()
        job.created_at = type('DT', (), {'isoformat': lambda s: "2026-04-03T00:00:00"})()
        job._events = [{"type": "event1"}, {"type": "event2"}]
        job._telemetry = [{"time": 0}, {"time": 1}, {"time": 2}]
        job._phase = "execute"
        return job
    
    def test_register_adds_to_jobs(self, mock_job):
        """Register adds job to tracking dict."""
        store = JobStateStore()
        persistor = BackgroundPersistor(store)
        persistor.register(mock_job)
        assert "test_job" in persistor._jobs
    
    def test_unregister_removes_from_jobs(self, mock_job):
        """Unregister removes job from tracking dict."""
        store = JobStateStore()
        persistor = BackgroundPersistor(store)
        persistor.register(mock_job)
        persistor.unregister("test_job")
        assert "test_job" not in persistor._jobs
    
    def test_persist_writes_to_store(self, mock_job, temp_dir):
        """Persist loop writes job state to store."""
        store = JobStateStore(temp_dir)
        persistor = BackgroundPersistor(store, interval_s=0.01)
        persistor.register(mock_job)
        persistor.start()
        
        time.sleep(0.05)  # Wait for persist loop
        
        persistor.stop()
        
        loaded = store.load("test_job")
        assert loaded is not None
        assert loaded.job_id == "test_job"
