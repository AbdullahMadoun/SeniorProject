from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def default_replay_bundle_manifest_path(repo_root: Path) -> Path:
    return repo_root / "artifacts" / "replay_bundle" / "latest" / "manifest.json"


def _safe_get(mapping: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _precision_parameters(profile_artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries = _safe_get(profile_artifact, "profile")
    if not isinstance(entries, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "name": entry.get("name"),
                "applied_value": entry.get("applied_value"),
                "rationale": entry.get("rationale"),
            }
        )
    return normalized


def _precision_scenarios(precision_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries = _safe_get(precision_manifest, "results")
    if not isinstance(entries, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "name": entry.get("name"),
                "passed": entry.get("passed"),
                "final_phase": entry.get("final_phase"),
                "touchdown_error_m": entry.get("touchdown_error_m"),
                "details": entry.get("details", []),
            }
        )
    return normalized


def _precision_nominal_steps(precision_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    steps = _safe_get(precision_manifest, "steps", "nominal_precision_touchdown")
    if not isinstance(steps, list):
        return []
    normalized: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        normalized.append(
            {
                "t_s": step.get("t_s"),
                "phase": step.get("phase"),
                "altitude_m": step.get("altitude_m"),
                "horizontal_error_m": step.get("horizontal_error_m"),
            }
        )
    return normalized


def _dock_records(dock_artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    records = _safe_get(dock_artifact, "live_stream", "records")
    if not isinstance(records, list):
        return []
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        pose = record.get("vehicle_local_pose", {})
        snapshot = record.get("snapshot", {})
        normalized.append(
            {
                "index": record.get("index"),
                "mode": snapshot.get("mode"),
                "in_air": snapshot.get("in_air"),
                "battery_percent": snapshot.get("battery_percent"),
                "altitude_agl_m": record.get("altitude_agl_m"),
                "horizontal_distance_to_dock_m": record.get("horizontal_distance_to_dock_m"),
                "north_m": pose.get("north_m"),
                "east_m": pose.get("east_m"),
                "down_m": pose.get("down_m"),
                "yaw_deg": pose.get("yaw_deg"),
            }
        )
    return normalized


def _weather_results(weather_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    results = _safe_get(weather_manifest, "results")
    if not isinstance(results, list):
        return []
    normalized: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        normalized.append(
            {
                "name": result.get("name"),
                "passed": result.get("passed"),
                "effective_wind_mps": result.get("effective_wind_mps"),
                "launch_allowed": result.get("launch_allowed"),
                "mission_continue_allowed": result.get("mission_continue_allowed"),
                "dock_allowed": result.get("dock_allowed"),
                "safety_action": result.get("safety_action"),
                "final_mode": result.get("final_mode"),
            }
        )
    return normalized


def _snapshot_stage(label: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    position = snapshot.get("position", {}) if isinstance(snapshot, dict) else {}
    mission_progress = snapshot.get("mission_progress", {}) if isinstance(snapshot, dict) else {}
    return {
        "label": label,
        "mode": snapshot.get("mode"),
        "armed": snapshot.get("armed"),
        "in_air": snapshot.get("in_air"),
        "battery_percent": snapshot.get("battery_percent"),
        "alt_m": position.get("alt_m"),
        "mission_current": mission_progress.get("current"),
        "mission_total": mission_progress.get("total"),
    }


def _mission_lifecycle(
    mission_validation: dict[str, Any] | None,
    execution_validation: dict[str, Any] | None,
    dock_artifact: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    lifecycle: list[dict[str, Any]] = []
    lifecycle.append(_snapshot_stage("Before Upload", _safe_get(mission_validation, "before_upload") or {}))
    lifecycle.append(_snapshot_stage("After Upload", _safe_get(mission_validation, "after_upload") or {}))
    lifecycle.append(_snapshot_stage("Execution Start", _safe_get(execution_validation, "initial_snapshot") or {}))
    mission_snapshots = _safe_get(execution_validation, "mission_phase_snapshots")
    if isinstance(mission_snapshots, list) and mission_snapshots:
        lifecycle.append(_snapshot_stage("Mission Entry", mission_snapshots[0].get("snapshot")))
    lifecycle.append(_snapshot_stage("RTL Active", _safe_get(execution_validation, "after_rtl_snapshot") or {}))
    dock_first = _safe_get(dock_artifact, "live_stream", "first_record", "snapshot") or {}
    dock_last = _safe_get(dock_artifact, "live_stream", "last_record", "snapshot") or {}
    lifecycle.append(_snapshot_stage("Dock Approach", dock_first))
    lifecycle.append(_snapshot_stage("Dock Final", dock_last))
    return lifecycle

DEFAULT_GEOFENCE_RADIUS_M = 100.0
DEFAULT_SCENE_EXTENT_M = 200.0


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _normalize_mode(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip().lower()


def _load_preferred_artifact(replay_bundle_manifest: dict[str, Any], artifact_name: str) -> dict[str, Any]:
    source_path_raw = _safe_get(replay_bundle_manifest, "sources", artifact_name)
    if isinstance(source_path_raw, str) and source_path_raw:
        source_path = Path(source_path_raw)
        if source_path.exists():
            try:
                return load_json(source_path)
            except json.JSONDecodeError:
                pass
    artifact = _safe_get(replay_bundle_manifest, "artifacts", artifact_name)
    return artifact if isinstance(artifact, dict) else {}


def _load_preferred_value(replay_bundle_manifest: dict[str, Any], artifact_name: str) -> Any:
    artifact = _safe_get(replay_bundle_manifest, "artifacts", artifact_name)
    return artifact


def _sample_time_seconds(record: dict[str, Any]) -> float | None:
    time_usec = _coerce_float(_safe_get(record, "sample", "time_usec"))
    if time_usec is None:
        return None
    return time_usec / 1_000_000.0


def _normalized_telemetry_frame(
    record: dict[str, Any],
    *,
    source: str,
    source_index: int,
    dock_target: dict[str, float],
) -> dict[str, Any] | None:
    pose = record.get("vehicle_local_pose")
    if not isinstance(pose, dict):
        pose = record.get("local_pose")
    if not isinstance(pose, dict):
        return None

    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    attitude = record.get("attitude_euler") if isinstance(record.get("attitude_euler"), dict) else {}
    north_m = _coerce_float(pose.get("north_m"))
    east_m = _coerce_float(pose.get("east_m"))
    down_m = _coerce_float(pose.get("down_m"))
    yaw_deg = _coerce_float(attitude.get("yaw_deg"))
    if yaw_deg is None:
        yaw_deg = _coerce_float(pose.get("yaw_deg"))
    if north_m is None or east_m is None or down_m is None or yaw_deg is None:
        return None

    horizontal_distance_to_dock_m = _coerce_float(record.get("horizontal_distance_to_dock_m"))
    if horizontal_distance_to_dock_m is None:
        horizontal_distance_to_dock_m = math.hypot(
            north_m - dock_target.get("north_m", 0.0),
            east_m - dock_target.get("east_m", 0.0),
        )

    altitude_agl_m = _coerce_float(record.get("altitude_agl_m"))
    if altitude_agl_m is None:
        altitude_agl_m = max(0.0, dock_target.get("down_m", 0.0) - down_m)

    in_air = _coerce_bool(snapshot.get("in_air"))
    if in_air is None:
        in_air = altitude_agl_m > 0.25

    return {
        "index": -1,
        "source": source,
        "source_index": source_index,
        "t_s": _coerce_float(record.get("t_s")) or _sample_time_seconds(record),
        "north_m": north_m,
        "east_m": east_m,
        "down_m": down_m,
        "yaw_deg": yaw_deg,
        "roll_deg": _coerce_float(attitude.get("roll_deg")) or _coerce_float(pose.get("roll_deg")) or 0.0,
        "pitch_deg": _coerce_float(attitude.get("pitch_deg")) or _coerce_float(pose.get("pitch_deg")) or 0.0,
        "mode": _normalize_mode(snapshot.get("mode")) or "unknown",
        "battery_percent": _coerce_float(snapshot.get("battery_percent")),
        "in_air": in_air,
        "horizontal_distance_to_dock_m": horizontal_distance_to_dock_m,
        "altitude_agl_m": altitude_agl_m,
        "speed_mps": 0.0,
    }


def _flight_telemetry(dock_artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(dock_artifact, dict):
        return []
    dock_target_raw = dock_artifact.get("dock_target") if isinstance(dock_artifact.get("dock_target"), dict) else {}
    dock_target = {
        "north_m": _coerce_float(dock_target_raw.get("north_m")) or 0.0,
        "east_m": _coerce_float(dock_target_raw.get("east_m")) or 0.0,
        "down_m": _coerce_float(dock_target_raw.get("down_m")) or 0.0,
    }
    frame_groups = (
        ("mission_entry", _safe_get(dock_artifact, "mission_entry_observations") or []),
        ("departure", _safe_get(dock_artifact, "departure_observations") or []),
        ("rtl_approach", _safe_get(dock_artifact, "rtl_approach_window", "observations") or []),
        ("dock_stream", _safe_get(dock_artifact, "live_stream", "records") or []),
    )
    normalized: list[dict[str, Any]] = []
    for source, frames in frame_groups:
        if not isinstance(frames, list):
            continue
        for source_index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                continue
            normalized_frame = _normalized_telemetry_frame(
                frame,
                source=source,
                source_index=source_index,
                dock_target=dock_target,
            )
            if normalized_frame is not None:
                normalized.append(normalized_frame)

    for index, frame in enumerate(normalized):
        frame["index"] = index
        if index == 0:
            continue
        previous = normalized[index - 1]
        dt_s = _coerce_float(frame.get("t_s"))
        previous_t_s = _coerce_float(previous.get("t_s"))
        if dt_s is None or previous_t_s is None:
            dt_s = 1.0
        else:
            delta_t_s = dt_s - previous_t_s
            if delta_t_s <= 0.0 or delta_t_s > 30.0:
                dt_s = 1.0
            else:
                dt_s = max(0.05, delta_t_s)
        distance_m = math.sqrt(
            (frame["north_m"] - previous["north_m"]) ** 2
            + (frame["east_m"] - previous["east_m"]) ** 2
            + (frame["down_m"] - previous["down_m"]) ** 2
        )
        frame["speed_mps"] = distance_m / dt_s
    return normalized


def _mission_waypoints(mission_validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    explicit = _safe_get(mission_validation, "mission", "waypoints_local")
    if isinstance(explicit, list):
        waypoints: list[dict[str, Any]] = []
        for index, waypoint in enumerate(explicit):
            if not isinstance(waypoint, dict):
                continue
            north_m = _coerce_float(waypoint.get("north_m"))
            east_m = _coerce_float(waypoint.get("east_m"))
            if north_m is None or east_m is None:
                continue
            waypoints.append(
                {
                    "index": index,
                    "north_m": north_m,
                    "east_m": east_m,
                    "altitude_m": _coerce_float(waypoint.get("altitude_m")) or 0.0,
                }
            )
        if waypoints:
            return waypoints

    waypoint_count = int(_coerce_float(_safe_get(mission_validation, "mission", "waypoint_count")) or 0)
    east_span_m = _coerce_float(_safe_get(mission_validation, "mission", "east_span_m"))
    north_span_m = _coerce_float(_safe_get(mission_validation, "mission", "north_span_m"))
    if waypoint_count < 2 or east_span_m is None or north_span_m is None:
        return []

    row_count = max(1, math.ceil(waypoint_count / 2))
    north_step_m = 0.0 if row_count <= 1 else north_span_m / max(row_count - 1, 1)
    waypoints = []
    direction_east = True
    waypoint_index = 0
    for row_index in range(row_count):
        north_m = row_index * north_step_m
        east_values = (0.0, east_span_m) if direction_east else (east_span_m, 0.0)
        for east_m in east_values:
            if waypoint_index >= waypoint_count:
                break
            waypoints.append(
                {
                    "index": waypoint_index,
                    "north_m": north_m,
                    "east_m": east_m,
                    "altitude_m": 0.0,
                }
            )
            waypoint_index += 1
        direction_east = not direction_east
    return waypoints


def build_showcase_data(replay_bundle_manifest: dict[str, Any]) -> dict[str, Any]:
    mission_validation = _load_preferred_artifact(replay_bundle_manifest, "mission_validation")
    execution_validation = _load_preferred_artifact(replay_bundle_manifest, "execution_validation")
    precision_profile = _load_preferred_artifact(replay_bundle_manifest, "precision_profile")
    landing_target = _load_preferred_artifact(replay_bundle_manifest, "landing_target_consumption")
    dock_artifact = _load_preferred_artifact(replay_bundle_manifest, "dock_approach_validation")
    live_weather_validation = _load_preferred_artifact(replay_bundle_manifest, "live_weather_validation")
    precision_manifest = _load_preferred_artifact(replay_bundle_manifest, "precision_landing_manifest")
    weather_manifest = _load_preferred_artifact(replay_bundle_manifest, "weather_scenario_manifest")
    media_bindings = _load_preferred_value(replay_bundle_manifest, "media_bindings")
    flight_telemetry = _flight_telemetry(dock_artifact)
    mission_waypoints = _mission_waypoints(mission_validation)
    geofence_radius_m = _coerce_float(_safe_get(mission_validation, "geofence", "radius_m")) or DEFAULT_GEOFENCE_RADIUS_M
    dock_target = {
        "north_m": _coerce_float(_safe_get(dock_artifact, "dock_target", "north_m")) or 0.0,
        "east_m": _coerce_float(_safe_get(dock_artifact, "dock_target", "east_m")) or 0.0,
        "down_m": _coerce_float(_safe_get(dock_artifact, "dock_target", "down_m")) or 0.0,
    }

    return {
        "bundle_name": replay_bundle_manifest.get("bundle_name"),
        "summary": replay_bundle_manifest.get("summary", {}),
        "simulation": {
            "scene_extent_m": DEFAULT_SCENE_EXTENT_M,
            "geofence_radius_m": geofence_radius_m,
            "dock_target": dock_target,
        },
        "flight_telemetry": flight_telemetry,
        "mission": {
            "mission_id": _safe_get(mission_validation, "mission", "mission_id") or execution_validation.get("mission_id"),
            "waypoint_count": _safe_get(mission_validation, "mission", "waypoint_count") or execution_validation.get("waypoint_count"),
            "cruise_speed_mps": _safe_get(mission_validation, "mission", "cruise_speed_mps"),
            "geofence_radius_m": geofence_radius_m,
            "area_m2": _safe_get(mission_validation, "mission", "area_m2"),
            "north_span_m": _safe_get(mission_validation, "mission", "north_span_m"),
            "east_span_m": _safe_get(mission_validation, "mission", "east_span_m"),
            "post_rtl_mode": _safe_get(execution_validation, "after_rtl_snapshot", "mode"),
            "lifecycle": _mission_lifecycle(mission_validation, execution_validation, dock_artifact),
            "waypoints": mission_waypoints,
        },
        "landing_target": {
            "proof_status": landing_target.get("proof_status"),
            "receiver_count": _safe_get(landing_target, "receiver_observation", "count"),
            "bridge_host_to_px4_count": landing_target.get("bridge_host_to_px4_count"),
            "first_match": _safe_get(landing_target, "receiver_observation", "first_match") or {},
        },
        "dock": {
            "proof_status": dock_artifact.get("proof_status"),
            "activation_radius_m": _safe_get(dock_artifact, "rtl_approach_window", "activation_radius_m"),
            "final_horizontal_distance_m": _safe_get(dock_artifact, "live_stream", "last_record", "horizontal_distance_to_dock_m"),
            "final_in_air": _safe_get(dock_artifact, "live_stream", "last_record", "snapshot", "in_air"),
            "telemetry_frame_count": len(flight_telemetry),
            "records": _dock_records(dock_artifact),
        },
        "precision_landing": {
            "parameters": _precision_parameters(precision_profile),
            "scenarios": _precision_scenarios(precision_manifest),
            "nominal_steps": _precision_nominal_steps(precision_manifest),
        },
        "media": media_bindings if isinstance(media_bindings, list) else [],
        "weather": {
            "wind_limit_mps": 7.0,
            "results": _weather_results(weather_manifest),
            "live_validation": {
                "proof_status": live_weather_validation.get("proof_status"),
                "triggered_action": live_weather_validation.get("triggered_action"),
                "triggered_at_s": live_weather_validation.get("triggered_at_s"),
                "dock_recovered_at_s": live_weather_validation.get("dock_recovered_at_s"),
                "observations": live_weather_validation.get("observations", []),
                "dock_weather_observations": live_weather_validation.get("dock_weather_observations", []),
            },
        },
    }


def render_showcase_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, indent=2).replace("</", "<\\/")
    template_path = Path(__file__).with_name("showcase_template.html")
    template = template_path.read_text(encoding="utf-8")
    return template.replace("__SHOWCASE_DATA__", payload)

def write_showcase(
    *,
    replay_bundle_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = load_json(replay_bundle_manifest_path)
    showcase_data = build_showcase_data(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "showcase_data.json").write_text(
        json.dumps(showcase_data, indent=2),
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(
        render_showcase_html(showcase_data),
        encoding="utf-8",
    )
    return showcase_data
