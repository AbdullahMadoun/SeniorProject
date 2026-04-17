from __future__ import annotations

import io
import tempfile
from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.remote_bridge import (
    CommandResult,
    RemoteExecutionBridge,
    RemoteTarget,
    RemoteTimeoutError,
    StreamKind,
)


class _FakePopen:
    def __init__(
        self,
        *,
        stdout_text: str = "",
        stderr_text: str = "",
        exit_code: int = 0,
        poll_code: int | None = None,
    ) -> None:
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._exit_code = int(exit_code)
        self._poll_code = poll_code
        self.terminated = False

    def poll(self) -> int | None:
        return self._poll_code

    def wait(self) -> int:
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True


class _FakeExecutor:
    def __init__(self) -> None:
        self.run_calls: list[tuple[tuple[str, ...], str | None, float | None]] = []
        self.popen_calls: list[tuple[tuple[str, ...], str | None]] = []
        self.next_run_results: list[CommandResult] = []
        self.next_popen: _FakePopen | None = None

    def run(
        self,
        args,
        *,
        cwd: str | None = None,
        env=None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        self.run_calls.append((tuple(args), cwd, timeout_seconds))
        if self.next_run_results:
            return self.next_run_results.pop(0)
        return CommandResult(args=tuple(args), exit_code=0, stdout="", stderr="", duration_seconds=0.0)

    def popen(
        self,
        args,
        *,
        cwd: str | None = None,
        env=None,
    ):
        self.popen_calls.append((tuple(args), cwd))
        assert self.next_popen is not None, "Test must set next_popen"
        return self.next_popen


class RemoteBridgeTests(unittest.TestCase):
    def test_ssh_and_scp_args_include_key_and_port(self) -> None:
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target)

        ssh_args = bridge.ssh_base_args()
        self.assertEqual(ssh_args[0], "ssh")
        self.assertIn("-i", ssh_args)
        self.assertTrue(any(str(arg).endswith("id_ed25519") for arg in ssh_args))
        self.assertIn("-p", ssh_args)
        self.assertIn("17126", ssh_args)
        self.assertIn("root@ssh4.vast.ai", ssh_args)

        scp_args = bridge.scp_base_args()
        self.assertEqual(scp_args[0], "scp")
        self.assertIn("-P", scp_args)
        self.assertIn("17126", scp_args)

    def test_build_remote_command_wraps_bash_and_cd(self) -> None:
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            remote_repo_root="/root/SeniorProject",
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target)

        remote = bridge.build_remote_command("echo hello", env={"FOO": "bar"})
        self.assertIn("bash -lc", remote)
        self.assertIn("cd /root/SeniorProject", remote)
        self.assertIn("export PYTHONUNBUFFERED=1", remote)
        self.assertIn("export FOO=bar", remote)
        self.assertIn("echo hello", remote)

    def test_run_uses_executor_and_constructs_ssh_command(self) -> None:
        fake = _FakeExecutor()
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target, executor=fake)

        fake.next_run_results.append(
            CommandResult(args=(), exit_code=0, stdout="skylink\n", stderr="", duration_seconds=0.01)
        )
        result = bridge.run("echo skylink", timeout_seconds=1.0)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(fake.run_calls), 1)
        args, _, _ = fake.run_calls[0]
        self.assertEqual(args[0], "ssh")
        self.assertTrue(args[-1].startswith("bash -lc"))

    def test_upload_file_runs_mkdir_then_scp(self) -> None:
        fake = _FakeExecutor()
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            remote_repo_root="/root/SeniorProject",
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target, executor=fake)

        with tempfile.TemporaryDirectory() as tmp:
            local_file = Path(tmp) / "mission.json"
            local_file.write_text('{"ok": true}\n', encoding="utf-8")

            remote_path = "/root/SeniorProject/artifacts/planner/job_cache/abc/mission.json"
            bridge.upload_file(local_file, remote_path, timeout_seconds=1.0)

        self.assertGreaterEqual(len(fake.run_calls), 2)
        self.assertEqual(fake.run_calls[0][0][0], "ssh")
        self.assertEqual(fake.run_calls[1][0][0], "scp")
        self.assertIn("root@ssh4.vast.ai:/root/SeniorProject/artifacts/planner/job_cache/abc/mission.json", fake.run_calls[1][0])

    def test_run_streaming_delivers_stdout_and_stderr(self) -> None:
        fake = _FakeExecutor()
        fake.next_popen = _FakePopen(
            stdout_text="out1\nout2\n",
            stderr_text="err1\n",
            exit_code=0,
            poll_code=0,
        )
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target, executor=fake)

        seen: list[tuple[str, str]] = []

        def _on_line(item) -> None:
            seen.append((item.kind.value, item.line))

        result = bridge.run_streaming("echo hi", on_line=_on_line, timeout_seconds=2.0)
        self.assertEqual(result.exit_code, 0)
        self.assertIn(("stdout", "out1"), seen)
        self.assertIn(("stdout", "out2"), seen)
        self.assertIn(("stderr", "err1"), seen)
        self.assertEqual(result.stdout, "out1\nout2")
        self.assertEqual(result.stderr, "err1")

    def test_run_streaming_times_out_and_terminates(self) -> None:
        fake = _FakeExecutor()
        fake.next_popen = _FakePopen(stdout_text="", stderr_text="", exit_code=0, poll_code=None)
        target = RemoteTarget(
            host="ssh4.vast.ai",
            port=17126,
            user="root",
            ssh_key_path=Path("deploy/backend/ssh/id_ed25519"),
            user_known_hosts_file="/dev/null",
        )
        bridge = RemoteExecutionBridge(target, executor=fake)

        with self.assertRaises(RemoteTimeoutError):
            bridge.run_streaming("sleep 999", timeout_seconds=0.05)
        self.assertTrue(fake.next_popen.terminated)


if __name__ == "__main__":
    unittest.main()
