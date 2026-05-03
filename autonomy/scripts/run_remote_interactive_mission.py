from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PX4_REPO = REPO_ROOT / "vendor" / "PX4-Autopilot"
SITL_LOG_DIR = REPO_ROOT / "artifacts" / "sitl_logs"
REMOTE_JOB_DIR = REPO_ROOT / "artifacts" / "remote_jobs"
TELEMETRY_PREFIX = "__TELEMETRY__"
READY_MARKERS = (
    "Startup script returned successfully",
    "Ready for takeoff!",
    "INFO  [mavlink] mode: Normal",
)


@dataclass
class ManagedProcess:
    process: subprocess.Popen[str]
    name: str
    log_path: Path


class ProcessRegistry:
    def __init__(self) -> None:
        self._processes: list[ManagedProcess] = []

    def add(self, managed: ManagedProcess) -> None:
        self._processes.append(managed)

    def shutdown(self) -> None:
        for managed in self._processes:
            if managed.process.poll() is None:
                with contextlib.suppress(Exception):
                    managed.process.terminate()
        time.sleep(2.0)
        for managed in self._processes:
            if managed.process.poll() is None:
                with contextlib.suppress(Exception):
                    managed.process.kill()
        subprocess.run(["pkill", "-x", "px4"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "[g]z sim"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "[m]ake px4_sitl"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "mavsdk_server"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "execute_interactive_mission.py"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "check_live_px4_snapshot.py"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reconfigure_stdout() -> None:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    with contextlib.suppress(Exception):
        sys.stderr.reconfigure(encoding="utf-8")


def _status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def _write_status(job_dir: Path, *, step: str, detail: str, ok: bool | None = None) -> None:
    payload: dict[str, object] = {
        "step": step,
        "detail": detail,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if ok is not None:
        payload["ok"] = ok
    job_dir.mkdir(parents=True, exist_ok=True)
    _status_path(job_dir).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[RUNNER] {step}: {detail}", flush=True)


def _stream_process_output(
    process: subprocess.Popen[str],
    *,
    label: str,
    log_path: Path,
    ready_event: threading.Event | None = None,
) -> threading.Thread:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _pump() -> None:
        with log_path.open("w", encoding="utf-8", errors="replace") as handle:
            assert process.stdout is not None
            for raw_line in process.stdout:
                handle.write(raw_line)
                handle.flush()
                line = raw_line.rstrip("\r\n")
                if line.startswith(TELEMETRY_PREFIX):
                    print(line, flush=True)
                else:
                    print(f"[{label}] {line}", flush=True)
                if ready_event is not None and any(marker in line for marker in READY_MARKERS):
                    ready_event.set()

    thread = threading.Thread(target=_pump, name=f"{label.lower()}-pump", daemon=True)
    thread.start()
    return thread


def _start_process(
    command: list[str],
    *,
    label: str,
    log_path: Path,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    ready_event: threading.Event | None = None,
) -> ManagedProcess:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        cwd=str(cwd or REPO_ROOT),
    )
    _stream_process_output(process, label=label, log_path=log_path, ready_event=ready_event)
    return ManagedProcess(process=process, name=label, log_path=log_path)


def _run_step(
    command: list[str],
    *,
    label: str,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> int:
    managed = _start_process(command, label=label, log_path=log_path, env=env)
    return managed.process.wait()


def _sitl_ready() -> bool:
    px4_running = subprocess.run(["pgrep", "-x", "px4"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    mavlink_ready = subprocess.run(
        ["bash", "-lc", "ss -lun | grep -q ':14580'"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    return px4_running and mavlink_ready


def _cleanup_stale_sitl() -> None:
    subprocess.run(["pkill", "-x", "px4"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "[g]z sim"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "[m]ake px4_sitl"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)


def _cleanup_stale_mavsdk_clients() -> None:
    subprocess.run(["pkill", "-9", "-f", "mavsdk_server"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "execute_interactive_mission.py"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "check_live_px4_snapshot.py"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)


def _start_sitl(job_dir: Path, registry: ProcessRegistry) -> None:
    if _sitl_ready():
        _write_status(job_dir, step="sitl", detail="Reusing existing PX4 SITL runtime", ok=True)
        return
    stale_px4 = subprocess.run(["pgrep", "-x", "px4"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if stale_px4:
        _write_status(job_dir, step="sitl", detail="Cleaning up stale PX4 SITL runtime before restart")
        _cleanup_stale_sitl()
    _write_status(job_dir, step="sitl", detail="Starting PX4 SITL on remote host")
    ready_event = threading.Event()
    env = os.environ.copy()
    env["HEADLESS"] = "1"
    env.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "0")
    managed = _start_process(
        ["bash", "-lc", "make px4_sitl gz_x500"],
        label="PX4",
        log_path=job_dir / "px4_runtime.log",
        env=env,
        cwd=PX4_REPO,
        ready_event=ready_event,
    )
    registry.add(managed)
    if not ready_event.wait(timeout=300.0):
        raise RuntimeError("Timed out waiting for PX4 SITL readiness markers.")

    # Poll for MAVLink readiness instead of a static sleep to avoid race conditions on remote hosts
    max_wait = 45.0
    start_wait = time.time()
    _write_status(job_dir, step="sitl", detail="PX4 process started, waiting for local MAVLink port 14580 to bind...")

    while (time.time() - start_wait) < max_wait:
        if _sitl_ready():
            _write_status(job_dir, step="sitl", detail="PX4 SITL ready with local UDP 14580 forwarding to 14540", ok=True)
            return
        time.sleep(1.5)

    raise RuntimeError(f"PX4 SITL started but local MAVLink port 14580 was not found after {max_wait}s.")


def _build_child_env(cpu_cores: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MAVSDK_SYSTEM_ADDRESS"] = "udpin://0.0.0.0:14540"
    env["LANDING_TARGET_DIRECT_PX4"] = "1"
    env["SKYLINK_EXECUTION_CPU_CORES"] = cpu_cores
    return env


def _sync_artifacts(job_dir: Path, python_executable: str) -> None:
    _write_status(job_dir, step="artifacts", detail="Building replay bundle and showcase")
    replay_code = _run_step(
        [python_executable, str(AUTONOMY_ROOT / "scripts" / "build_latest_replay_bundle.py")],
        label="REPLAY",
        log_path=job_dir / "replay_bundle.log",
        env=_build_child_env(""),
    )
    if replay_code != 0:
        raise RuntimeError(f"Replay bundle build failed with exit code {replay_code}.")
    showcase_code = _run_step(
        [python_executable, str(AUTONOMY_ROOT / "scripts" / "build_showcase.py")],
        label="SHOWCASE",
        log_path=job_dir / "showcase.log",
        env=_build_child_env(""),
    )
    if showcase_code != 0:
        raise RuntimeError(f"Showcase build failed with exit code {showcase_code}.")
    _write_status(job_dir, step="artifacts", detail="Replay bundle and showcase ready", ok=True)


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-spec", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--cpu-cores", default=os.environ.get("SKYLINK_EXECUTION_CPU_CORES", "2,3"))
    args = parser.parse_args(argv)

    registry = ProcessRegistry()
    job_dir = REMOTE_JOB_DIR / args.job_id
    SITL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    def _on_signal(signum: int, _frame) -> None:
        _write_status(job_dir, step="cancelled", detail=f"Received signal {signum}; shutting down.", ok=False)
        registry.shutdown()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    python_executable = sys.executable
    child_env = _build_child_env(args.cpu_cores)

    try:
        _write_status(job_dir, step="bootstrap", detail="Remote mission runner starting")
        _start_sitl(job_dir, registry)
        _write_status(job_dir, step="mission", detail="Cleaning stale MAVSDK clients before mission start")
        _cleanup_stale_mavsdk_clients()
        _write_status(job_dir, step="mission", detail=f"Executing mission spec {args.mission_spec.name}")
        mission_managed = _start_process(
            [
                python_executable,
                str(AUTONOMY_ROOT / "scripts" / "execute_interactive_mission.py"),
                "--mission-spec",
                str(args.mission_spec),
                "--cpu-cores",
                args.cpu_cores,
            ],
            label="MISSION",
            log_path=job_dir / "mission.log",
            env=child_env,
        )
        registry.add(mission_managed)
        mission_exit = mission_managed.process.wait()
        if mission_exit != 0:
            raise RuntimeError(f"Interactive mission execution failed with exit code {mission_exit}.")
        _sync_artifacts(job_dir, python_executable)
        _write_status(job_dir, step="complete", detail="Remote mission completed successfully", ok=True)
        return 0
    except Exception as exc:
        _write_status(job_dir, step="failed", detail=str(exc), ok=False)
        print(f"[RUNNER] failed: {exc}", flush=True)
        return 1
    finally:
        registry.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
