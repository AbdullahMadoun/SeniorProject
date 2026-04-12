#!/usr/bin/env python3
"""
PX4 Waypoint Mission Test Script
Uploads a waypoint mission to Pixhawk and monitors execution.
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
    print("ERROR: pymavlink not installed")
    sys.exit(1)


# Default test waypoints (relative to home position)
DEFAULT_WAYPOINTS = [
    {"lat": 47.3979710, "lon": 8.5455943, "alt": 20.0},   # Waypoint 1: 20m altitude
    {"lat": 47.3980710, "lon": 8.5460943, "alt": 25.0},   # Waypoint 2: 25m altitude
    {"lat": 47.3978710, "lon": 8.5454943, "alt": 15.0},   # Waypoint 3: 15m altitude
    {"lat": 47.3979710, "lon": 8.5455943, "alt": 10.0},   # Return: 10m altitude
]


def create_mission_message(target_system: int, target_component: int, seq: int, waypoint: dict) -> Any:
    """Create a MISSION_ITEM MAVLink message for a waypoint."""
    msg = mavutil.mavlink.MAVLink_mission_item_message(
        target_system,
        target_component,
        seq,  # sequence number
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,  # frame
        mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,  # command
        0,  # current (0 = not current, 1 = current)
        0 if seq == 0 else 0,  # autocontinue
        0,  # param1: hold time (seconds)
        0,  # param2: acceptance radius (m)
        0,  # param3: 0
        0,  # param4: yaw
        waypoint["lat"],  # x: latitude
        waypoint["lon"],  # y: longitude  
        waypoint["alt"],  # z: altitude (relative)
    )
    return msg


def upload_mission(mav: Any, waypoints: list, home_lat: float, home_lon: float) -> tuple[bool, str]:
    """Upload waypoint mission to Pixhawk."""
    print("[MISSION] Starting mission upload...")
    
    num_items = len(waypoints) + 1  # +1 for home (waypoint 0)
    
    # Send mission count
    print(f"[MISSION] Sending mission count: {num_items}")
    mav.mav.mission_count_send(
        mav.target_system,
        mav.target_component,
        num_items,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    )
    
    # Wait for mission request from Pixhawk
    print("[MISSION] Waiting for MISSION_REQUEST...")
    for i in range(num_items + 5):
        msg = mav.recv_match(type=["MISSION_REQUEST", "MISSION_ACK"], blocking=True, timeout=10)
        if not msg:
            return False, "Timeout waiting for mission request"
        
        if msg.get_type() == "MISSION_ACK":
            return False, f"Mission rejected: {msg.type}"
        
        if msg.get_type() == "MISSION_REQUEST":
            seq = msg.seq
            print(f"[MISSION] Pixhawk requesting waypoint {seq}...")
            
            if seq == 0:
                # Home position
                home_msg = mavutil.mavlink.MAVLink_mission_item_message(
                    mav.target_system,
                    mav.target_component,
                    0,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                    0, 0, 0, 0, 0, 0,
                    home_lat, home_lon, 0,
                )
                mav.mav.send(home_msg)
                print(f"[MISSION] Sent home position: ({home_lat}, {home_lon})")
            else:
                # Regular waypoint
                wp_idx = seq - 1
                if wp_idx < len(waypoints):
                    wp = waypoints[wp_idx]
                    wp_msg = mavutil.mavlink.MAVLink_mission_item_message(
                        mav.target_system,
                        mav.target_component,
                        seq,
                        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                        mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                        0, 0, 0, 0, 0, 0,
                        wp["lat"], wp["lon"], wp["alt"],
                    )
                    mav.mav.send(wp_msg)
                    print(f"[MISSION] Sent waypoint {seq}: ({wp['lat']}, {wp['lon']}, {wp['alt']}m)")
    
    # Wait for mission ack
    msg = mav.recv_match(type="MISSION_ACK", blocking=True, timeout=10)
    if msg:
        print(f"[MISSION] Mission accepted: {msg.type}")
        return True, "Mission uploaded successfully"
    
    return False, "Timeout waiting for mission ack"


def arm_and_start_mission(mav: Any) -> tuple[bool, str]:
    """Arm vehicle and start mission."""
    print()
    print("[MISSION] Arming vehicle...")
    
    # Send arm command
    mav.mav.command_long_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,  # confirmation
        1,  # param1: arm (1 = arm)
        0, 0, 0, 0, 0, 0
    )
    
    # Wait for ack
    ack = mav.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)
    if ack:
        if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            print("[MISSION] ✓ Vehicle armed!")
        else:
            return False, f"Arm denied: {ack.result}"
    
    # Set to auto mission mode
    print("[MISSION] Setting AUTO mode...")
    mav.mav.command_long_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_MODE,
        0,
        mavutil.mavlink.MAV_MODE_FLAG_AUTO_ENABLED,
        0, 0, 0, 0, 0
    )
    
    ack = mav.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)
    if ack:
        print(f"[MISSION] Mode set: {ack.result}")
    
    return True, "Mission started"


def monitor_mission(mav: Any, duration: float = 60.0) -> None:
    """Monitor mission execution."""
    print()
    print("[MONITOR] Monitoring mission execution...")
    print("-" * 60)
    
    start = time.time()
    last_wp = -1
    
    while time.time() - start < duration:
        msg = mav.recv_match(blocking=True, timeout=1)
        if not msg:
            continue
        
        msg_type = msg.get_type()
        
        if msg_type == "GLOBAL_POSITION_INT":
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.alt / 1000.0
            rel_alt = msg.relative_alt / 1000.0
            print(f"[POS] Lat: {lat:.6f}, Lon: {lon:.6f}, Alt: {rel_alt:.1f}m", end="\r")
        
        elif msg_type == "MISSION_CURRENT":
            if msg.seq != last_wp:
                last_wp = msg.seq
                print(f"\n[WPT] Reached waypoint {msg.seq}")
        
        elif msg_type == "HEARTBEAT":
            if msg.system_status == mavutil.mavlink.MAV_STATE_ACTIVE:
                print(f"\n[STATUS] MISSION ACTIVE", end="\r")
        
        elif msg_type == "MISSION_ITEM_REACHED":
            print(f"\n[WPT] ✓ Reached waypoint {msg.seq}")
        
        elif msg_type == "COMMAND_ACK":
            if msg.command == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT:
                print(f"\n[ACK] Waypoint command result: {msg.result}")
    
    print()
    print("-" * 60)
    print("[MONITOR] Monitoring complete")


def test_waypoint_mission(
    port: str = "COM5",
    baud: int = 115200,
    waypoints: list = None,
    monitor_duration: float = 60.0,
) -> dict[str, Any]:
    """Test waypoint mission upload and execution."""
    
    results = {
        "connected": False,
        "mission_uploaded": False,
        "mission_started": False,
        "errors": [],
    }
    
    if waypoints is None:
        waypoints = DEFAULT_WAYPOINTS
    
    print("=" * 60)
    print("PX4 Waypoint Mission Test")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Baud: {baud}")
    print(f"Waypoints: {len(waypoints)}")
    print("=" * 60)
    
    # Connect
    print()
    print("[1] Connecting to Pixhawk...")
    try:
        mav = mavutil.mavlink_connection(port, baud=baud, autoreconnect=False, source_system=250)
        hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10)
        if not hb:
            results["errors"].append("No heartbeat")
            return results
        results["connected"] = True
        print(f"    ✓ Connected (System {mav.target_system})")
    except Exception as e:
        results["errors"].append(f"Connection failed: {e}")
        return results
    
    # Get home position
    print()
    print("[2] Getting home position...")
    home_lat = 47.3979710  # Default (will be replaced by actual)
    home_lon = 8.5455943
    
    # Try to get current position as home
    for _ in range(10):
        msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
        if msg and msg.lat != 0:
            home_lat = msg.lat / 1e7
            home_lon = msg.lon / 1e7
            print(f"    ✓ Home position: ({home_lat}, {home_lon})")
            break
    
    # Upload mission
    print()
    print("[3] Uploading mission...")
    success, msg = upload_mission(mav, waypoints, home_lat, home_lon)
    results["mission_uploaded"] = success
    if not success:
        results["errors"].append(msg)
        return results
    
    # Arm and start mission
    print()
    print("[4] Starting mission...")
    success, msg = arm_and_start_mission(mav)
    results["mission_started"] = success
    if not success:
        results["errors"].append(msg)
    
    # Monitor
    if results["mission_started"]:
        monitor_mission(mav, monitor_duration)
    
    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test waypoint mission on PX4")
    parser.add_argument("--port", "-p", default="COM5", help="Serial port (default: COM5)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--monitor", "-m", type=float, default=60.0, help="Monitor duration (default: 60s)")
    parser.add_argument("--lat", type=float, default=47.3979710, help="Home latitude")
    parser.add_argument("--lon", type=float, default=8.5455943, help="Home longitude")
    args = parser.parse_args()

    # Build waypoints relative to home
    waypoints = [
        {"lat": args.lat + 0.00001, "lon": args.lon + 0.00001, "alt": 20.0},
        {"lat": args.lat + 0.00002, "lon": args.lon + 0.00002, "alt": 25.0},
        {"lat": args.lat + 0.00001, "lon": args.lon + 0.000005, "alt": 15.0},
        {"lat": args.lat, "lon": args.lon, "alt": 10.0},
    ]

    results = test_waypoint_mission(
        port=args.port,
        baud=args.baud,
        waypoints=waypoints,
        monitor_duration=args.monitor,
    )

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Connected:      {'✓' if results['connected'] else '✗'}")
    print(f"Mission Upload: {'✓' if results['mission_uploaded'] else '✗'}")
    print(f"Mission Start: {'✓' if results['mission_started'] else '✗'}")
    for err in results["errors"]:
        print(f"Error: {err}")


if __name__ == "__main__":
    main()
