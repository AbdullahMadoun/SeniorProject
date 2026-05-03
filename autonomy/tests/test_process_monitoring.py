"""
Tests for child process monitoring.
"""
from __future__ import annotations

import pytest
import threading
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.scripts.run_live_interactive_mission import (
    ProcessManager,
    ProcessInfo,
    get_process_manager,
)


class TestProcessInfo:
    """Tests for ProcessInfo dataclass."""

    def test_creates_with_process_and_name(self):
        """ProcessInfo requires process and name."""
        proc = MagicMock()
        proc.pid = 12345
        info = ProcessInfo(process=proc, name="TEST")
        assert info.process is proc
        assert info.name == "TEST"

    def test_optional_ready_event(self):
        """ProcessInfo has optional ready_event."""
        proc = MagicMock()
        event = threading.Event()
        info = ProcessInfo(process=proc, name="TEST", ready_event=event)
        assert info.ready_event is event


@pytest.fixture
def manager():
    """Create fresh ProcessManager for each test."""
    m = ProcessManager()
    yield m
    m.shutdown()


class TestProcessManager:
    """Tests for ProcessManager."""

    def test_register_adds_process(self, manager):
        """Register adds process to tracking dict."""
        proc = MagicMock()
        proc.pid = 12345
        manager.register(proc, "TEST_PROCESS")
        assert 12345 in manager._processes

    def test_register_stores_name(self, manager):
        """Register stores process name."""
        proc = MagicMock()
        proc.pid = 12345
        manager.register(proc, "MY_PROCESS")
        assert manager._process_names[12345] == "MY_PROCESS"

    def test_multiple_processes_register(self, manager):
        """Can register multiple processes."""
        for i in range(3):
            proc = MagicMock()
            proc.pid = 1000 + i
            manager.register(proc, f"PROCESS_{i}")

        assert len(manager._processes) == 3

    def test_shutdown_terminates_processes(self, manager):
        """Shutdown sends SIGTERM to running processes."""
        proc = MagicMock()
        proc.pid = 12345
        proc.poll.return_value = None
        manager.register(proc, "TEST_PROCESS")

        manager.shutdown()

        proc.terminate.assert_called_once()

    def test_shutdown_kills_unresponsive_processes(self, manager):
        """Shutdown kills processes that don't respond to SIGTERM."""
        proc = MagicMock()
        proc.pid = 12345
        proc.poll.return_value = None
        proc.terminate.side_effect = PermissionError("Cannot terminate")
        manager.register(proc, "TEST_PROCESS")

        manager.shutdown()

        proc.kill.assert_called_once()

    def test_shutdown_clears_processes(self, manager):
        """Shutdown clears process dict."""
        proc = MagicMock()
        proc.pid = 12345
        proc.poll.return_value = 0
        manager.register(proc, "TEST_PROCESS")

        manager.shutdown()

        assert len(manager._processes) == 0


class TestSignalHandling:
    """Tests for signal handling in ProcessManager."""

    def test_register_registers_signal_handlers(self):
        """start_monitoring registers SIGTERM/SIGINT handlers."""
        manager = ProcessManager()

        with patch("signal.signal") as mock_signal:
            manager.start_monitoring()
            assert mock_signal.call_count == 2

        manager.stop_monitoring()
        manager.shutdown()


class TestGetProcessManager:
    """Tests for get_process_manager singleton."""

    def test_returns_process_manager_instance(self):
        """get_process_manager returns a ProcessManager."""
        manager = get_process_manager()
        assert isinstance(manager, ProcessManager)

    def test_managers_function_independently(self):
        """Each test should get its own manager context."""
        m1 = ProcessManager()
        m2 = ProcessManager()
        assert m1 is not m2
        m1.shutdown()
        m2.shutdown()
