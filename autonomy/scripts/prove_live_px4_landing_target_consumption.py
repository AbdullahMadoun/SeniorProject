from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from pyulog import ULog  # type: ignore

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
    sample_to_dict,
)


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_landing_target_consumption.json"
SITL_LOG_DIR = REPO_ROOT / "artifacts" / "sitl_logs"
PX4_REPO = REPO_ROOT / "vendor" / "PX4-Autopilot"
PX4_REPO_WSL = "/mnt/d/downloads/SeniorProject/Skylink2/vendor/PX4-Autopilot"
BRIDGE_SCRIPT_WSL = "/mnt/d/downloads/SeniorProject/Skylink2/autonomy/scripts/wsl_mavlink_bridge.py"
LANDING_TARGET_ENDPOINT = "gcs"
SITL_MODEL = "gz_x500"
STARTUP_TIMEOUT_S = 180
DEFAULT_DURATION_S = 5.0
DEFAULT_RATE_HZ = 10.0
OBSERVER_CONNECTION_STRING = "udpin:0.0.0.0:14550"
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


def run_wsl(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl", "bash", "-lc", command],
        capture_output=True,
        text=True,
        check=False,
    )


def detect_wsl_bridge_ip() -> str | None:
    result = run_wsl("hostname -I | awk '{print $1}'")
    bridge_ip = result.stdout.strip()
    if result.returncode != 0 or not bridge_ip:
        return None
    return bridge_ip


def start_wsl_process(command: str, log_path: Path) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        ["wsl", "bash", "-lc", command],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return ManagedProcess(process, log_handle)


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
        "landing_target_pose_samples": 0,
        "irlock_report_samples": 0,
        "landing_target_pose_preview": {},
        "irlock_report_preview": {},
    }
    if not ulog_path.exists():
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


def prime_gcs_link(connection_string: str) -> None:
    priming_connection = mavutil.mavlink_connection(
        connection_string,
        source_system=247,
        source_component=198,
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
    SITL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    sitl_log = SITL_LOG_DIR / f"landing_target_consumption_{stamp}.log"
    bridge_log = SITL_LOG_DIR / f"landing_target_consumption_{stamp}_bridge.log"
    run_wsl(
        " && ".join(
            (
                f"pkill -f '{PX4_REPO_WSL}/build/px4_sitl_default/bin/px4' || true",
                "pkill -f 'make px4_sitl' || true",
                f"pkill -f '{BRIDGE_SCRIPT_WSL}' || true",
            )
        )
    )
    time.sleep(2)

    sitl_process = start_wsl_process(
        f"cd '{PX4_REPO_WSL}' && HEADLESS=1 make px4_sitl {SITL_MODEL}",
        sitl_log,
    )
    bridge_process = start_wsl_process(
        f"python3 '{BRIDGE_SCRIPT_WSL}'",
        bridge_log,
    )

    try:
        wait_for_sitl_ready(sitl_log)
        time.sleep(3)

        bridge_ip = os.environ.get("WSL_BRIDGE_IP") or detect_wsl_bridge_ip()
        connection_string = os.environ.get(
            "LANDING_TARGET_CONNECTION_STRING",
            connection_string_for_endpoint(LANDING_TARGET_ENDPOINT, bridge_ip=bridge_ip),
        )
        observer = mavutil.mavlink_connection(OBSERVER_CONNECTION_STRING, source_system=246, source_component=197)
        prime_gcs_link(connection_string)
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
        bridge_text = bridge_log.read_text(encoding="utf-8", errors="ignore")
        receiver_observation = parse_receiver_observation(sitl_text)

        ulog_relative_path = extract_ulog_relative_path(sitl_text)
        ulog_path = (
            PX4_REPO / "build" / "px4_sitl_default" / "rootfs" / "log" / Path(ulog_relative_path)
            if ulog_relative_path
            else None
        )
        ulog_summary = summarize_ulog_topics(ulog_path) if ulog_path else {
            "ulog_path": None,
            "landing_target_pose_samples": 0,
            "irlock_report_samples": 0,
            "landing_target_pose_preview": {},
            "irlock_report_preview": {},
        }
        bridge_count = count_bridge_direction(bridge_text, bridge_name=LANDING_TARGET_ENDPOINT, direction="host->px4")

        proof_status = (
            "consumed"
            if receiver_observation.count or ulog_summary["landing_target_pose_samples"]
            else "transport_only"
        )
        payload = {
            "endpoint": LANDING_TARGET_ENDPOINT,
            "connection_string": connection_string,
            "sent_count": sent_count,
            "duration_s": DEFAULT_DURATION_S,
            "rate_hz": DEFAULT_RATE_HZ,
            "first_sample": sample_to_dict(samples[0]),
            "last_sample": sample_to_dict(samples[-1]),
            "proof_status": proof_status,
            "bridge_host_to_px4_count": bridge_count,
            "observer_connection_string": OBSERVER_CONNECTION_STRING,
            "observer_heartbeat": heartbeat.to_dict(),
            "observer_set_message_interval_ack": observer_ack,
            "observer_outbound_landing_target": observer_result,
            "receiver_observation": receiver_observation.to_dict(),
            "sitl_log_path": str(sitl_log),
            "bridge_log_path": str(bridge_log),
            "ulog_summary": ulog_summary,
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0 if proof_status == "consumed" else 1
    finally:
        bridge_process.terminate()
        sitl_process.terminate()
        run_wsl(
            " && ".join(
                (
                    f"pkill -f '{PX4_REPO_WSL}/build/px4_sitl_default/bin/px4' || true",
                    "pkill -f 'make px4_sitl' || true",
                    f"pkill -f '{BRIDGE_SCRIPT_WSL}' || true",
                )
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
