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

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.vehicle_interface import MavsdkVehicleGateway


OUTPUT_PATH = REPO_ROOT / "artifacts" / "live_px4" / "latest_snapshot.json"
DEFAULT_SYSTEM_ADDRESS = "udpin://0.0.0.0:14540"
DEFAULT_CONNECT_TIMEOUT_S = 15.0


def _local_pose_to_dict(local_pose) -> dict[str, object]:
    return {
        "north_m": local_pose.north_m if local_pose else None,
        "east_m": local_pose.east_m if local_pose else None,
        "down_m": local_pose.down_m if local_pose else None,
        "yaw_deg": local_pose.yaw_deg if local_pose else None,
    }


async def main() -> None:
    baseline = load_system_baseline()
    system_address = os.environ.get("MAVSDK_SYSTEM_ADDRESS", DEFAULT_SYSTEM_ADDRESS)
    connect_timeout_s = float(
        os.environ.get("MAVSDK_CONNECT_TIMEOUT_S", str(DEFAULT_CONNECT_TIMEOUT_S))
    )
    gateway = MavsdkVehicleGateway(
        baseline,
        system_address=system_address,
        connect_timeout_s=connect_timeout_s,
    )
    try:
        await gateway.connect()
        snapshot = await gateway.get_snapshot()
        local_pose = await gateway.get_local_pose()

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(
                {
                    "system_address": system_address,
                    "connect_timeout_s": connect_timeout_s,
                    "connected": snapshot.connected,
                    "armed": snapshot.armed,
                    "in_air": snapshot.in_air,
                    "mode": snapshot.mode.value,
                    "battery_percent": snapshot.battery_percent,
                    "position": {
                        "lat": snapshot.position.lat if snapshot.position else None,
                        "lon": snapshot.position.lon if snapshot.position else None,
                        "alt_m": snapshot.position.alt_m if snapshot.position else None,
                    },
                    "mission_progress": {
                        "current": snapshot.mission_progress.current,
                        "total": snapshot.mission_progress.total,
                    },
                    "local_pose": _local_pose_to_dict(local_pose),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Live PX4 snapshot written to: {OUTPUT_PATH}")
    finally:
        await gateway.disconnect()
        gc.collect()


if __name__ == "__main__":
    asyncio.run(main())
