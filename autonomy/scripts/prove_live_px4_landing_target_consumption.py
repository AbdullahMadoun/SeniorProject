from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

try:
    from pyulog import ULog  # type: ignore
except Exception:  # pragma: no cover
    ULog = None  # type: ignore[assignment]

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_proof import (
    count_bridge_direction,
    extract_ulog_relative_path,
    parse_receiver_observation,
)
from autonomy.drone_system.landing_target_stream import (
    LandingTargetPublisher,
    connection_string_for_endpoint,
    build_stationary_landing_target_samples,
    mavutil,
    observer_connection_string_for_endpoint,
    sample_to_dict,
)


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_landing_target_consumption.json"
SITL_LOG_DIR = REPO_ROOT / "artifacts" / "sitl_logs"
PX4_REPO = REPO_ROOT / "vendor" / "PX4-Autopilot"
PX4_REPO_WSL = "/mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot"
BRIDGE_SCRIPT_WSL = "/mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/wsl_mavlink_bridge.py"
LANDING_TARGET_ENDPOINT = "gcs"
SUPPORTED_HOST_MODES = {"wsl", "linux"}
SITL_MODEL = "gz_x500"
STARTUP_TIMEOUT_S = 180
DEFAULT_DURATION_S = 5.0
DEFAULT_RATE_HZ = 10.0
OBSERVER_TIMEOUT_S = 10.0
COLLECTION_WINDOW_S = 8.0


class ManagedProcess:
    def __init__(self, process: subprocess.Popen[bytes], log_handle) -> None:
        self.process = process
        self.log_handle = log_handle

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log_handle.close()


def use_direct_px4_transport() -> bool:
    raw = os.environ.get("LANDING_TARGET_DIRECT_PX4")
    if raw is not None and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return resolve_host_mode() == "linux"


def resolve_host_mode() -> str:
    raw = os.environ.get("SKYLINK_PX4_HOST_MODE", "").strip().lower()
    if raw:
        if raw not in SUPPORTED_HOST_MODES:
            valid = ", ".join(sorted(SUPPORTED_HOST_MODES))
            raise SystemExit(f"Unsupported SKYLINK_PX4_HOST_MODE '{raw}'. Valid values: {valid}.")
        return raw
    return "wsl" if os.name == "nt" else "linux"


def run_shell(command: str, *, host_mode: str) -> subprocess.CompletedProcess[str]:
    launcher = ["bash", "-lc", command] if host_mode == "linux" else ["wsl", "bash", "-lc", command]
    return subprocess.run(
        launcher,
        capture_output=True,
        text=True,
        check=False,
    )


def detect_wsl_bridge_ip(*, host_mode: str) -> str | None:
    if host_mode != "wsl":
        return None
    result = run_shell("hostname -I | awk '{print $1}'", host_mode=host_mode)
    bridge_ip = result.stdout.strip()
    if result.returncode != 0 or not bridge_ip:
        return None
    return bridge_ip


def start_shell_process(command: str, log_path: Path, *, host_mode: str) -> ManagedProcess:
    launcher = ["bash", "-lc", command] if host_mode == "linux" else ["wsl", "bash", "-lc", command]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        launcher,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return ManagedProcess(process, log_handle)


def shell_quote_path(path: Path | str) -> str:
    return shlex.quote(str(path))


def px4_repo_shell_path(*, host_mode: str) -> str:
    if host_mode == "wsl":
        return PX4_REPO_WSL
    return str(PX4_REPO)


def bridge_script_shell_path(*, host_mode: str) -> str | None:
    if host_mode != "wsl":
        return None
    return BRIDGE_SCRIPT_WSL


def cleanup_runtime_processes(*, host_mode: str) -> None:
    px4_binary_path = (
        f"{px4_repo_shell_path(host_mode=host_mode)}/build/px4_sitl_default/bin/px4"
        if host_mode == "wsl"
        else str(PX4_REPO / "build" / "px4_sitl_default" / "bin" / "px4")
    )
    commands = [
        f"pkill -f {shell_quote_path(px4_binary_path)} || true",
        "pkill -f 'make px4_sitl' || true",
    ]
    bridge_script = bridge_script_shell_path(host_mode=host_mode)
    if bridge_script:
        commands.append(f"pkill -f {shell_quote_path(bridge_script)} || true")
    run_shell(" && ".join(commands), host_mode=host_mode)


def start_sitl_process(log_path: Path, *, host_mode: str) -> ManagedProcess:
    px4_repo = px4_repo_shell_path(host_mode=host_mode)
    command = f"cd {shell_quote_path(px4_repo)} && HEADLESS=1 make px4_sitl {SITL_MODEL}"
    return start_shell_process(command, log_path, host_mode=host_mode)


def start_bridge_process(log_path: Path, *, host_mode: str) -> ManagedProcess | None:
    bridge_script = bridge_script_shell_path(host_mode=host_mode)
    if bridge_script is None:
        return None
    command = f"python3 {shell_quote_path(bridge_script)}"
    return start_shell_process(command, log_path, host_mode=host_mode)


def default_observer_connection_string(*, endpoint: str, direct_px4: bool) -> str:
    return observer_connection_string_for_endpoint(endpoint, direct_px4=direct_px4)


def default_publisher_connection_string(*, endpoint: str, direct_px4: bool, bridge_ip: str | None) -> str:
    return connection_string_for_endpoint(endpoint, bridge_ip=bridge_ip, direct_px4=direct_px4)


def wait_for_sitl_ready(log_path: Path) -> None:
    start = time.time()
    while time.time() - start < STARTUP_TIMEOUT_S:
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            if "Startup script returned successfully" in text:
                return
            if "make:" in text and "Error" in text:
                raise RuntimeError("PX4 SITL failed to start. See SITL log for details.")
        time.sleep(2)
    raise RuntimeError("PX4 SITL readiness timeout expired.")


def summarize_ulog_topics(ulog_path: Path) -> dict[str, object]:
    summary = {
        "ulog_path": str(ulog_path),
        "pyulog_available": ULog is not None,
        "landing_target_pose_samples": 0,
        "irlock_report_samples": 0,
        "landing_target_pose_preview": {},
        "irlock_report_preview": {},
    }
    if not ulog_path.exists():
        return summary
    if ULog is None:
        summary["error"] = "pyulog is not installed in the active Python environment."
        return summary

    ulog = ULog(str(ulog_path))
    for dataset in ulog.data_list:
        if dataset.name not in {"landing_target_pose", "irlock_report"}:
            continue
        keys = list(dataset.data.keys())
        count = len(dataset.data[keys[0]]) if keys else 0
        preview = {}
        if count:
            for key in keys[:10]:
                value = dataset.data[key][0]
                preview[key] = value.item() if hasattr(value, "item") else value
        summary[f"{dataset.name}_samples"] = count
        summary[f"{dataset.name}_preview"] = preview
    return summary


def wait_for_heartbeat(connection) -> object:
    heartbeat = connection.wait_heartbeat(timeout=OBSERVER_TIMEOUT_S)
    if heartbeat is None:
        raise RuntimeError("Timed out waiting for PX4 heartbeat on the host observer link.")
    return heartbeat


def request_landing_target_stream(connection) -> dict[str, object]:
    target_system = connection.target_system
    target_component = connection.target_component
    connection.mav.command_long_send(
        target_system,
        target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_LANDING_TARGET,
        100_000,
        0,
        0,
        0,
        0,
        0,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        message = connection.recv_match(type="COMMAND_ACK", blocking=True, timeout=0.5)
        if message is None:
            continue
        if message.command != mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL:
            continue
        return {
            "command": int(message.command),
            "result": int(message.result),
        }
    return {
        "command": int(mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL),
        "result": None,
    }


def prime_connection(
    connection_string: str,
    *,
    source_system: int,
    source_component: int,
) -> None:
    priming_connection = mavutil.mavlink_connection(
        connection_string,
        source_system=source_system,
        source_component=source_component,
    )
    try:
        for _ in range(3):
            priming_connection.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0,
                0,
                0,
            )
            time.sleep(0.5)
    finally:
        priming_connection.close()


def collect_outbound_landing_targets(connection, *, duration_s: float) -> dict[str, object]:
    deadline = time.time() + duration_s
    observed_messages: list[dict[str, object]] = []
    first_nonzero_message: dict[str, object] = {}
    position_valid_count = 0
    while time.time() < deadline:
        message = connection.recv_match(blocking=True, timeout=0.5)
        if message is None or message.get_type() != "LANDING_TARGET":
            continue
        message_dict = message.to_dict()
        observed_messages.append(message_dict)
        if int(message_dict.get("position_valid", 0)):
            position_valid_count += 1
        if not first_nonzero_message and (
            int(message_dict.get("position_valid", 0))
            or abs(float(message_dict.get("x", 0.0))) > 1e-6
            or abs(float(message_dict.get("y", 0.0))) > 1e-6
            or abs(float(message_dict.get("z", 0.0))) > 1e-6
        ):
            first_nonzero_message = message_dict

    return {
        "count": len(observed_messages),
        "first_message": observed_messages[0] if observed_messages else {},
        "first_nonzero_message": first_nonzero_message,
        "position_valid_count": position_valid_count,
    }


def main() -> int:
    host_mode = resolve_host_mode()
    direct_px4 = use_direct_px4_transport()
    SITL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    sitl_log = SITL_LOG_DIR / f"landing_target_consumption_{stamp}.log"
    bridge_log = SITL_LOG_DIR / f"landing_target_consumption_{stamp}_bridge.log"
    cleanup_runtime_processes(host_mode=host_mode)
    time.sleep(2)

    sitl_process = start_sitl_process(sitl_log, host_mode=host_mode)
    bridge_process = start_bridge_process(bridge_log, host_mode=host_mode)

    try:
        wait_for_sitl_ready(sitl_log)
        time.sleep(3)

        bridge_ip = None if direct_px4 else (os.environ.get("WSL_BRIDGE_IP") or detect_wsl_bridge_ip(host_mode=host_mode))
        connection_string = os.environ.get(
            "LANDING_TARGET_CONNECTION_STRING",
            default_publisher_connection_string(
                endpoint=LANDING_TARGET_ENDPOINT,
                direct_px4=direct_px4,
                bridge_ip=bridge_ip,
            ),
        )
        observer_connection_string = os.environ.get(
            "LANDING_TARGET_OBSERVER_CONNECTION_STRING",
            default_observer_connection_string(
                endpoint=LANDING_TARGET_ENDPOINT,
                direct_px4=direct_px4,
            ),
        )
        observer = mavutil.mavlink_connection(
            observer_connection_string,
            source_system=246,
            source_component=197,
        )
        if observer_connection_string.startswith("udpout:"):
            prime_connection(
                observer_connection_string,
                source_system=246,
                source_component=197,
            )
        else:
            prime_connection(
                connection_string,
                source_system=247,
                source_component=198,
            )
        heartbeat = wait_for_heartbeat(observer)
        observer_ack = request_landing_target_stream(observer)
        observer_result: dict[str, object] = {}

        collector = threading.Thread(
            target=lambda: observer_result.update(
                collect_outbound_landing_targets(observer, duration_s=COLLECTION_WINDOW_S)
            ),
            daemon=True,
        )
        collector.start()

        samples = build_stationary_landing_target_samples(
            duration_s=DEFAULT_DURATION_S,
            rate_hz=DEFAULT_RATE_HZ,
            x_m=1.25,
            y_m=-0.75,
            z_m=0.0,
        )
        publisher = LandingTargetPublisher(connection_string)
        sent_count = publisher.send_samples(samples, rate_hz=DEFAULT_RATE_HZ)

        collector.join(timeout=COLLECTION_WINDOW_S + 2.0)

        sitl_text = sitl_log.read_text(encoding="utf-8", errors="ignore")
        bridge_text = (
            bridge_log.read_text(encoding="utf-8", errors="ignore")
            if bridge_process is not None and bridge_log.exists()
            else ""
        )
        receiver_observation = parse_receiver_observation(sitl_text)

        ulog_relative_path = extract_ulog_relative_path(sitl_text)
        ulog_path = (
            PX4_REPO / "build" / "px4_sitl_default" / "rootfs" / "log" / Path(ulog_relative_path)
            if ulog_relative_path
            else None
        )
        ulog_summary = summarize_ulog_topics(ulog_path) if ulog_path else {
            "ulog_path": None,
            "pyulog_available": ULog is not None,
            "landing_target_pose_samples": 0,
            "irlock_report_samples": 0,
            "landing_target_pose_preview": {},
            "irlock_report_preview": {},
        }
        bridge_count = (
            count_bridge_direction(
                bridge_text,
                bridge_name=LANDING_TARGET_ENDPOINT,
                direction="host->px4",
            )
            if bridge_text
            else 0
        )

        proof_status = (
            "consumed"
            if receiver_observation.count or ulog_summary["landing_target_pose_samples"]
            else "transport_only"
        )
        payload = {
            "host_mode": host_mode,
            "endpoint": LANDING_TARGET_ENDPOINT,
            "direct_px4_transport": direct_px4,
            "connection_string": connection_string,
            "sent_count": sent_count,
            "duration_s": DEFAULT_DURATION_S,
            "rate_hz": DEFAULT_RATE_HZ,
            "first_sample": sample_to_dict(samples[0]),
            "last_sample": sample_to_dict(samples[-1]),
            "proof_status": proof_status,
            "bridge_host_to_px4_count": bridge_count,
            "observer_connection_string": observer_connection_string,
            "observer_heartbeat": heartbeat.to_dict(),
            "observer_set_message_interval_ack": observer_ack,
            "observer_outbound_landing_target": observer_result,
            "receiver_observation": receiver_observation.to_dict(),
            "sitl_log_path": str(sitl_log),
            "bridge_log_path": str(bridge_log) if bridge_process is not None else None,
            "ulog_summary": ulog_summary,
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0 if proof_status == "consumed" else 1
    finally:
        if bridge_process is not None:
            bridge_process.terminate()
        sitl_process.terminate()
        cleanup_runtime_processes(host_mode=host_mode)


if __name__ == "__main__":
    raise SystemExit(main())
