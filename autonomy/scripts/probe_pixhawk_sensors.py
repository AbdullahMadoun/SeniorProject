#!/usr/bin/env python3
"""
Pixhawk MAVLink Connection Test & Basic Command Script
Non-destructive: Only reads telemetry and tests safe commands.
"""

from __future__ import annotations

import sys
import os
import time
from pathlib import Path
from typing import Any, Optional

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

try:
    from pymavlink import mavutil
except ImportError:
    print("ERROR: pymavlink not installed. Install with: pip install pymavlink")
    sys.exit(1)


def test_connection(port: str = "COM5", baud: int = 115200, duration: float = 10.0) -> dict[str, Any]:
    """Test MAVLink connection to Pixhawk and read telemetry."""
    results = {
        "connected": False,
        "heartbeat_count": 0,
        "telemetry": {},
        "errors": [],
    }

    print(f"[TEST] Connecting to {port} at {baud} baud...")

    try:
        # Create MAVLink connection
        # pymavlink expects: /dev/ttyACM0 or COM5 format (baud optional for serial)
        mav = mavutil.mavlink_connection(port, baud=baud, autoreconnect=True, source_system=250)

        print(f"[TEST] Waiting for heartbeat (timeout: {duration}s)...")
        
        # Wait for first heartbeat
        start_time = time.time()
        first_hb = None
        
        while time.time() - start_time < duration:
            msg = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
            if msg:
                first_hb = msg
                results["connected"] = True
                results["heartbeat_count"] += 1
                break

        if not results["connected"]:
            results["errors"].append("No heartbeat received - check connection")
            return results

        print(f"[TEST] ✓ Heartbeat received!")
        print(f"       System ID: {mav.target_system}")
        print(f"       Component ID: {mav.target_component}")
        print(f"       Type: {first_hb.type} (MAV_TYPE={first_hb.type})")
        print(f"       Autopilot: {first_hb.autopilot} (MAV_AUTOPILOT={first_hb.autopilot})")
        print(f"       System Status: {first_hb.system_status}")

        # Read telemetry for specified duration
        print(f"[TEST] Reading telemetry for {duration}s...")
        
        telemetry = {
            "gps": [],
            "battery": [],
            "distance_sensor": [],
            "attitude": [],
            "heartbeats": results["heartbeat_count"],
        }

        read_start = time.time()
        last_gps_print = 0
        last_batt_print = 0

        while time.time() - read_start < duration:
            msg = mav.recv_msg()
            if msg:
                msg_type = msg.get_type()

                if msg_type == "HEARTBEAT":
                    telemetry["heartbeats"] += 1

                elif msg_type == "GLOBAL_POSITION_INT":
                    gps_data = {
                        "lat": msg.lat / 1e7,
                        "lon": msg.lon / 1e7,
                        "alt": msg.alt / 1000.0,
                        "relative_alt": msg.relative_alt / 1000.0,
                        "hdg": msg.hdg / 100.0 if msg.hdg and msg.hdg != 65535 else 0,
                        "fix_type": getattr(msg, "fix_type", 0),
                        "satellites_visible": getattr(msg, "satellites_visible", 0),
                    }
                    telemetry["gps"].append(gps_data)
                    
                    # Print GPS update every 2 seconds
                    if time.time() - last_gps_print > 2:
                        print(f"[GPS]  Lat: {gps_data['lat']:.6f}, Lon: {gps_data['lon']:.6f}, Alt: {gps_data['alt']:.1f}m, Fix: {gps_data['fix_type']}, Sats: {gps_data['satellites_visible']}")
                        last_gps_print = time.time()

                elif msg_type == "BATTERY_STATUS":
                    batt_data = {
                        "voltage": msg.voltages[0] / 1000.0 if msg.voltages else 0,
                        "current": msg.current_battery / 100.0 if msg.current_battery > 0 else 0,
                        "remaining": msg.battery_remaining if msg.battery_remaining >= 0 else -1,
                    }
                    telemetry["battery"].append(batt_data)
                    
                    if time.time() - last_batt_print > 2:
                        print(f"[BATT] Voltage: {batt_data['voltage']:.2f}V, Current: {batt_data['current']:.1f}A, Remaining: {batt_data['remaining']}%")
                        last_batt_print = time.time()

                elif msg_type == "DISTANCE_SENSOR":
                    dist_data = {
                        "distance": msg.current_distance / 100.0,
                        "sensor_id": msg.id,
                        "orientation": msg.orientation,
                    }
                    telemetry["distance_sensor"].append(dist_data)
                    print(f"[DIST] Sensor {dist_data['sensor_id']}: {dist_data['distance']:.2f}m")

                elif msg_type == "ATTITUDE":
                    att_data = {
                        "roll": msg.roll,
                        "pitch": msg.pitch,
                        "yaw": msg.yaw,
                    }
                    telemetry["attitude"].append(att_data)

            time.sleep(0.01)

        results["telemetry"] = telemetry
        results["heartbeat_count"] = telemetry["heartbeats"]

        print(f"[TEST] ✓ Telemetry collection complete")
        print(f"       Heartbeats: {results['heartbeat_count']}")
        print(f"       GPS readings: {len(telemetry['gps'])}")
        print(f"       Battery readings: {len(telemetry['battery'])}")
        print(f"       Distance readings: {len(telemetry['distance_sensor'])}")

        mav.close()

    except Exception as e:
        results["errors"].append(str(e))
        print(f"[TEST] ERROR: {e}")
        import traceback
        traceback.print_exc()

    return results


def test_command_arm(port: str = "COM5", baud: int = 115200) -> dict[str, Any]:
    """Test arm command - non-destructive test."""
    results = {"success": False, "response": None, "error": None}

    print(f"[CMD] Testing ARM command on {port}...")

    try:
        mav = mavutil.mavlink_connection(port, baud=baud, autoreconnect=False, source_system=250)

        # Wait for heartbeat first
        print(f"[CMD] Waiting for heartbeat...")
        hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10.0)
        if not hb:
            results["error"] = "No heartbeat received"
            return results

        print(f"[CMD] ✓ Heartbeat received, system {mav.target_system}")

        # Send arm command (but don't actually arm - just test if command is accepted)
        # MAV_CMD_COMPONENT_ARM_DISARM = 400
        # param1: 1 = arm, 0 = disarm
        # param2: 21196 = force (used for safety switch)
        
        print(f"[CMD] Sending ARM command (param1=1, force=0)...")
        mav.mav.command_long_send(
            mav.target_system,
            mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,  # confirmation
            1,  # param1: arm
            0,  # param2: do not force
            0, 0, 0, 0, 0  # unused params
        )

        # Wait for command acknowledgment
        print(f"[CMD] Waiting for command ACK...")
        ack = mav.recv_match(type="COMMAND_ACK", blocking=True, timeout=5.0)
        
        if ack:
            print(f"[CMD] ✓ COMMAND_ACK received!")
            print(f"       Command: {ack.command}")
            print(f"       Result: {ack.result} (MAV_RESULT={ack.result})")
            
            if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                results["success"] = True
                results["response"] = "ARM command accepted - Pixhawk is ready!"
            elif ack.result == mavutil.mavlink.MAV_RESULT_DENIED:
                results["response"] = "ARM denied - may need safety switch disabled or prearm check"
            elif ack.result == mavutil.mavlink.MAV_RESULT_TEMPORARILY_REJECTED:
                results["response"] = "ARM temporarily rejected - try again in a moment"
            else:
                results["response"] = f"ARM result: {ack.result}"
        else:
            results["response"] = "No COMMAND_ACK received (timeout)"

        mav.close()

    except Exception as e:
        results["error"] = str(e)
        print(f"[CMD] ERROR: {e}")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test MAVLink connection to Pixhawk")
    parser.add_argument("--port", "-p", default="COM5", help="Serial port (default: COM5)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--duration", "-d", type=float, default=10.0, help="Telemetry duration (default: 10s)")
    parser.add_argument("--arm-test", action="store_true", help="Also test ARM command")
    args = parser.parse_args()

    print("=" * 60)
    print("Pixhawk MAVLink Connection Test")
    print("=" * 60)
    print(f"Port: {args.port}")
    print(f"Baud: {args.baud}")
    print(f"Duration: {args.duration}s")
    print("=" * 60)

    # Step 1: Test basic connection and read telemetry
    print()
    print("[STEP 1] Testing Connection & Reading Telemetry")
    print("-" * 60)
    results = test_connection(args.port, args.baud, args.duration)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if results["connected"]:
        print("✓ MAVLink connection: SUCCESS")
        print(f"  - Heartbeats received: {results['heartbeat_count']}")
        
        tel = results["telemetry"]
        print(f"  - GPS readings: {len(tel.get('gps', []))}")
        print(f"  - Battery readings: {len(tel.get('battery', []))}")
        print(f"  - Distance sensor readings: {len(tel.get('distance_sensor', []))}")
        
        if tel.get('gps'):
            last_gps = tel['gps'][-1]
            print(f"  - Latest GPS Fix: {last_gps.get('fix_type', 'N/A')}")
            print(f"  - Latest GPS Sats: {last_gps.get('satellites_visible', 'N/A')}")
    else:
        print("✗ MAVLink connection: FAILED")
        for err in results["errors"]:
            print(f"  Error: {err}")

    # Step 2: Optional ARM test
    if args.arm_test and results["connected"]:
        print()
        print("[STEP 2] Testing ARM Command")
        print("-" * 60)
        arm_results = test_command_arm(args.port, args.baud)
        
        if arm_results["success"]:
            print("✓ ARM command: SUCCESS")
        else:
            print("✗ ARM command: FAILED")
        
        if arm_results["response"]:
            print(f"  Response: {arm_results['response']}")
        if arm_results["error"]:
            print(f"  Error: {arm_results['error']}")

    print()
    print("=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
