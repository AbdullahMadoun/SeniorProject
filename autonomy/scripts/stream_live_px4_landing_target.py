from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_stream import (
    LandingTargetPublisher,
    build_stationary_landing_target_samples,
    connection_string_for_endpoint,
    sample_to_dict,
)
from autonomy.drone_system.landing_target_projection import (
    build_projected_approach_landing_target_samples,
    frame_to_dict,
)


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_landing_target_stream.json"
DEFAULT_DURATION_S = 5.0
DEFAULT_RATE_HZ = 10.0
DEFAULT_ENDPOINT = "gcs"
DEFAULT_SOURCE_MODE = "projected_approach"


def detect_wsl_bridge_ip() -> str | None:
    result = subprocess.run(
        ["wsl", "bash", "-lc", "hostname -I | awk '{print $1}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    bridge_ip = result.stdout.strip()
    if result.returncode != 0 or not bridge_ip:
        return None
    return bridge_ip


def main() -> None:
    bridge_ip = os.environ.get("WSL_BRIDGE_IP") or detect_wsl_bridge_ip()
    endpoint = os.environ.get("LANDING_TARGET_ENDPOINT", DEFAULT_ENDPOINT)
    source_mode = os.environ.get("LANDING_TARGET_SOURCE_MODE", DEFAULT_SOURCE_MODE)
    connection_string = os.environ.get(
        "LANDING_TARGET_CONNECTION_STRING",
        connection_string_for_endpoint(endpoint, bridge_ip=bridge_ip),
    )
    print("stage=build_samples", flush=True)
    projection_preview: dict[str, object] = {}
    if source_mode == "projected_approach":
        samples, frames = build_projected_approach_landing_target_samples(
            duration_s=DEFAULT_DURATION_S,
            rate_hz=DEFAULT_RATE_HZ,
        )
        projection_preview = frame_to_dict(frames[0])
    elif source_mode == "stationary":
        samples = build_stationary_landing_target_samples(
            duration_s=DEFAULT_DURATION_S,
            rate_hz=DEFAULT_RATE_HZ,
            x_m=1.25,
            y_m=-0.75,
            z_m=0.0,
        )
    else:
        raise ValueError(f"Unsupported LANDING_TARGET_SOURCE_MODE '{source_mode}'.")
    publisher = LandingTargetPublisher(connection_string)

    print("stage=stream_samples", flush=True)
    sent_count = publisher.send_samples(samples, rate_hz=DEFAULT_RATE_HZ)

    payload = {
        "endpoint": endpoint,
        "source_mode": source_mode,
        "connection_string": connection_string,
        "duration_s": DEFAULT_DURATION_S,
        "rate_hz": DEFAULT_RATE_HZ,
        "sent_count": sent_count,
        "first_sample": sample_to_dict(samples[0]),
        "last_sample": sample_to_dict(samples[-1]),
        "projection_preview": projection_preview,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("stage=artifact_written", flush=True)
    print(f"Live landing-target stream artifact written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
