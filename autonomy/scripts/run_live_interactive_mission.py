from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.interactive_mission import interactive_mission_spec_from_dict
from autonomy.drone_system.px4_sim_overrides import build_px4_sim_override_plan, write_generated_gz_world
from autonomy.drone_system.runtime_affinity import enforce_cpu_affinity, parse_cpu_cores

VENV_PYTHON = AUTONOMY_ROOT / ".venv" / "Scripts" / "python.exe"
PX4_REPO = REPO_ROOT / "vendor" / "PX4-Autopilot"
BRIDGE_SCRIPT = AUTONOMY_ROOT / "scripts" / "wsl_mavlink_bridge.py"
VALIDATOR_SCRIPT = AUTONOMY_ROOT / "scripts" / "execute_interactive_mission.py"
REPLAY_SCRIPT = AUTONOMY_ROOT / "scripts" / "build_latest_replay_bundle.py"
SHOWCASE_SCRIPT = AUTONOMY_ROOT / "scripts" / "build_showcase.py"
DASHBOARD_SCRIPT = AUTONOMY_ROOT / "scripts" / "build_dashboard.py"
SITL_LOG_DIR = REPO_ROOT / "artifacts" / "sitl_logs"
GENERATED_WORLD_DIR = REPO_ROOT / "artifacts" / "generated_worlds"
WIND_TEMPLATE_PATH = PX4_REPO / "Tools" / "simulation" / "gz" / "worlds" / "windy.sdf"
GZ_ENV_PATH = PX4_REPO / "build" / "px4_sitl_default" / "rootfs" / "gz_env.sh"
TELEMETRY_PREFIX = "__TELEMETRY__"

READY_MARKERS = (
    "Startup script returned successfully",
    "Ready for takeoff",
    "INFO  [commander] home set",
    "INFO  [tone_alarm] home set",
    "INFO  [mavlink] mode: Normal",
)


def _windows_to_wsl_path(path: Path) -> str:
    drive = path.drive.rstrip(":").lower()
    relative = path.as_posix().split(":/", 1)[1]
    return f"/mnt/{drive}/{relative}"


def _kill_stale_mavsdk_server() -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process mavsdk_server -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


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
                line = raw_line.rstrip("\r\n")
                handle.write(raw_line)
                handle.flush()
                print(f"[{label}] {line}", flush=True)
                if ready_event is not None and any(marker in line for marker in READY_MARKERS):
                    ready_event.set()

    thread = threading.Thread(target=_pump, name=f"{label.lower()}-pump", daemon=True)
    thread.start()
    return thread


def _run_step(
    command: list[str],
    *,
    label: str,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    cpu_cores: list[int] | None = None,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(REPO_ROOT),
    )
    if cpu_cores:
        enforce_cpu_affinity(cpu_cores, pid=process.pid, label=label.lower())
    assert process.stdout is not None
    log_handle = log_path.open("w", encoding="utf-8", errors="replace") if log_path is not None else None
    try:
        for raw_line in process.stdout:
            if log_handle is not None:
                log_handle.write(raw_line)
                log_handle.flush()
            line = raw_line.rstrip()
            if line.startswith(TELEMETRY_PREFIX):
                print(line, flush=True)
            else:
                print(f"[{label}] {line}", flush=True)
    finally:
        if log_handle is not None:
            log_handle.close()
    exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError(f"{label} exited with code {exit_code}.")


def _cleanup_process(process: subprocess.Popen[str] | None, *, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    print(f"[{name}] terminated", flush=True)


def _wsl_cleanup_px4() -> None:
    cleanup_command = (
        "pkill -f 'px4_sitl_default/bin/px4' 2>/dev/null || true; "
        "pkill -f '/bin/px4' 2>/dev/null || true; "
        "pkill -f 'gz sim' 2>/dev/null || true; "
        "pkill -f 'make px4_sitl' 2>/dev/null || true"
    )
    subprocess.run(
        ["wsl", "bash", "-lc", cleanup_command],
        check=False,
        capture_output=True,
        text=True,
    )


def _wait_for_world_ready(world_name: str, *, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        result = subprocess.run(
            [
                "wsl",
                "bash",
                "-lc",
                f"gz service -i --service /world/{world_name}/scene/info",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if "Service providers" in result.stdout:
            return
        time.sleep(1.0)
    raise RuntimeError(f"Gazebo world {world_name} did not become ready within {timeout_s:.0f} seconds.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-spec", required=True, type=Path)
    parser.add_argument("--model", default="gz_x500")
    parser.add_argument("--world", default="")
    parser.add_argument("--cpu-cores", default=os.environ.get("SKYLINK_EXECUTION_CPU_CORES", "2,3"))
    args = parser.parse_args()
    execution_cpu_cores = parse_cpu_cores(args.cpu_cores, default=[2, 3])

    if not VENV_PYTHON.exists():
        raise RuntimeError(f"Expected Windows autonomy venv python at {VENV_PYTHON}")
    if not args.mission_spec.exists():
        raise RuntimeError(f"Mission spec not found: {args.mission_spec}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    baseline = load_system_baseline()
    spec = interactive_mission_spec_from_dict(
        json.loads(args.mission_spec.read_text(encoding="utf-8-sig")),
        baseline,
    )
    override_plan = build_px4_sim_override_plan(spec, baseline)
    world_name = f"skylink_live_{timestamp.lower()}"
    generated_world = write_generated_gz_world(
        template_path=WIND_TEMPLATE_PATH,
        output_dir=GENERATED_WORLD_DIR,
        world_name=world_name,
        wind_vector_enu_mps=override_plan.wind_vector_enu_mps,
    )

    sitl_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}.log"
    world_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_world.log"
    bridge_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_bridge.log"
    validator_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_validator.log"
    replay_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_replay.log"
    showcase_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_showcase.log"
    dashboard_log_path = SITL_LOG_DIR / f"interactive_mission_{timestamp}_dashboard.log"

    _kill_stale_mavsdk_server()
    _wsl_cleanup_px4()

    px4_repo_wsl = _windows_to_wsl_path(PX4_REPO)
    bridge_script_wsl = _windows_to_wsl_path(BRIDGE_SCRIPT)
    generated_world_wsl = _windows_to_wsl_path(generated_world)
    gz_env_wsl = _windows_to_wsl_path(GZ_ENV_PATH)
    wsl_command = f"cd {px4_repo_wsl}; . {gz_env_wsl}; "
    if args.world:
        wsl_command += f"env HEADLESS=1 PX4_GZ_WORLD={args.world} make px4_sitl {args.model}"
    else:
        wsl_command += f"env HEADLESS=1 PX4_GZ_STANDALONE=1 PX4_GZ_WORLD={world_name} make px4_sitl {args.model}"

    print(
        "[RUNNER] simulator overrides "
        f"weather_profile_mode={override_plan.weather_profile_mode} "
        f"wind_speed_mps={override_plan.wind_speed_mps:.1f} "
        f"wind_direction_deg={override_plan.wind_direction_deg:.1f} "
        f"gust_multiplier={override_plan.gust_multiplier:.2f} "
        f"low_battery_action={override_plan.low_battery_action} "
        f"world={generated_world.name}",
        flush=True,
    )

    world_process = None
    world_thread = None
    if not args.world:
        print("[RUNNER] launching generated Gazebo world", flush=True)
        world_process = subprocess.Popen(
            [
                "wsl",
                "bash",
                "-lc",
                f". {gz_env_wsl}; HEADLESS=1 gz sim --verbose=1 -r -s {generated_world_wsl}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
        )
        enforce_cpu_affinity(execution_cpu_cores, pid=world_process.pid, label="world")
        world_thread = _stream_process_output(
            world_process,
            label="WORLD",
            log_path=world_log_path,
        )
        _wait_for_world_ready(world_name)
        print(f"[RUNNER] Gazebo world ready: {world_name}", flush=True)

    print("[RUNNER] launching PX4 SITL", flush=True)
    sitl_ready_event = threading.Event()
    sitl_process = subprocess.Popen(
        ["wsl", "bash", "-lc", wsl_command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(REPO_ROOT),
    )
    enforce_cpu_affinity(execution_cpu_cores, pid=sitl_process.pid, label="sitl")
    sitl_thread = _stream_process_output(
        sitl_process,
        label="SITL",
        log_path=sitl_log_path,
        ready_event=sitl_ready_event,
    )

    print("[RUNNER] launching WSL MAVLink bridge", flush=True)
    bridge_process = subprocess.Popen(
        ["wsl", "bash", "-lc", f"python3 {bridge_script_wsl}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(REPO_ROOT),
    )
    enforce_cpu_affinity(execution_cpu_cores, pid=bridge_process.pid, label="bridge")
    bridge_thread = _stream_process_output(
        bridge_process,
        label="BRIDGE",
        log_path=bridge_log_path,
    )

    try:
        deadline = time.time() + 300
        while not sitl_ready_event.is_set():
            if sitl_process.poll() is not None:
                raise RuntimeError(f"PX4 SITL exited early with code {sitl_process.returncode}.")
            if time.time() >= deadline:
                raise RuntimeError("PX4 SITL did not report readiness within 300 seconds.")
            time.sleep(1.0)

        print("[RUNNER] PX4 SITL ready, starting validator", flush=True)
        env = os.environ.copy()
        env["LIVE_PX4_SITL_LOG_PATH"] = str(sitl_log_path)
        env["LIVE_PX4_BRIDGE_LOG_PATH"] = str(bridge_log_path)
        _run_step(
            [
                str(VENV_PYTHON),
                str(VALIDATOR_SCRIPT),
                "--mission-spec",
                str(args.mission_spec),
                "--cpu-cores",
                ",".join(str(core) for core in execution_cpu_cores),
            ],
            label="VALIDATOR",
            env=env,
            log_path=validator_log_path,
            cpu_cores=execution_cpu_cores,
        )

        print("[RUNNER] building replay bundle", flush=True)
        _run_step([str(VENV_PYTHON), str(REPLAY_SCRIPT)], label="REPLAY", log_path=replay_log_path)
        print("[RUNNER] building showcase", flush=True)
        _run_step([str(VENV_PYTHON), str(SHOWCASE_SCRIPT)], label="SHOWCASE", log_path=showcase_log_path)
        print("[RUNNER] building dashboard", flush=True)
        _run_step([str(VENV_PYTHON), str(DASHBOARD_SCRIPT)], label="DASHBOARD", log_path=dashboard_log_path)

        print(
            f"[RUNNER] completed showcase={REPO_ROOT / 'artifacts' / 'showcase' / 'latest' / 'index.html'}",
            flush=True,
        )
    finally:
        _cleanup_process(bridge_process, name="BRIDGE")
        _cleanup_process(sitl_process, name="SITL")
        _cleanup_process(world_process, name="WORLD")
        _wsl_cleanup_px4()
        sitl_thread.join(timeout=2)
        bridge_thread.join(timeout=2)
        if world_thread is not None:
            world_thread.join(timeout=2)


if __name__ == "__main__":
    main()
