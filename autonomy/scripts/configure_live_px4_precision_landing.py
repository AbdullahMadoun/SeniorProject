from __future__ import annotations

import asyncio
import gc
import json
import os
from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mavsdk import System  # type: ignore

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.precision_landing import PrecisionLandingTuning
from autonomy.drone_system.precision_landing_px4 import (
    apply_px4_precision_landing_profile,
    applied_profile_to_dict,
    build_px4_precision_landing_profile,
)


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_precision_landing_profile.json"
DEFAULT_SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
DEFAULT_CONNECT_TIMEOUT_S = 30.0


async def _wait_for_connection(drone: System) -> None:
    async for state in drone.core.connection_state():
        if state.is_connected:
            return


async def main() -> None:
    baseline = load_system_baseline()
    tuning = PrecisionLandingTuning()
    system_address = os.environ.get("MAVSDK_SYSTEM_ADDRESS", DEFAULT_SYSTEM_ADDRESS)
    connect_timeout_s = float(
        os.environ.get("MAVSDK_CONNECT_TIMEOUT_S", str(DEFAULT_CONNECT_TIMEOUT_S))
    )
    drone = System()

    try:
        print("stage=connect", flush=True)
        await asyncio.wait_for(
            drone.connect(system_address=system_address),
            timeout=connect_timeout_s,
        )
        await asyncio.wait_for(_wait_for_connection(drone), timeout=connect_timeout_s)

        profile = build_px4_precision_landing_profile(baseline, tuning)
        print("stage=apply_profile", flush=True)
        applied = await apply_px4_precision_landing_profile(drone.param, profile)

        payload = {
            "system_address": system_address,
            "connect_timeout_s": connect_timeout_s,
            "profile": applied_profile_to_dict(applied),
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("stage=artifact_written", flush=True)
        print(f"Live PX4 precision landing profile written to: {OUTPUT_PATH}")
    finally:
        stop_server = getattr(drone, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()
        gc.collect()


if __name__ == "__main__":
    asyncio.run(main())
