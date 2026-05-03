#!/usr/bin/env python3
"""
Pixhawk HITL (Hardware In The Loop) Configuration Script
Configures Pixhawk parameters for HITL simulation mode.
"""

from __future__ import annotations

import sys
import os
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

try:
    from pymavlink import mavutil
except ImportError:
    print("ERROR: pymavlink not installed. Install with: pip install pymavlink")
    sys.exit(1)


# HITL Configuration Parameters for Pixhawk4
HITL_PARAMETERS = {
    # Enable HITL mode - this is the main switch
    "SYS_HITL": 2,           # 2 = HITL enabled (1 = disabled)

    # Vehicle type (1=quadrotor, 2=fixed wing, 4=vtol, etc.)
    "SYS_MAV_TYPE": 1,        # 1 = Quadrotor

    # Serial port configuration for MAVLink
    # MAV_0 = USB/Telem1, MAV_1 = Telem2, MAV_2 = GPS
    "MAV_0_MODE": 2,          # 2 = Onboard mode (sends data)
    "MAV_0_FLOW_CTRL": 0,    # No hardware flow control

    # Serial baud rates (typically 57600 for HITL)
    "SER_TEL1_BAUD": 57600,   # Telem1 baud rate

    # EKF configuration - use GPS for position
    "EKF2_AID_MASK": 7,       # 1=GPS, 2=vision, 4=flow (7=all)

    # Disable sensors not available in HITL
    "CAL_GYRO": 0,            # Disable gyro calibration
    "CAL_ACC0": 0,            # Disable accel calibration
    "CAL_MAG0": 0,            # Disable mag calibration

    # Battery simulation (if no real battery)
    "BAT1_SOURCE": 0,         # 0 = ADC battery, 1 = ESC battery
}

# Simulation engine selection
SIMULATION_ENGINES = {
    "gazebo": {
        "name": "Gazebo",
        "description": "3D robot simulator with SITL/HITL support",
        "default_port": 14560,  # MAVLink TCP port
    },
    "jsbsim": {
        "name": "JSBSim",
        "description": "Fixed-wing flight simulator",
        "default_port": 4560,
    },
    "flightgear": {
        "name": "FlightGear",
        "description": "Flight simulator with MAVLink support",
        "default_port": 4560,
    },
}


def get_current_parameters(mav: Any) -> dict[str, tuple[Any, str]]:
    """Read current parameters from Pixhawk."""
    print("[PARAM] Requesting all parameters (this may take a moment)...")
    
    params = {}
    start = time.time()
    timeout = 60.0
    
    # Use recv_msg to get all messages
    while time.time() - start < timeout:
        msg = mav.recv_msg()
        if msg and msg.get_type() == "PARAM_VALUE":
            # Handle both bytes and string param_id
            param_id = msg.param_id
            if isinstance(param_id, bytes):
                param_id = param_id.decode().rstrip('\x00')
            else:
                param_id = param_id.rstrip('\x00')
            params[param_id] = (msg.param_value, "current")
            
            if len(params) % 100 == 0:
                print(f"[PARAM] Received {len(params)} parameters...")
            
            # Check if we have all parameters
            if msg.param_count > 0 and len(params) >= msg.param_count:
                break
        
        time.sleep(0.01)
    
    print(f"[PARAM] Total parameters received: {len(params)}")
    return params


def read_parameter(mav: Any, param_name: str) -> tuple[bool, Any]:
    """Read a single parameter via MAVLink."""
    try:
        # Try using mavutil's method if available
        if hasattr(mav, 'param_fetch_one'):
            mav.param_fetch_one(param_name)
            start = time.time()
            while time.time() - start < 5.0:
                msg = mav.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
                if msg and msg.param_id.rstrip('\x00') == param_name:
                    return True, msg.param_value
        else:
            # Manual approach for serial connections
            mav.mav.param_set_send(
                mav.target_system,
                mav.target_component,
                param_name.encode(),
                0,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )
            start = time.time()
            while time.time() - start < 5.0:
                msg = mav.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
                if msg and msg.param_id.rstrip('\x00') == param_name:
                    return True, msg.param_value
        return False, None
    except Exception as e:
        print(f"[PARAM] Error reading {param_name}: {e}")
        return False, None


def set_parameter(mav: Any, param_name: str, value: Any, retries: int = 3) -> tuple[bool, str]:
    """Set a parameter on Pixhawk with retries."""
    for attempt in range(retries):
        try:
            if isinstance(param_name, str):
                param_name_bytes = param_name.encode('utf-8')
            else:
                param_name_bytes = param_name
            
            print(f"       Attempt {attempt + 1}/{retries}: Sending {param_name} = {value}")
            
            mav.mav.param_set_send(
                mav.target_system,
                mav.target_component,
                param_name_bytes,
                float(value),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            )
            
            # Wait for acknowledgment with longer timeout
            start = time.time()
            while time.time() - start < 10.0:
                msg = mav.recv_match(type=["PARAM_VALUE", "COMMAND_ACK"], blocking=True, timeout=1.0)
                if msg:
                    if msg.get_type() == "PARAM_VALUE":
                        pid = msg.param_id
                        if isinstance(pid, bytes):
                            pid = pid.decode('utf-8').rstrip('\x00')
                        else:
                            pid = pid.rstrip('\x00')
                        if pid == param_name_bytes.decode('utf-8').rstrip('\x00'):
                            print(f"       ✓ Received PARAM_VALUE for {param_name}")
                            return True, f"Set {param_name} = {value}"
                    elif msg.get_type() == "COMMAND_ACK":
                        print(f"       ✓ Received COMMAND_ACK: result={msg.result}")
                        if msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                            return True, f"Set {param_name} = {value}"
                        else:
                            return False, f"Set rejected: result={msg.result}"
                
                time.sleep(0.1)
            
            print(f"       Timeout on attempt {attempt + 1}")
            
        except Exception as e:
            print(f"       Error on attempt {attempt + 1}: {e}")
        
        if attempt < retries - 1:
            time.sleep(1)
    
    return False, f"Failed to set {param_name} after {retries} attempts"


def configure_hitl(mav: Any, dry_run: bool = True) -> dict[str, Any]:
    """Configure Pixhawk for HITL mode."""
    results = {
        "dry_run": dry_run,
        "changes": [],
        "errors": [],
    }
    
    print(f"[HITL] {'DRY RUN' if dry_run else 'APPLYING'} - HITL Configuration")
    print("=" * 60)
    
    for param, value in HITL_PARAMETERS.items():
        status = "[DRY]" if dry_run else "[SET]"
        print(f"{status} {param} = {value}")
        
        if not dry_run:
            success, msg = set_parameter(mav, param, value)
            results["changes"].append({"param": param, "value": value, "success": success})
            if success:
                print(f"       ✓ {msg}")
            else:
                print(f"       ✗ {msg}")
                results["errors"].append(msg)
        
        time.sleep(0.5)  # Rate limit parameter sets
    
    return results


def check_hitl_status(mav: Any) -> dict[str, Any]:
    """Check current HITL status of Pixhawk."""
    status = {
        "SYS_HITL": None,
        "SYS_MAV_TYPE": None,
        "MAV_0_MODE": None,
        "connected": False,
    }
    
    # Read key parameters
    for param in ["SYS_HITL", "SYS_MAV_TYPE", "MAV_0_MODE"]:
        success, value = read_parameter(mav, param)
        if success:
            status[param] = value
            print(f"[CHECK] {param} = {value}")
        else:
            print(f"[CHECK] {param} = (could not read)")
    
    status["connected"] = True
    return status


def enable_hitl_mode(port: str = "COM5", baud: int = 115200, dry_run: bool = True) -> dict[str, Any]:
    """Connect to Pixhawk and configure HITL mode."""
    results = {"success": False, "steps": []}
    
    print(f"[HITL] Connecting to Pixhawk on {port}...")
    
    try:
        mav = mavutil.mavlink_connection(port, baud=baud, autoreconnect=False, source_system=250)
        
        # Wait for heartbeat
        print("[HITL] Waiting for heartbeat...")
        hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10.0)
        if not hb:
            results["error"] = "No heartbeat received"
            return results
        
        print(f"[HITL] ✓ Connected to Pixhawk (System {mav.target_system})")
        print(f"       Autopilot: {hb.autopilot} (12=PX4)")
        print(f"       Type: {hb.type}")
        
        # Check current HITL status
        print()
        print("[STEP 1] Checking current HITL status...")
        print("-" * 40)
        current_status = check_hitl_status(mav)
        
        # Configure HITL
        print()
        print("[STEP 2] Configuring HITL parameters...")
        print("-" * 40)
        config_result = configure_hitl(mav, dry_run=dry_run)
        
        results["success"] = True
        results["steps"].append({"name": "connect", "success": True})
        results["steps"].append({"name": "check_status", "success": current_status["connected"]})
        results["steps"].append({"name": "configure", "success": len(config_result["errors"]) == 0})
        results["current_status"] = current_status
        results["config_result"] = config_result
        
        mav.close()
        
    except Exception as e:
        results["error"] = str(e)
        print(f"[HITL] ERROR: {e}")
    
    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Configure Pixhawk for HITL simulation")
    parser.add_argument("--port", "-p", default="COM5", help="Serial port (default: COM5)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--status-only", action="store_true", help="Only check status, don't configure")
    args = parser.parse_args()

    print("=" * 60)
    print("Pixhawk HITL Configuration Tool")
    print("=" * 60)
    print(f"Port: {args.port}")
    print(f"Baud: {args.baud}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print("=" * 60)

    if args.status_only:
        print()
        print("[MODE] Status Check Only")
        print("-" * 60)
        # Just connect and check status
        try:
            mav = mavutil.mavlink_connection(args.port, baud=args.baud, autoreconnect=False, source_system=250)
            hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10.0)
            if hb:
                print(f"✓ Connected to Pixhawk (System {mav.target_system})")
                check_hitl_status(mav)
            mav.close()
        except Exception as e:
            print(f"✗ Connection failed: {e}")
    else:
        print()
        enable_hitl_mode(port=args.port, baud=args.baud, dry_run=not args.apply)

    print()
    print("=" * 60)
    print("Done")
    print("=" * 60)


if __name__ == "__main__":
    main()
