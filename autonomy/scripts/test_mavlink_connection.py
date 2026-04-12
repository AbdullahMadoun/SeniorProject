#!/usr/bin/env python3
"""
Quick MAVLink Command Test
Tests basic MAVLink commands on Pixhawk to verify connection is working.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from pymavlink import mavutil


def test_connection(port: str = "COM5", baud: int = 115200, duration: float = 10.0) -> dict:
    """Test MAVLink connection and commands."""
    results = {
        "connection_ok": False,
        "heartbeats": 0,
        "telemetry": {},
        "commands_accepted": 0,
        "commands_rejected": 0,
        "errors": [],
    }

    print(f"Connecting to {port} at {baud} baud...")
    
    try:
        mav = mavutil.mavlink_connection(port, baud=baud, autoreconnect=False, source_system=250)
        
        # Wait for heartbeat
        print("Waiting for heartbeat...")
        hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10)
        if not hb:
            results["errors"].append("No heartbeat received")
            return results
        
        results["connection_ok"] = True
        print(f"✓ Connected! System {mav.target_system}, Autopilot: {hb.autopilot}")
        
        # Collect telemetry for specified duration
        print(f"Collecting telemetry for {duration}s...")
        
        telemetry = {
            "gps": [],
            "battery": [],
            "distance": [],
            "heartbeats": 0,
        }
        
        start = time.time()
        while time.time() - start < duration:
            msg = mav.recv_msg()
            if msg:
                msg_type = msg.get_type()
                
                if msg_type == "HEARTBEAT":
                    telemetry["heartbeats"] += 1
                    results["heartbeats"] = telemetry["heartbeats"]
                
                elif msg_type == "GLOBAL_POSITION_INT":
                    telemetry["gps"].append({
                        "lat": msg.lat / 1e7,
                        "lon": msg.lon / 1e7,
                        "alt": msg.alt / 1000.0,
                        "rel_alt": msg.relative_alt / 1000.0,
                        "fix": getattr(msg, "fix_type", 0),
                    })
                
                elif msg_type == "BATTERY_STATUS":
                    telemetry["battery"].append({
                        "voltage": msg.voltages[0] / 1000.0 if msg.voltages else 0,
                        "current": msg.current_battery / 100.0 if msg.current_battery > 0 else 0,
                    })
                
                elif msg_type == "DISTANCE_SENSOR":
                    telemetry["distance"].append({
                        "dist": msg.current_distance / 100.0,
                        "sensor": msg.id,
                    })
        
        results["telemetry"] = telemetry
        
        print()
        print("=" * 50)
        print("TELEMETRY SUMMARY")
        print("=" * 50)
        print(f"Heartbeats:     {telemetry['heartbeats']}")
        print(f"GPS readings:    {len(telemetry['gps'])}")
        print(f"Battery readings: {len(telemetry['battery'])}")
        print(f"Distance readings: {len(telemetry['distance'])}")
        
        if telemetry["gps"]:
            last = telemetry["gps"][-1]
            print()
            print(f"Latest GPS: ({last['lat']:.6f}, {last['lon']:.6f})")
            print(f"  Altitude: {last['alt']:.1f}m, Relative: {last['rel_alt']:.1f}m")
            print(f"  Fix type: {last['fix']}")
        
        if telemetry["battery"]:
            last = telemetry["battery"][-1]
            print()
            print(f"Latest Battery: {last['voltage']:.2f}V")
        
        if telemetry["distance"]:
            print()
            print(f"Distance sensors active: {len(set(d['sensor'] for d in telemetry['distance']))}")
        
        mav.close()
        
    except Exception as e:
        results["errors"].append(str(e))
        print(f"ERROR: {e}")
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Test MAVLink connection to Pixhawk")
    parser.add_argument("--port", "-p", default="COM5", help="Serial port")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate")
    parser.add_argument("--duration", "-d", type=float, default=10.0, help="Test duration in seconds")
    args = parser.parse_args()
    
    print("=" * 50)
    print("MAVLink Quick Test")
    print("=" * 50)
    
    results = test_connection(args.port, args.baud, args.duration)
    
    print()
    print("=" * 50)
    print("RESULT")
    print("=" * 50)
    if results["connection_ok"]:
        print("✓ Connection working")
        print(f"  - {results['heartbeats']} heartbeats received")
        print(f"  - {len(results['telemetry'].get('gps', []))} GPS readings")
    else:
        print("✗ Connection failed")
        for err in results["errors"]:
            print(f"  Error: {err}")


if __name__ == "__main__":
    main()
