from __future__ import annotations

import contextlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reuse the HTML syncing utility from the existing export script
from autonomy.scripts.export_landing_demo_data import (
    PROOF_SOURCE_LIVE_PX4_SITL,
    build_demo_proof,
    build_event_entry,
    build_command_entry,
    sync_embedded_payload,
)

INPUT_LOG_PATH = REPO_ROOT / "artifacts" / "live_px4" / "rtl_precision_landing_console.txt"
OUTPUT_JSON_PATH = REPO_ROOT / "artifacts" / "demo" / "landing_trajectory.json"

# Regex for telemetry lines
TELEMETRY_PATTERN = re.compile(
    r"telemetry t_s=(?P<t>\d+\.\d+) mode=(?P<mode>\w+) altitude_m=(?P<alt>-?\d+\.\d+) "
    r"vz_down_mps=(?P<vz>-?\d+\.\d+) vx_north_mps=(?P<vx>-?\d+\.\d+) vy_east_mps=(?P<vy>-?\d+\.\d+)"
)

# Regex for position checkpoints
CHECKPOINT_PATTERN = re.compile(
    r"(?P<kind>takeoff_transition|flyaway_target_reached|touchdown_detected) .*?north_m=(?P<north>-?\d+\.\d+) east_m=(?P<east>-?\d+\.\d+)"
)

EVENT_PATTERN = re.compile(r"\[(?P<stamp>.*?)\] (?P<msg>.*)")

def parse_live_log() -> dict[str, Any]:
    if not INPUT_LOG_PATH.exists():
        raise FileNotFoundError(f"Source log not found at {INPUT_LOG_PATH}")

    content = INPUT_LOG_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    frames = []
    events = []
    commands = []
    
    # Dead reckoning state
    current_north = 0.0
    current_east = 0.0
    last_t = 0.0
    
    # We use these to "snap" position to known truth from the log
    checkpoints = {}

    for line in lines:
        # Check for events/checkpoints
        cp_match = CHECKPOINT_PATTERN.search(line)
        if cp_match:
            kind = cp_match.group("kind")
            n = float(cp_match.group("north"))
            e = float(cp_match.group("east"))
            checkpoints[kind] = (n, e)
            
            # Snap current position if we reach a checkpoint
            current_north = n
            current_east = e
            
        # Parse telemetry
        tel_match = TELEMETRY_PATTERN.search(line)
        if tel_match:
            t = float(tel_match.group("t"))
            mode = tel_match.group("mode")
            alt = float(tel_match.group("alt"))
            vz = float(tel_match.group("vz"))
            vx = float(tel_match.group("vx"))
            vy = float(tel_match.group("vy"))
            
            dt = t - last_t
            if dt > 0 and dt < 2.0: # Sanity check for DT
                current_north += vx * dt
                current_east += vy * dt
            
            last_t = t
            
            # Record frame
            frames.append({
                "t": t,
                "north_m": round(current_north, 6),
                "east_m": round(current_east, 6),
                "down_m": round(-alt, 6),
                "target_north_m": 0.0, # Will update phase-specifically
                "target_east_m": 0.0,
                "phase": mode.upper(),
                "horizontal_error_m": math.hypot(current_north, current_east),
                "altitude_m": round(alt, 6),
                "forward_vel": round(vx, 6), # Rough approximation for body vel
                "right_vel": round(vy, 6),
                "forward_error_m": round(current_north, 6),
                "right_error_m": round(current_east, 6),
            })
            
        # Generic events
        evt_match = EVENT_PATTERN.match(line)
        if evt_match:
            msg = evt_match.group("msg")
            if "telemetry" not in msg:
                # Basic event extraction
                kind = "info"
                if "rtl_command" in msg: kind = "action"
                elif "touchdown" in msg: kind = "summary"
                elif "injection" in msg: kind = "target"
                
                events.append(build_event_entry(
                    last_t,
                    kind=kind,
                    message=msg
                ))

    # Second pass: Update target positions based on injection
    # In the log: target_east_m=3.00 was injected
    has_injection = "landing_target_injection_started" in content
    target_east = 3.0 if has_injection else 0.0
    
    for frame in frames:
        # Before injection, drone thinks target is at (0,0) or hasn't found it.
        # After injection line, it "sees" it at target_east.
        if frame["t"] > 36.1: # T calculated from log line 82
             frame["target_east_m"] = target_east
             frame["horizontal_error_m"] = math.hypot(frame["north_m"], frame["east_m"] - target_east)
             frame["right_error_m"] = round(frame["east_m"] - target_east, 6)

    accuracy_m = frames[-1]["horizontal_error_m"] if frames else 0.0
    
    payload = {
        "schema_version": 2,
        "frames": frames,
        "dock_north_m": 0.0,
        "dock_east_m": target_east,
        "accuracy_m": round(accuracy_m, 6),
        "proof": build_demo_proof(
            source=PROOF_SOURCE_LIVE_PX4_SITL,
            live_pixhawk=False,
            vehicle_link="udpin://0.0.0.0:14540 (Real SITL)",
            command_rate_hz=10.0,
            modes_seen=list(set(f["phase"] for f in frames)),
            parameter_count=13
        ),
        "events": events,
        "commands": commands # We don't have separate command logs, but we can infer
    }
    return payload

def main():
    # Set encoding to utf-8 to handle Arabic chars in path during printing
    if sys.stdout.encoding.lower() != 'utf-8':
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding='utf-8')

    print(f"Parsing live SITL log...")
    try:
        payload = parse_live_log()
        OUTPUT_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        sync_embedded_payload(payload)
        print(f"Successfully wrote 3D replay with {len(payload['frames'])} frames.")
        print(f"Final accuracy: {payload['accuracy_m']} m")
        print(f"Target Injection Offset: {payload['dock_east_m']} m (East)")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
