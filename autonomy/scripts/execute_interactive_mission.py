from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.interactive_mission import (
    build_mission_request,
    interactive_mission_spec_from_dict,
    interactive_mission_spec_to_dict,
    validate_interactive_mission,
    weather_reading_at,
)
from autonomy.drone_system.landing_target_proof import count_bridge_direction, parse_receiver_observation
from autonomy.drone_system.landing_target_projection import DockTarget
from autonomy.drone_system.landing_target_stream import connection_string_for_endpoint
from autonomy.drone_system.live_px4_runtime import (
    capture_live_telemetry,
    detect_wsl_bridge_ip,
    local_pose_to_dict,
    resolve_log_path,
    snapshot_to_dict,
    stream_live_projected_targets,
    wait_for_departure,
    wait_for_mission_entry,
    wait_for_rtl_approach_window,
)
from autonomy.drone_system.models import Waypoint
from autonomy.drone_system.px4_sim_overrides import build_px4_sim_override_plan, plan_to_dict
from autonomy.drone_system.safety_engine import MissionSafetyEngine
from autonomy.drone_system.vehicle_interface import MavsdkVehicleGateway
from autonomy.drone_system.weather_gate import MissionWeatherGate


LIVE_PX4_DIR = REPO_ROOT / "artifacts" / "live_px4"
MISSION_OUTPUT_PATH = LIVE_PX4_DIR / "latest_mission_validation.json"
EXECUTION_OUTPUT_PATH = LIVE_PX4_DIR / "latest_execution_validation.json"
DOCK_OUTPUT_PATH = LIVE_PX4_DIR / "latest_dock_approach_validation.json"
WEATHER_OUTPUT_PATH = LIVE_PX4_DIR / "latest_live_weather_validation.json"

DEFAULT_SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_ENDPOINT = "gcs"
DEPARTURE_RADIUS_M = 5.0
MISSION_ENTRY_TIMEOUT_S = 30.0
DEPARTURE_TIMEOUT_S = 25.0
WEATHER_TRIGGER_TIMEOUT_S = 45.0
DOCK_WEATHER_TIMEOUT_S = 30.0
RTL_APPROACH_TIMEOUT_S = 45.0
STREAM_DURATION_S = 12.0
LIVE_TELEMETRY_INTERVAL_S = 0.35
TELEMETRY_PREFIX = "__TELEMETRY__"
LIVE_POSITION_READY_TIMEOUT_S = 45.0


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _local_waypoints_payload(spec) -> list[dict[str, float]]:
    return [
        {
            "index": index,
            "north_m": waypoint.north_m,
            "east_m": waypoint.east_m,
            "altitude_m": waypoint.altitude_m,
        }
        for index, waypoint in enumerate(spec.waypoints)
    ]


def _weather_profile_payload(spec) -> list[dict[str, float | None]]:
    return [
        {
            "t_s": point.t_s,
            "steady_wind_mps": point.steady_wind_mps,
            "gust_wind_mps": point.gust_wind_mps,
        }
        for point in spec.weather_profile
    ]


def _emit_live_telemetry(payload: dict[str, object]) -> None:
    print(f"{TELEMETRY_PREFIX}{json.dumps(payload, separators=(',', ':'))}", flush=True)


async def _publish_live_telemetry(
    gateway: MavsdkVehicleGateway,
    *,
    runtime_origin_s: float,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        payload = await capture_live_telemetry(
            gateway,
            elapsed_s=time.monotonic() - runtime_origin_s,
        )
        _emit_live_telemetry(payload)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=LIVE_TELEMETRY_INTERVAL_S)
        except asyncio.TimeoutError:
            continue


async def _monitor_dynamic_weather(
    gateway: MavsdkVehicleGateway,
    *,
    baseline,
    spec,
    runtime_start_s: float,
) -> tuple[dict[str, object], object]:
    gate = MissionWeatherGate(baseline)
    engine = MissionSafetyEngine(baseline)
    observations: list[dict[str, object]] = []
    triggered = False
    action_observation: dict[str, object] | None = None
    deadline = time.monotonic() + WEATHER_TRIGGER_TIMEOUT_S

    while time.monotonic() < deadline:
        elapsed_s = time.monotonic() - runtime_start_s
        reading = weather_reading_at(spec.weather_profile, elapsed_s)
        gate_decision = gate.assess(reading)
        snapshot_before = await gateway.get_snapshot()
        local_pose_before = await gateway.get_local_pose()
        inflight_decision = await engine.enforce_inflight_policy(
            gateway,
            wind_mps=gate_decision.effective_wind_mps,
        )
        if inflight_decision.action.value in {"return_to_launch", "land_now"}:
            await asyncio.sleep(2.0)
        snapshot_after = await gateway.get_snapshot()
        local_pose_after = await gateway.get_local_pose()
        observation = {
            "elapsed_s": round(elapsed_s, 3),
            "weather": {
                "steady_wind_mps": reading.steady_wind_mps,
                "gust_wind_mps": reading.gust_wind_mps,
                "source": reading.source,
                "effective_wind_mps": gate_decision.effective_wind_mps,
            },
            "gate_decision": {
                "launch_allowed": gate_decision.launch_allowed,
                "mission_continue_allowed": gate_decision.mission_continue_allowed,
                "dock_allowed": gate_decision.dock_allowed,
                "reasons": [reason.value for reason in gate_decision.reasons],
                "details": list(gate_decision.details),
            },
            "inflight_decision": {
                "action": inflight_decision.action.value,
                "reasons": [reason.value for reason in inflight_decision.reasons],
                "details": list(inflight_decision.details),
            },
            "snapshot_before": snapshot_to_dict(snapshot_before),
            "local_pose_before": local_pose_to_dict(local_pose_before),
            "snapshot_after": snapshot_to_dict(snapshot_after),
            "local_pose_after": local_pose_to_dict(local_pose_after),
        }
        observations.append(observation)
        if inflight_decision.action.value in {"return_to_launch", "land_now"}:
            triggered = True
            action_observation = observation
            break
        await asyncio.sleep(1.0)

    if not triggered:
        raise RuntimeError("Dynamic weather profile did not trigger an in-flight safety action.")

    dock_weather_observations: list[dict[str, object]] = []
    dock_ready = False
    dock_deadline = time.monotonic() + DOCK_WEATHER_TIMEOUT_S
    while time.monotonic() < dock_deadline:
        elapsed_s = time.monotonic() - runtime_start_s
        reading = weather_reading_at(spec.weather_profile, elapsed_s)
        gate_decision = gate.assess(reading)
        dock_entry = {
            "elapsed_s": round(elapsed_s, 3),
            "weather": {
                "steady_wind_mps": reading.steady_wind_mps,
                "gust_wind_mps": reading.gust_wind_mps,
                "source": reading.source,
                "effective_wind_mps": gate_decision.effective_wind_mps,
            },
            "dock_allowed": gate_decision.dock_allowed,
            "details": list(gate_decision.details),
        }
        dock_weather_observations.append(dock_entry)
        if gate_decision.dock_allowed:
            dock_ready = True
            break
        await asyncio.sleep(1.0)

    if not dock_ready:
        raise RuntimeError("Dynamic weather profile never returned to a dock-safe state.")

    payload = {
        "mission_id": spec.mission_id,
        "weather_profile": _weather_profile_payload(spec),
        "trigger_timeout_s": WEATHER_TRIGGER_TIMEOUT_S,
        "dock_wait_timeout_s": DOCK_WEATHER_TIMEOUT_S,
        "observations": observations,
        "dock_weather_observations": dock_weather_observations,
        "triggered_action": action_observation["inflight_decision"]["action"] if action_observation else None,
        "triggered_at_s": action_observation["elapsed_s"] if action_observation else None,
        "dock_recovered_at_s": dock_weather_observations[-1]["elapsed_s"] if dock_weather_observations else None,
        "proof_status": (
            "rtl_triggered_by_live_weather_injection"
            if action_observation and action_observation["inflight_decision"]["action"] == "return_to_launch"
            else "weather_action_not_verified"
        ),
    }
    latest_snapshot = await gateway.get_snapshot()
    return payload, latest_snapshot


async def main_async(spec_path: Path) -> None:
    baseline = load_system_baseline()
    raw_spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    spec = interactive_mission_spec_from_dict(raw_spec, baseline)
    validate_interactive_mission(spec, baseline)

    system_address = os.environ.get("MAVSDK_SYSTEM_ADDRESS", DEFAULT_SYSTEM_ADDRESS)
    connect_timeout_s = float(
        os.environ.get("MAVSDK_CONNECT_TIMEOUT_S", str(DEFAULT_CONNECT_TIMEOUT_S))
    )
    endpoint = os.environ.get("LANDING_TARGET_ENDPOINT", DEFAULT_ENDPOINT)
    bridge_ip = os.environ.get("WSL_BRIDGE_IP") or detect_wsl_bridge_ip()
    connection_string = os.environ.get(
        "LANDING_TARGET_CONNECTION_STRING",
        connection_string_for_endpoint(endpoint, bridge_ip=bridge_ip),
    )
    dock_target = DockTarget(
        north_m=baseline.docking.dock_center_north_m,
        east_m=baseline.docking.dock_center_east_m,
        down_m=baseline.docking.dock_center_down_m,
    )

    gateway = MavsdkVehicleGateway(
        baseline,
        system_address=system_address,
        connect_timeout_s=connect_timeout_s,
    )
    runtime_origin_s = time.monotonic()
    telemetry_stop_event = asyncio.Event()
    telemetry_task: asyncio.Task[None] | None = None
    print("stage=connect", flush=True)
    await gateway.connect()
    try:
        print("stage=await_live_position", flush=True)
        pre_override_snapshot, pre_override_local_pose = await gateway.wait_for_live_position(
            timeout_s=LIVE_POSITION_READY_TIMEOUT_S,
        )

        live_home = Waypoint(
            lat=pre_override_snapshot.position.lat,
            lon=pre_override_snapshot.position.lon,
            alt_m=max(pre_override_snapshot.position.alt_m, 0.0),
        )
        mission_request = build_mission_request(spec, home=live_home)
        override_plan = build_px4_sim_override_plan(spec, baseline)

        print("stage=apply_preflight_overrides", flush=True)
        applied_overrides = await gateway.apply_parameter_overrides(
            float_params=override_plan.float_params,
            int_params=override_plan.int_params,
        )
        initial_snapshot = await gateway.get_snapshot()
        initial_local_pose = await gateway.get_local_pose()
        telemetry_task = asyncio.create_task(
            _publish_live_telemetry(
                gateway,
                runtime_origin_s=runtime_origin_s,
                stop_event=telemetry_stop_event,
            )
        )

        print("stage=preflight_weather_gate", flush=True)
        preflight_weather = weather_reading_at(spec.weather_profile, 0.0)
        preflight_gate = MissionWeatherGate(baseline).assess(preflight_weather)
        preflight_safety = MissionSafetyEngine(baseline).assess_preflight(
            initial_snapshot,
            mission_request,
            wind_mps=preflight_gate.effective_wind_mps,
        )
        if not preflight_gate.launch_allowed or preflight_safety.action.value == "abort_launch":
            raise RuntimeError(
                "Preflight launch blocked: "
                + "; ".join(preflight_safety.details or preflight_gate.details)
            )

        print("stage=upload_geofence", flush=True)
        geofence = build_home_geofence(live_home, baseline.mission_limits.max_radius_m)
        await gateway.upload_geofence(geofence)
        print("stage=upload_mission", flush=True)
        await gateway.upload_mission(mission_request)
        after_upload = await gateway.get_snapshot()
        after_upload_local_pose = await gateway.get_local_pose()

        mission_payload = {
            "system_address": system_address,
            "connect_timeout_s": connect_timeout_s,
            "planner_spec": interactive_mission_spec_to_dict(spec),
            "simulator_overrides": {
                "plan": plan_to_dict(override_plan),
                "applied_parameters": applied_overrides,
            },
            "geofence": {
                "center": {
                    "lat": geofence.center.lat,
                    "lon": geofence.center.lon,
                    "alt_m": geofence.center.alt_m,
                },
                "radius_m": geofence.radius_m,
            },
            "mission": {
                "mission_id": mission_request.mission_id,
                "waypoint_count": len(mission_request.waypoints),
                "cruise_speed_mps": mission_request.cruise_speed_mps,
                "waypoints_local": _local_waypoints_payload(spec),
            },
            "pre_override_snapshot": snapshot_to_dict(pre_override_snapshot),
            "pre_override_local_pose": local_pose_to_dict(pre_override_local_pose),
            "before_upload": snapshot_to_dict(initial_snapshot),
            "before_upload_local_pose": local_pose_to_dict(initial_local_pose),
            "after_upload": snapshot_to_dict(after_upload),
            "after_upload_local_pose": local_pose_to_dict(after_upload_local_pose),
        }
        _write_json(MISSION_OUTPUT_PATH, mission_payload)

        print("stage=arm", flush=True)
        await gateway.arm()
        print("stage=start_mission", flush=True)
        await gateway.start_mission()
        runtime_start_s = time.monotonic()

        print("stage=mission_entry", flush=True)
        mission_entry_snapshot, mission_entry_observations = await wait_for_mission_entry(
            gateway,
            timeout_s=MISSION_ENTRY_TIMEOUT_S,
        )
        print("stage=departure", flush=True)
        departure_observations = await wait_for_departure(
            gateway,
            dock_target,
            min_radius_m=DEPARTURE_RADIUS_M,
            timeout_s=DEPARTURE_TIMEOUT_S,
        )
        print("stage=dynamic_weather_injection", flush=True)
        weather_payload, snapshot_after_weather = await _monitor_dynamic_weather(
            gateway,
            baseline=baseline,
            spec=spec,
            runtime_start_s=runtime_start_s,
        )
        _write_json(WEATHER_OUTPUT_PATH, weather_payload)

        execution_payload = {
            "system_address": system_address,
            "connect_timeout_s": connect_timeout_s,
            "mission_id": mission_request.mission_id,
            "waypoint_count": len(mission_request.waypoints),
            "planner_waypoints_local": _local_waypoints_payload(spec),
            "simulator_overrides": {
                "plan": plan_to_dict(override_plan),
                "applied_parameters": applied_overrides,
            },
            "initial_snapshot": snapshot_to_dict(initial_snapshot),
            "initial_local_pose": local_pose_to_dict(initial_local_pose),
            "mission_phase_snapshots": mission_entry_observations + departure_observations,
            "after_rtl_snapshot": snapshot_to_dict(snapshot_after_weather),
            "after_rtl_local_pose": local_pose_to_dict(await gateway.get_local_pose()),
            "weather_validation_path": str(WEATHER_OUTPUT_PATH),
            "weather_triggered_action": weather_payload["triggered_action"],
        }
        _write_json(EXECUTION_OUTPUT_PATH, execution_payload)

        print("stage=rtl_approach_window", flush=True)
        approach_local_pose, rtl_approach_observations = await wait_for_rtl_approach_window(
            gateway,
            dock_target,
            activation_radius_m=baseline.docking.approach_activation_radius_m,
            timeout_s=RTL_APPROACH_TIMEOUT_S,
        )

        print("stage=landing_target_stream", flush=True)
        from autonomy.drone_system.landing_target_stream import LandingTargetPublisher

        publisher = LandingTargetPublisher(connection_string)
        live_stream_records = await stream_live_projected_targets(
            gateway,
            publisher,
            dock_target,
            rate_hz=baseline.docking.landing_target_stream_rate_hz,
            duration_s=STREAM_DURATION_S,
        )
        after_stream_snapshot = await gateway.get_snapshot()
        after_stream_local_pose = await gateway.get_local_pose()
        await asyncio.sleep(2.0)

        sitl_log_path = resolve_log_path(REPO_ROOT, "LIVE_PX4_SITL_LOG_PATH", "interactive_mission_*.log")
        bridge_log_path = resolve_log_path(REPO_ROOT, "LIVE_PX4_BRIDGE_LOG_PATH", "interactive_mission_*_bridge.log")
        receiver_observation = {"count": 0, "first_match": {}}
        bridge_summary = {
            "gcs_host_to_px4_count": 0,
            "gcs_px4_to_host_count": 0,
        }
        if sitl_log_path is not None:
            sitl_log_text = sitl_log_path.read_text(encoding="utf-8", errors="replace")
            receiver_observation = parse_receiver_observation(sitl_log_text).to_dict()
        if bridge_log_path is not None:
            bridge_log_text = bridge_log_path.read_text(encoding="utf-8", errors="replace")
            bridge_summary = {
                "gcs_host_to_px4_count": count_bridge_direction(
                    bridge_log_text,
                    bridge_name="gcs",
                    direction="host->px4",
                ),
                "gcs_px4_to_host_count": count_bridge_direction(
                    bridge_log_text,
                    bridge_name="gcs",
                    direction="px4->host",
                ),
            }

        dock_payload = {
            "system_address": system_address,
            "connect_timeout_s": connect_timeout_s,
            "mission_id": mission_request.mission_id,
            "waypoint_count": len(mission_request.waypoints),
            "planner_waypoints_local": _local_waypoints_payload(spec),
            "simulator_overrides": {
                "plan": plan_to_dict(override_plan),
                "applied_parameters": applied_overrides,
            },
            "dock_target": {
                "north_m": dock_target.north_m,
                "east_m": dock_target.east_m,
                "down_m": dock_target.down_m,
            },
            "landing_target_connection": {
                "endpoint": endpoint,
                "connection_string": connection_string,
                "stream_rate_hz": baseline.docking.landing_target_stream_rate_hz,
                "stream_duration_s": STREAM_DURATION_S,
            },
            "evidence_paths": {
                "sitl_log_path": str(sitl_log_path) if sitl_log_path is not None else None,
                "bridge_log_path": str(bridge_log_path) if bridge_log_path is not None else None,
                "weather_validation_path": str(WEATHER_OUTPUT_PATH),
            },
            "initial_snapshot": snapshot_to_dict(initial_snapshot),
            "initial_local_pose": local_pose_to_dict(initial_local_pose),
            "mission_entry_snapshot": snapshot_to_dict(mission_entry_snapshot),
            "mission_entry_observations": mission_entry_observations,
            "departure_observations": departure_observations,
            "rtl_approach_window": {
                "activation_radius_m": baseline.docking.approach_activation_radius_m,
                "entry_local_pose": local_pose_to_dict(approach_local_pose),
                "observations": rtl_approach_observations,
            },
            "weather_validation": weather_payload,
            "live_stream": {
                "record_count": len(live_stream_records),
                "first_record": live_stream_records[0] if live_stream_records else {},
                "last_record": live_stream_records[-1] if live_stream_records else {},
                "records": live_stream_records,
            },
            "after_stream_snapshot": snapshot_to_dict(after_stream_snapshot),
            "after_stream_local_pose": local_pose_to_dict(after_stream_local_pose),
            "receiver_observation": receiver_observation,
            "bridge_summary": bridge_summary,
            "proof_status": (
                "consumed_from_live_telemetry_projection"
                if receiver_observation["count"] >= len(live_stream_records)
                else "streamed_without_full_receiver_match"
            ),
        }
        _write_json(DOCK_OUTPUT_PATH, dock_payload)
        print("stage=artifacts_written", flush=True)
        print(f"Mission artifact written to: {MISSION_OUTPUT_PATH}", flush=True)
        print(f"Execution artifact written to: {EXECUTION_OUTPUT_PATH}", flush=True)
        print(f"Weather artifact written to: {WEATHER_OUTPUT_PATH}", flush=True)
        print(f"Dock artifact written to: {DOCK_OUTPUT_PATH}", flush=True)
    finally:
        telemetry_stop_event.set()
        if telemetry_task is not None:
            try:
                await telemetry_task
            except Exception:
                pass
        await gateway.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-spec", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main_async(args.mission_spec))


if __name__ == "__main__":
    main()
