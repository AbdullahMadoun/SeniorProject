"""POST a lawnmower mission to mission_api and print the job_id.

Default payload: 45×45m lawnmower, 6 waypoints, 25 m altitude, 5 m/s.
Exit 0 if the response contains status "running"; exit 1 otherwise.

Invocation:
    From Mac (localhost):   python sitl_simple_mission.py
    From Pi over hotspot:   python sitl_simple_mission.py \\
                                --api-url http://<mac-hotspot-ip>:8625
    The default --api-url is 127.0.0.1:8625 and works only on Mac.
    Pi runs must override.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_API_URL = "http://127.0.0.1:8625"
DEFAULT_MISSION_ID = "r12-sitl-lawnmower"
DEFAULT_CRUISE_SPEED_MPS = 5.0
DEFAULT_ALTITUDE_M = 25.0

# 45×45m two-pass lawnmower, row spacing 22.5m — fits 50m dimension limit.
# Diagonal ≈ 63.6m < 100m radius limit. ~36s cruise at 5 m/s.
DEFAULT_WAYPOINTS: list[dict[str, float]] = [
    {"north_m":  0.0, "east_m":  0.0,  "altitude_m": DEFAULT_ALTITUDE_M},
    {"north_m": 45.0, "east_m":  0.0,  "altitude_m": DEFAULT_ALTITUDE_M},
    {"north_m": 45.0, "east_m": 22.5,  "altitude_m": DEFAULT_ALTITUDE_M},
    {"north_m":  0.0, "east_m": 22.5,  "altitude_m": DEFAULT_ALTITUDE_M},
    {"north_m":  0.0, "east_m": 45.0,  "altitude_m": DEFAULT_ALTITUDE_M},
    {"north_m": 45.0, "east_m": 45.0,  "altitude_m": DEFAULT_ALTITUDE_M},
]


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=(
            "Base URL of the mission_api server "
            "(default: %(default)s, works on Mac only; "
            "Pi runs must override, e.g. http://172.20.10.2:8625)"
        ),
    )
    parser.add_argument("--mission-id", default=DEFAULT_MISSION_ID)
    parser.add_argument("--cruise-speed", type=float, default=DEFAULT_CRUISE_SPEED_MPS)
    parser.add_argument(
        "--waypoints",
        type=json.loads,
        default=None,
        help="JSON list of {north_m, east_m, altitude_m} dicts (overrides default lawnmower)",
    )
    args = parser.parse_args(argv)

    waypoints = args.waypoints if args.waypoints is not None else DEFAULT_WAYPOINTS
    payload: dict[str, Any] = {
        "mission_id": args.mission_id,
        "cruise_speed_mps": args.cruise_speed,
        "waypoints": waypoints,
    }

    url = f"{args.api_url.rstrip('/')}/api/mission/execute"
    try:
        result = _post_json(url, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[sitl_simple_mission] HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[sitl_simple_mission] connection error: {exc}", file=sys.stderr)
        return 1

    job_id = result.get("job_id", "")
    status = result.get("status", "")
    print(job_id)
    if status != "running":
        print(f"[sitl_simple_mission] unexpected status={status!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
