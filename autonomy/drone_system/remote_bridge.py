from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
import posixpath
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


class RemoteBridgeError(RuntimeError):
    """Base error for remote bridge failures."""


class RemoteTimeoutError(RemoteBridgeError):
    """Raised when a remote operation times out."""


class RemoteCommandError(RemoteBridgeError):
    """Raised when a remote command exits non-zero and check=True."""

    def __init__(self, message: str, *, exit_code: int, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class StreamKind(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"


@dataclass(frozen=True)
class RemoteStreamLine:
    kind: StreamKind
    line: str


@dataclass(frozen=True)
class RemoteTarget:
    host: str
    port: int
    user: str = "root"
    ssh_key_path: Path | None = None
    remote_repo_root: str = "/root/SeniorProject"
    strict_host_key_checking: bool = False
    user_known_hosts_file: str | None = None
    connect_timeout_seconds: int = 10
    extra_ssh_options: tuple[str, ...] = ()

    def destination(self) -> str:
        return f"{self.user}@{self.host}"

    def resolved_known_hosts_file(self) -> str:
        if self.user_known_hosts_file is not None:
            return self.user_known_hosts_file
        # Use OS-appropriate null device for the local OpenSSH client.
        return os.devnull


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class LocalCommandExecutor(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...

    def popen(
        self,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.Popen[str]: ...


class SubprocessExecutor:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        started_at = time.monotonic()
        try:
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                env=None if env is None else dict(env),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemoteTimeoutError(f"Command timed out after {timeout_seconds}s: {args}") from exc
        duration = time.monotonic() - started_at
        return CommandResult(
            args=tuple(args),
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=duration,
        )

    def popen(
        self,
        args: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        return subprocess.Popen(
            list(args),
            cwd=cwd,
            env=None if env is None else dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )


def _bash_script(
    command: str,
    *,
    cwd: str | None,
    env: Mapping[str, str] | None,
) -> str:
    lines: list[str] = ["set -e"]
    if env:
        for key, value in env.items():
            if not key:
                continue
            # Use shell escaping for values.
            lines.append(f"export {key}={shlex.quote(str(value))}")
    if cwd:
        lines.append(f"cd {shlex.quote(cwd)}")
    lines.append(command)
    return "\n".join(lines)


def _remote_bash_invocation(script: str) -> str:
    # Run using bash for predictable quoting/behavior.
    return f"bash -lc {shlex.quote(script)}"


def _posix_join(root: str, *parts: str) -> str:
    path = root
    for part in parts:
        if not part:
            continue
        path = posixpath.join(path, part)
    return path


def _is_ascii_text(value: str) -> bool:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _needs_ascii_staging(path: Path) -> bool:
    return not _is_ascii_text(str(path))


def _staging_root() -> Path:
    root = Path(tempfile.gettempdir()) / "skylink_bridge_xfer"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_staging_path(original: Path) -> Path:
    safe_stem = "".join(character if ord(character) < 128 and character not in '\\/:*?"<>|' else "_" for character in original.stem)
    safe_suffix = "".join(character if ord(character) < 128 and character not in '\\/:*?"<>|' else "_" for character in original.suffix)
    timestamp = f"{time.time_ns()}"
    return _staging_root() / f"{safe_stem}_{timestamp}{safe_suffix}"


@dataclass
class RemoteHealthStatus:
    ssh_ok: bool
    repo_ok: bool | None = None
    udp_ports: dict[int, bool] | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        if not self.ssh_ok:
            return False
        if self.repo_ok is False:
            return False
        if self.udp_ports and not all(self.udp_ports.values()):
            return False
        return True


class RemoteExecutionBridge:
    """
    SSH/SCP-based bridge for executing PX4 SITL workflows on a remote Linux host.

    This module is intentionally "dumb plumbing": it constructs commands, streams output,
    and moves files. Higher layers (mission_api) decide what to run and how to parse logs.
    """

    REMOTE_RUNTIME_SYNC_FILES: tuple[str, ...] = (
        "autonomy/drone_system/config.py",
        "autonomy/drone_system/safety_engine.py",
        "autonomy/drone_system/vehicle_interface.py",
        "autonomy/scripts/execute_interactive_mission.py",
        "autonomy/scripts/generate_synthetic_telemetry.py",
        "autonomy/scripts/run_remote_interactive_mission.py",
    )

    def __init__(
        self,
        target: RemoteTarget,
        *,
        executor: LocalCommandExecutor | None = None,
        local_cwd: Path | None = None,
        default_remote_cwd: str | None = None,
        remote_python_path: str | None = None,
        remote_runner_relative_path: str = "autonomy/scripts/run_remote_interactive_mission.py",
    ) -> None:
        self._target = target
        self._executor = executor or SubprocessExecutor()
        self._local_cwd = str(local_cwd) if local_cwd is not None else None
        self._default_remote_cwd = default_remote_cwd or target.remote_repo_root
        self._remote_python_path = remote_python_path or self.remote_path("autonomy", ".venv", "bin", "python")
        self._remote_runner_relative_path = remote_runner_relative_path

    @property
    def target(self) -> RemoteTarget:
        return self._target

    @property
    def target_label(self) -> str:
        return f"ssh://{self._target.destination()}:{self._target.port}{self._target.remote_repo_root}"

    @property
    def remote_python_path(self) -> str:
        return self._remote_python_path

    @property
    def remote_runner_path(self) -> str:
        return self.remote_path(*self._remote_runner_relative_path.split("/"))

    def remote_path(self, *parts: str) -> str:
        return _posix_join(self._target.remote_repo_root, *parts)

    def local_repo_root(self) -> Path:
        if self._local_cwd is not None:
            return Path(self._local_cwd)
        return Path.cwd()

    def ssh_base_args(self) -> list[str]:
        args = ["ssh"]
        if self._target.ssh_key_path is not None:
            args.extend(["-i", str(self._target.ssh_key_path)])
        args.extend(["-p", str(self._target.port)])
        args.extend(["-o", f"ConnectTimeout={int(self._target.connect_timeout_seconds)}"])
        if not self._target.strict_host_key_checking:
            args.extend(["-o", "StrictHostKeyChecking=no"])
            args.extend(["-o", f"UserKnownHostsFile={self._target.resolved_known_hosts_file()}"])
        for opt in self._target.extra_ssh_options:
            args.extend(["-o", opt])
        args.append(self._target.destination())
        return args

    def scp_base_args(self) -> list[str]:
        args = ["scp"]
        if self._target.ssh_key_path is not None:
            args.extend(["-i", str(self._target.ssh_key_path)])
        args.extend(["-P", str(self._target.port)])
        if not self._target.strict_host_key_checking:
            args.extend(["-o", "StrictHostKeyChecking=no"])
            args.extend(["-o", f"UserKnownHostsFile={self._target.resolved_known_hosts_file()}"])
        for opt in self._target.extra_ssh_options:
            args.extend(["-o", opt])
        return args

    def build_remote_command(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        effective_cwd = self._default_remote_cwd if cwd is None else cwd
        effective_env: dict[str, str] = {}
        effective_env["PYTHONUNBUFFERED"] = "1"
        if env:
            effective_env.update({str(k): str(v) for k, v in env.items()})
        script = _bash_script(command, cwd=effective_cwd, env=effective_env)
        return _remote_bash_invocation(script)

    def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = 30.0,
        check: bool = False,
    ) -> CommandResult:
        remote = self.build_remote_command(command, cwd=cwd, env=env)
        args = [*self.ssh_base_args(), remote]
        result = self._executor.run(args, cwd=self._local_cwd, timeout_seconds=timeout_seconds)
        if check and result.exit_code != 0:
            raise RemoteCommandError(
                f"Remote command failed with exit code {result.exit_code}.",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def open(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        remote = self.build_remote_command(command, cwd=cwd, env=env)
        args = [*self.ssh_base_args(), remote]
        return self._executor.popen(args, cwd=self._local_cwd)

    def run_streaming(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        on_line: Callable[[RemoteStreamLine], None] | None = None,
        check: bool = False,
    ) -> CommandResult:
        remote = self.build_remote_command(command, cwd=cwd, env=env)
        args = [*self.ssh_base_args(), remote]

        started_at = time.monotonic()
        process = self._executor.popen(args, cwd=self._local_cwd)
        q: queue.Queue[RemoteStreamLine | None] = queue.Queue()

        stdout_capture: list[str] = []
        stderr_capture: list[str] = []

        def _reader(kind: StreamKind, stream) -> None:
            try:
                for raw_line in stream:
                    line = str(raw_line).rstrip("\r\n")
                    q.put(RemoteStreamLine(kind=kind, line=line))
            finally:
                q.put(None)

        assert process.stdout is not None
        assert process.stderr is not None
        threads = [
            threading.Thread(target=_reader, args=(StreamKind.STDOUT, process.stdout), daemon=True),
            threading.Thread(target=_reader, args=(StreamKind.STDERR, process.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()

        sentinels_seen = 0
        while True:
            if timeout_seconds is not None and (time.monotonic() - started_at) > timeout_seconds:
                try:
                    process.terminate()
                except Exception:
                    pass
                raise RemoteTimeoutError(f"Remote streaming command timed out after {timeout_seconds}s.")

            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None and sentinels_seen >= 2:
                    break
                continue

            if item is None:
                sentinels_seen += 1
                if process.poll() is not None and sentinels_seen >= 2:
                    break
                continue

            if item.kind == StreamKind.STDOUT:
                stdout_capture.append(item.line)
            else:
                stderr_capture.append(item.line)
            if on_line is not None:
                on_line(item)

        exit_code = process.wait()
        duration = time.monotonic() - started_at
        result = CommandResult(
            args=tuple(args),
            exit_code=int(exit_code),
            stdout="\n".join(stdout_capture).strip(),
            stderr="\n".join(stderr_capture).strip(),
            duration_seconds=duration,
        )
        if check and result.exit_code != 0:
            raise RemoteCommandError(
                f"Remote command failed with exit code {result.exit_code}.",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        *,
        timeout_seconds: float | None = 60.0,
        ensure_remote_parent: bool = True,
        check: bool = True,
    ) -> CommandResult:
        local_path = local_path.resolve()
        staged_path: Path | None = None
        source_path = local_path
        if _needs_ascii_staging(local_path):
            staged_path = _make_staging_path(local_path)
            shutil.copy2(local_path, staged_path)
            source_path = staged_path
        if ensure_remote_parent:
            parent = posixpath.dirname(remote_path)
            if parent:
                self.run(f"mkdir -p {shlex.quote(parent)}", timeout_seconds=timeout_seconds, check=True)
        try:
            args = [*self.scp_base_args(), str(source_path), f"{self._target.destination()}:{remote_path}"]
            result = self._executor.run(args, cwd=self._local_cwd, timeout_seconds=timeout_seconds)
            if check and result.exit_code != 0:
                raise RemoteCommandError(
                    f"SCP upload failed with exit code {result.exit_code}.",
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            return result
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)

    def download_file(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout_seconds: float | None = 60.0,
        ensure_local_parent: bool = True,
        check: bool = True,
    ) -> CommandResult:
        local_path = local_path.resolve()
        staged_path: Path | None = None
        target_path = local_path
        if _needs_ascii_staging(local_path):
            staged_path = _make_staging_path(local_path)
            target_path = staged_path
        if ensure_local_parent:
            local_path.parent.mkdir(parents=True, exist_ok=True)
        args = [*self.scp_base_args(), f"{self._target.destination()}:{remote_path}", str(target_path)]
        result = self._executor.run(args, cwd=self._local_cwd, timeout_seconds=timeout_seconds)
        if check and result.exit_code != 0:
            raise RemoteCommandError(
                f"SCP download failed with exit code {result.exit_code}.",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if staged_path is not None and staged_path.exists():
            if local_path.exists():
                local_path.unlink()
            shutil.move(str(staged_path), str(local_path))
        return result

    def download_path(
        self,
        remote_path: str,
        local_path: Path,
        *,
        recursive: bool = False,
        timeout_seconds: float | None = 120.0,
        check: bool = True,
    ) -> CommandResult:
        local_path = local_path.resolve()
        staged_parent: Path | None = None
        target_dir = local_path
        if _needs_ascii_staging(local_path):
            staged_parent = _staging_root() / f"download_{time.time_ns()}"
            staged_parent.mkdir(parents=True, exist_ok=True)
            target_dir = staged_parent
        if recursive:
            local_path.mkdir(parents=True, exist_ok=True)
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
        args = self.scp_base_args()
        if recursive:
            args.append("-r")
        args.extend([f"{self._target.destination()}:{remote_path}", str(target_dir)])
        result = self._executor.run(args, cwd=self._local_cwd, timeout_seconds=timeout_seconds)
        if check and result.exit_code != 0:
            raise RemoteCommandError(
                f"SCP download failed with exit code {result.exit_code}.",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        if staged_parent is not None:
            remote_name = Path(posixpath.basename(remote_path.rstrip("/"))).name
            staged_download = staged_parent / remote_name
            destination = local_path / remote_name if recursive else local_path
            if staged_download.exists():
                if staged_download.is_dir():
                    shutil.copytree(staged_download, destination, dirs_exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(staged_download, destination)
            shutil.rmtree(staged_parent, ignore_errors=True)
        return result

    def health_check(
        self,
        *,
        udp_ports: Sequence[int] = (),
        timeout_seconds: float = 8.0,
    ) -> RemoteHealthStatus:
        # Bounded SSH probe. Keep it minimal and non-destructive.
        try:
            probe = self.run("echo skylink_bridge_ok", timeout_seconds=timeout_seconds, check=True)
        except RemoteBridgeError as exc:
            return RemoteHealthStatus(ssh_ok=False, message=str(exc), udp_ports={p: False for p in udp_ports})

        ssh_ok = probe.exit_code == 0 and "skylink_bridge_ok" in probe.stdout
        if not ssh_ok:
            return RemoteHealthStatus(ssh_ok=False, message="SSH probe failed.", udp_ports={p: False for p in udp_ports})

        repo_ok: bool | None = None
        udp_status: dict[int, bool] = {}

        try:
            repo_probe = self.run(
                f"test -d {shlex.quote(self._target.remote_repo_root)} && echo repo_ok",
                timeout_seconds=timeout_seconds,
                check=True,
            )
            repo_ok = "repo_ok" in repo_probe.stdout
        except RemoteBridgeError:
            repo_ok = None

        for port in udp_ports:
            udp_status[int(port)] = self.is_udp_port_listening(int(port), timeout_seconds=timeout_seconds)

        return RemoteHealthStatus(
            ssh_ok=True,
            repo_ok=repo_ok,
            udp_ports=udp_status if udp_ports else None,
            message="ok",
        )

    def is_udp_port_listening(self, port: int, *, timeout_seconds: float = 6.0) -> bool:
        # UDP "liveness" is best-effort: check for a bound socket.
        # Avoid assuming netcat exists. 'ss' should exist on Ubuntu.
        regex = f":{int(port)}\\b"
        cmd = f"ss -lunp | grep -E {shlex.quote(regex)} >/dev/null 2>&1 && echo listening || echo not_listening"
        try:
            result = self.run(cmd, timeout_seconds=timeout_seconds, check=True)
        except RemoteBridgeError:
            return False
        return "listening" in result.stdout

    def cancel_remote_processes(
        self,
        patterns: Sequence[str],
        *,
        timeout_seconds: float = 15.0,
        grace_seconds: float = 2.0,
        force: bool = True,
    ) -> CommandResult:
        if not patterns:
            return self.run("echo no_patterns", timeout_seconds=timeout_seconds, check=True)

        lines: list[str] = []
        for pattern in patterns:
            lines.append(f"pkill -TERM -f {shlex.quote(pattern)} || true")
        if force:
            lines.append(f"sleep {float(grace_seconds):.3f} || true")
            for pattern in patterns:
                lines.append(f"pkill -KILL -f {shlex.quote(pattern)} || true")
        return self.run("\n".join(lines), timeout_seconds=timeout_seconds, check=False)

    def cleanup_px4_sitl(self, *, timeout_seconds: float = 20.0) -> CommandResult:
        # Conservative cleanup for the common PX4/Gazebo SITL stack on remote Linux.
        return self.cancel_remote_processes(
            patterns=(
                "make px4_sitl",
                "px4 -i",
                "px4",
                "gz sim",
                "MicroXRCEAgent",
                "micrortps_agent",
            ),
            timeout_seconds=timeout_seconds,
            grace_seconds=2.0,
            force=True,
        )

    def check_status(self) -> dict[str, Any]:
        probe = self.health_check(udp_ports=(14580,), timeout_seconds=float(self._target.connect_timeout_seconds))
        unavailable = {
            "configured": True,
            "reachable": probe.ssh_ok,
            "status": "unavailable",
            "status_label": "Remote Unavailable",
            "detail": probe.message or "Remote execution host is not reachable.",
            "target": self._target.destination(),
            "target_label": self.target_label,
            "repo_root": self._target.remote_repo_root,
            "repo_present": False,
            "venv_present": False,
            "runner_present": False,
            "px4_binary_present": False,
            "sitl_running": False,
            "mavlink_ready": False,
            "gpu_name": "",
            "ready_for_remote_execution": False,
        }
        if not probe.ssh_ok:
            return unavailable

        command = """
python3 - <<'PY'
import json
import os
import subprocess

repo_root = os.environ["SKYLINK_REMOTE_REPO_ROOT"]
runner_path = os.environ["SKYLINK_REMOTE_RUNNER_PATH"]
python_path = os.environ["SKYLINK_REMOTE_PYTHON"]
px4_binary = os.path.join(repo_root, "vendor", "PX4-Autopilot", "build", "px4_sitl_default", "bin", "px4")

def sh(command: str) -> bool:
    return subprocess.run(
        command,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

gpu_name = ""
try:
    gpu_name = subprocess.check_output(
        ["bash", "-lc", "nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
except Exception:
    gpu_name = ""

payload = {
    "repo_present": os.path.isdir(repo_root),
    "venv_present": os.path.exists(python_path),
    "runner_present": os.path.exists(runner_path),
    "px4_binary_present": os.path.exists(px4_binary),
    "sitl_running": sh("pgrep -x px4 >/dev/null 2>&1"),
    "mavlink_ready": sh("ss -lun | grep -q ':14580'"),
    "gpu_name": gpu_name,
}
print(json.dumps(payload))
PY
"""
        try:
            result = self.run(
                command,
                cwd="/",
                env={
                    "SKYLINK_REMOTE_REPO_ROOT": self._target.remote_repo_root,
                    "SKYLINK_REMOTE_RUNNER_PATH": self.remote_runner_path,
                    "SKYLINK_REMOTE_PYTHON": self.remote_python_path,
                },
                timeout_seconds=max(8.0, float(self._target.connect_timeout_seconds)),
                check=True,
            )
            payload = json.loads(result.stdout.strip() or "{}")
        except (RemoteBridgeError, json.JSONDecodeError):
            return unavailable

        repo_present = bool(payload.get("repo_present", False))
        venv_present = bool(payload.get("venv_present", False))
        runner_present = bool(payload.get("runner_present", False))
        px4_binary_present = bool(payload.get("px4_binary_present", False))
        sitl_running = bool(payload.get("sitl_running", False))
        mavlink_ready = bool(payload.get("mavlink_ready", False))
        gpu_name = str(payload.get("gpu_name", "") or "")
        ready = repo_present and venv_present and runner_present and px4_binary_present

        status = "ready" if ready else "degraded"
        status_label = "Remote Ready" if ready else "Remote Degraded"
        detail_parts: list[str] = []
        if not repo_present:
            detail_parts.append("repo missing")
        if not venv_present:
            detail_parts.append("venv missing")
        if not runner_present:
            detail_parts.append("runner missing")
        if not px4_binary_present:
            detail_parts.append("px4 binary missing")
        if ready and not sitl_running:
            detail_parts.append("sitl idle")
        if ready and sitl_running and not mavlink_ready:
            detail_parts.append("udp 14580 not ready")
        if gpu_name:
            detail_parts.append(gpu_name)

        return {
            "configured": True,
            "reachable": True,
            "status": status,
            "status_label": status_label,
            "detail": ", ".join(detail_parts) if detail_parts else "Remote execution host ready.",
            "target": self._target.destination(),
            "target_label": self.target_label,
            "repo_root": self._target.remote_repo_root,
            "repo_present": repo_present,
            "venv_present": venv_present,
            "runner_present": runner_present,
            "px4_binary_present": px4_binary_present,
            "sitl_running": sitl_running,
            "mavlink_ready": mavlink_ready,
            "gpu_name": gpu_name,
            "ready_for_remote_execution": ready,
        }

    def upload_mission_spec(self, local_spec_path: Path, *, job_id: str) -> str:
        remote_dir = self.remote_path("artifacts", "remote_jobs", job_id)
        remote_spec_path = posixpath.join(remote_dir, "mission_request.json")
        self.upload_file(local_spec_path, remote_spec_path, timeout_seconds=60.0, ensure_remote_parent=True, check=True)
        return remote_spec_path

    def sync_runtime_sources(self) -> None:
        local_repo_root = self.local_repo_root()
        for relative_path in self.REMOTE_RUNTIME_SYNC_FILES:
            local_path = (local_repo_root / Path(relative_path)).resolve()
            if not local_path.exists():
                continue
            remote_path = self.remote_path(*Path(relative_path).parts)
            self.upload_file(
                local_path,
                remote_path,
                timeout_seconds=120.0,
                ensure_remote_parent=True,
                check=True,
            )

    def start_remote_mission_process(
        self,
        remote_spec_path: str,
        *,
        job_id: str,
        cpu_cores: str,
    ) -> subprocess.Popen[str]:
        self.sync_runtime_sources()
        command = " ".join(
            [
                shlex.quote(self.remote_python_path),
                shlex.quote(self.remote_runner_path),
                "--mission-spec",
                shlex.quote(remote_spec_path),
                "--job-id",
                shlex.quote(job_id),
                "--cpu-cores",
                shlex.quote(cpu_cores),
            ]
        )
        return self.open(
            command,
            cwd=self._target.remote_repo_root,
            env={
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )

    def cancel_remote_job(self, job_id: str) -> None:
        self.cancel_remote_processes(
            patterns=(
                f"run_remote_interactive_mission.py --job-id {job_id}",
                f"execute_interactive_mission.py --mission-spec .*{job_id}",
                "run_remote_interactive_mission.py",
                "execute_interactive_mission.py",
                "make px4_sitl",
                "px4",
                "gz sim",
            ),
            timeout_seconds=20.0,
            grace_seconds=2.0,
            force=True,
        )

    def download_artifacts(self, *, local_repo_root: Path) -> None:
        local_repo_root = local_repo_root.resolve()
        downloads = (
            (self.remote_path("artifacts", "showcase", "latest"), local_repo_root / "artifacts" / "showcase"),
            (self.remote_path("artifacts", "replay_bundle", "latest"), local_repo_root / "artifacts" / "replay_bundle"),
            (self.remote_path("artifacts", "live_px4"), local_repo_root / "artifacts"),
        )
        for remote_path, local_path in downloads:
            self.download_path(remote_path, local_path, recursive=True, timeout_seconds=180.0, check=False)


def remote_bridge_from_env(repo_root: Path) -> RemoteExecutionBridge | None:
    host = os.environ.get("SKYLINK_REMOTE_SSH_HOST", "").strip()
    if not host:
        return None
    port = int(os.environ.get("SKYLINK_REMOTE_SSH_PORT", "22"))
    user = os.environ.get("SKYLINK_REMOTE_SSH_USER", "root").strip() or "root"
    remote_repo_root = os.environ.get("SKYLINK_REMOTE_REPO_ROOT", "/root/SeniorProject").strip() or "/root/SeniorProject"
    connect_timeout_seconds = int(os.environ.get("SKYLINK_REMOTE_CONNECT_TIMEOUT_S", "10"))
    key_path_raw = os.environ.get("SKYLINK_REMOTE_IDENTITY_PATH", "").strip()
    ssh_key_path = Path(key_path_raw) if key_path_raw else repo_root / "deploy" / "backend" / "ssh" / "id_ed25519"
    user_known_hosts_file = os.environ.get("SKYLINK_REMOTE_USER_KNOWN_HOSTS_FILE", os.devnull)
    remote_python_path = os.environ.get(
        "SKYLINK_REMOTE_PYTHON",
        posixpath.join(remote_repo_root, "autonomy", ".venv", "bin", "python"),
    )
    remote_runner_relative_path = os.environ.get(
        "SKYLINK_REMOTE_RUNNER_PATH",
        "autonomy/scripts/run_remote_interactive_mission.py",
    ).strip() or "autonomy/scripts/run_remote_interactive_mission.py"
    target = RemoteTarget(
        host=host,
        port=port,
        user=user,
        ssh_key_path=ssh_key_path,
        remote_repo_root=remote_repo_root,
        strict_host_key_checking=False,
        user_known_hosts_file=user_known_hosts_file,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    return RemoteExecutionBridge(
        target,
        local_cwd=repo_root,
        remote_python_path=remote_python_path,
        remote_runner_relative_path=remote_runner_relative_path,
    )
