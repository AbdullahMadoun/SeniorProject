from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .media_binding import discover_media_bindings


def load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _safe_get(mapping: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _profile_value_by_name(profile_artifact: dict[str, Any] | None, name: str) -> Any:
    entries = _safe_get(profile_artifact, "profile")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry.get("applied_value")
    return None


def write_dock_approach_timeline_csv(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "index",
                "mode",
                "in_air",
                "altitude_agl_m",
                "horizontal_distance_to_dock_m",
                "north_m",
                "east_m",
                "down_m",
                "roll_deg",
                "pitch_deg",
                "yaw_deg",
                "target_x_m",
                "target_y_m",
                "target_z_m",
            ],
        )
        writer.writeheader()
        for record in records:
            vehicle_local_pose = record.get("vehicle_local_pose", {})
            attitude_euler = record.get("attitude_euler", {})
            sample = record.get("sample", {})
            snapshot = record.get("snapshot", {})
            writer.writerow(
                {
                    "index": record.get("index"),
                    "mode": snapshot.get("mode"),
                    "in_air": snapshot.get("in_air"),
                    "altitude_agl_m": record.get("altitude_agl_m"),
                    "horizontal_distance_to_dock_m": record.get("horizontal_distance_to_dock_m"),
                    "north_m": vehicle_local_pose.get("north_m"),
                    "east_m": vehicle_local_pose.get("east_m"),
                    "down_m": vehicle_local_pose.get("down_m"),
                    "roll_deg": attitude_euler.get("roll_deg", vehicle_local_pose.get("roll_deg")),
                    "pitch_deg": attitude_euler.get("pitch_deg", vehicle_local_pose.get("pitch_deg")),
                    "yaw_deg": attitude_euler.get("yaw_deg", vehicle_local_pose.get("yaw_deg")),
                    "target_x_m": sample.get("x_m"),
                    "target_y_m": sample.get("y_m"),
                    "target_z_m": sample.get("z_m"),
                }
            )


def build_replay_bundle(
    *,
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    live_px4_dir = repo_root / "artifacts" / "live_px4"
    precision_dir = repo_root / "artifacts" / "precision_landing" / "latest"
    weather_dir = repo_root / "artifacts" / "weather_scenarios" / "latest"
    media_dir = repo_root / "artifacts" / "media" / "latest"

    mission_validation = load_json_if_exists(live_px4_dir / "latest_mission_validation.json")
    execution_validation = load_json_if_exists(live_px4_dir / "latest_execution_validation.json")
    precision_profile = load_json_if_exists(live_px4_dir / "latest_precision_landing_profile.json")
    landing_target_consumption = load_json_if_exists(
        live_px4_dir / "latest_landing_target_consumption.json"
    )
    dock_approach = load_json_if_exists(live_px4_dir / "latest_dock_approach_validation.json")
    live_weather_validation = load_json_if_exists(live_px4_dir / "latest_live_weather_validation.json")
    precision_summary = load_json_if_exists(precision_dir / "manifest.json")
    weather_summary = load_json_if_exists(weather_dir / "manifest.json")
    media_bindings = discover_media_bindings(repo_root)

    output_dir.mkdir(parents=True, exist_ok=True)
    dock_timeline_path = output_dir / "dock_approach_timeline.csv"
    dock_records = _safe_get(dock_approach, "live_stream", "records") or []
    write_dock_approach_timeline_csv(dock_records, dock_timeline_path)

    manifest = {
        "bundle_name": "latest_live_px4_replay_bundle",
        "sources": {
            "mission_validation": str(live_px4_dir / "latest_mission_validation.json"),
            "execution_validation": str(live_px4_dir / "latest_execution_validation.json"),
            "precision_profile": str(live_px4_dir / "latest_precision_landing_profile.json"),
            "landing_target_consumption": str(live_px4_dir / "latest_landing_target_consumption.json"),
            "dock_approach_validation": str(live_px4_dir / "latest_dock_approach_validation.json"),
            "live_weather_validation": str(live_px4_dir / "latest_live_weather_validation.json"),
            "precision_landing_manifest": str(precision_dir / "manifest.json"),
            "weather_scenario_manifest": str(weather_dir / "manifest.json"),
            "media_manifest": str(media_dir / "manifest.json"),
            "dock_approach_timeline": str(dock_timeline_path),
        },
        "artifacts": {
            "mission_validation": mission_validation,
            "execution_validation": execution_validation,
            "precision_profile": precision_profile,
            "landing_target_consumption": landing_target_consumption,
            "dock_approach_validation": dock_approach,
            "live_weather_validation": live_weather_validation,
            "precision_landing_manifest": precision_summary,
            "weather_scenario_manifest": weather_summary,
            "media_bindings": media_bindings,
        },
        "summary": {
            "mission_waypoint_count": _safe_get(mission_validation, "mission", "waypoint_count"),
            "execution_after_rtl_mode": _safe_get(execution_validation, "after_rtl_snapshot", "mode"),
            "dock_proof_status": _safe_get(dock_approach, "proof_status"),
            "dock_stream_record_count": _safe_get(dock_approach, "live_stream", "record_count"),
            "dock_receiver_count": _safe_get(dock_approach, "receiver_observation", "count"),
            "dock_final_horizontal_distance_m": _safe_get(
                dock_approach, "live_stream", "last_record", "horizontal_distance_to_dock_m"
            ),
            "dock_final_in_air": _safe_get(dock_approach, "live_stream", "last_record", "snapshot", "in_air"),
            "precision_profile_rtl_pld_md": _profile_value_by_name(precision_profile, "RTL_PLD_MD"),
            "landing_target_consumption_count": _safe_get(
                landing_target_consumption, "receiver_observation", "count"
            ),
            "live_weather_proof_status": _safe_get(live_weather_validation, "proof_status"),
            "live_weather_triggered_action": _safe_get(live_weather_validation, "triggered_action"),
            "precision_scenario_passed_count": _safe_get(precision_summary, "passed_count"),
            "precision_scenario_total_count": _safe_get(precision_summary, "scenario_count"),
            "weather_scenario_passed_count": _safe_get(weather_summary, "passed_count"),
            "weather_scenario_total_count": _safe_get(weather_summary, "scenario_count"),
            "bound_media_count": len(media_bindings),
        },
    }
    _write_json(output_dir / "manifest.json", manifest)

    summary_lines = [
        "# Live PX4 Replay Bundle Summary",
        "",
        "## Included Evidence",
        "",
        f"- mission validation: {'yes' if mission_validation else 'no'}",
        f"- execution validation: {'yes' if execution_validation else 'no'}",
        f"- precision-landing profile: {'yes' if precision_profile else 'no'}",
        f"- landing-target consumption proof: {'yes' if landing_target_consumption else 'no'}",
        f"- dock-approach validation: {'yes' if dock_approach else 'no'}",
        f"- live weather validation: {'yes' if live_weather_validation else 'no'}",
        f"- precision-landing simulator manifest: {'yes' if precision_summary else 'no'}",
        f"- weather scenario manifest: {'yes' if weather_summary else 'no'}",
        f"- bound media files: `{len(media_bindings)}`",
        "",
        "## Key Results",
        "",
        f"- mission waypoint count: `{manifest['summary']['mission_waypoint_count']}`",
        f"- post-RTL execution mode: `{manifest['summary']['execution_after_rtl_mode']}`",
        f"- dock proof status: `{manifest['summary']['dock_proof_status']}`",
        f"- dock stream record count: `{manifest['summary']['dock_stream_record_count']}`",
        f"- dock receiver count: `{manifest['summary']['dock_receiver_count']}`",
        f"- dock final horizontal distance: `{manifest['summary']['dock_final_horizontal_distance_m']}` m",
        f"- dock final in_air: `{manifest['summary']['dock_final_in_air']}`",
        f"- precision profile `RTL_PLD_MD`: `{manifest['summary']['precision_profile_rtl_pld_md']}`",
        f"- landing-target consumption count: `{manifest['summary']['landing_target_consumption_count']}`",
        f"- live weather proof status: `{manifest['summary']['live_weather_proof_status']}`",
        f"- live weather triggered action: `{manifest['summary']['live_weather_triggered_action']}`",
        f"- precision simulator pass count: `{manifest['summary']['precision_scenario_passed_count']}` / `{manifest['summary']['precision_scenario_total_count']}`",
        f"- weather scenario pass count: `{manifest['summary']['weather_scenario_passed_count']}` / `{manifest['summary']['weather_scenario_total_count']}`",
        f"- bound media count: `{manifest['summary']['bound_media_count']}`",
        "",
        "## Generated Files",
        "",
        f"- [manifest.json]({(output_dir / 'manifest.json').as_posix()})",
        f"- [dock_approach_timeline.csv]({dock_timeline_path.as_posix()})",
    ]
    (output_dir / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return manifest
