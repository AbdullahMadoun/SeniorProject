from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import load_system_baseline
from .showcase_builder import build_showcase_data, load_json


def default_replay_bundle_manifest_path(repo_root: Path) -> Path:
    return repo_root / "artifacts" / "replay_bundle" / "latest" / "manifest.json"


def build_dashboard_data(replay_bundle_manifest: dict[str, Any]) -> dict[str, Any]:
    baseline = load_system_baseline()
    latest_replay = build_showcase_data(replay_bundle_manifest)
    fpv_source_url = os.environ.get("SKYLINK_FPV_SOURCE_URL", "http://127.0.0.1:5050/stream")
    fpv_enabled = os.environ.get("SKYLINK_FPV_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    home_lat = float(os.environ.get("SKYLINK_HOME_LAT", str(baseline.home.lat)))
    home_lon = float(os.environ.get("SKYLINK_HOME_LON", str(baseline.home.lon)))
    return {
        "baseline": {
            "home": {
                "lat": home_lat,
                "lon": home_lon,
                "alt_m": baseline.home.alt_m,
            },
            "mission_limits": {
                "max_radius_m": baseline.mission_limits.max_radius_m,
                "max_altitude_m": baseline.mission_limits.max_altitude_m,
            },
            "speed_band": {
                "min_mps": baseline.speed_band.min_mps,
                "nominal_mps": baseline.speed_band.nominal_mps,
                "max_mps": baseline.speed_band.max_mps,
            },
            "safety": {
                "battery_warn_percent": baseline.safety.battery_warn_percent,
                "battery_rtl_percent": baseline.safety.battery_rtl_percent,
                "battery_emergency_percent": baseline.safety.battery_emergency_percent,
                "max_operating_wind_mps": baseline.safety.max_operating_wind_mps,
            },
            "visualization": {
                "fpv": {
                    "enabled": fpv_enabled,
                    "source_url": fpv_source_url,
                    "proxy_url": "/api/fpv/stream",
                },
                "cinematic": {
                    "redline_pitch_deg": 15.0,
                    "redline_roll_deg": 15.0,
                },
            },
        },
        "latest_replay": latest_replay,
    }


def render_dashboard_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, indent=2).replace("</", "<\\/")
    template_path = Path(__file__).with_name("dashboard_template.html")
    template = template_path.read_text(encoding="utf-8")
    return template.replace("__DASHBOARD_DATA__", payload)


def write_dashboard(
    *,
    replay_bundle_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = load_json(replay_bundle_manifest_path)
    dashboard_data = build_dashboard_data(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dashboard_data.json").write_text(
        json.dumps(dashboard_data, indent=2),
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(
        render_dashboard_html(dashboard_data),
        encoding="utf-8",
    )
    return dashboard_data
