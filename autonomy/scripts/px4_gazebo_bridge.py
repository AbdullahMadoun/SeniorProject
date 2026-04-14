#!/usr/bin/env python3
"""
PX4-Gazebo HITL Bridge
Bridges MAVLink between Pixhawk (serial) and Gazebo (UDP) for Hardware-In-The-Loop simulation.

Connection:
  Pixhawk (USB) <--serial--> this script <--UDP--> Gazebo

In HITL mode:
  - Gazebo sends HIL_ACTUATOR_CONTROLS (motor outputs) - but Pixhawk computes these
  - Actually in HITL, Pixhawk sends HIL_ACTUATOR_CONTROLS to simulator
  - Simulator sends HIL_SENSOR_DATA, HIL_GPS, HIL_STATE_QUATERNION to Pixhawk
"""

from __future__ import annotations

import sys
import os
import time
import struct
from pathlib import Path
from typing import Any, Optional
import argparse
import threading
import queue

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

try:
    from pymavlink import mavutil
except ImportError:
    print("ERROR: pymavlink not installed")
    sys.exit(1)


class PX4GazeboBridge:
    """Bridges MAVLink between Pixhawk serial and Gazebo UDP."""

    def __init__(
        self,
        serial_port: str = "COM5",
        serial_baud: int = 115200,
        gazebo_ip: str = "127.0.0.1",
        gazebo_port: int = 14560,
        system_id: int = 1,
    ):
        self.serial_port = serial_port
        self.serial_baud = serial_baud
        self.gazebo_ip = gazebo_ip
        self.gazebo_port = gazebo_port
        self.system_id = system_id

        self.serial_mav: Optional[Any] = None
        self.udp_mav: Optional[Any] = None
        self.running = False

        self._serial_thread: Optional[threading.Thread] = None
        self._udp_thread: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()
        self._forward_thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start the bridge."""
        print("=" * 60)
        print("PX4-Gazebo HITL Bridge")
        print("=" * 60)
        print(f"Serial:   {self.serial_port} @ {self.serial_baud}")
        print(f"Gazebo:   {self.gazebo_ip}:{self.gazebo_port}")
        print("=" * 60)

        # Connect to Pixhawk via serial
        print()
        print("[1] Connecting to Pixhawk via serial...")
        try:
            self.serial_mav = mavutil.mavlink_connection(
                self.serial_port,
                baud=self.serial_baud,
                autoreconnect=False,
                source_system=250,
            )
            # Wait for heartbeat
            hb = self.serial_mav.recv_match(type="HEARTBEAT", blocking=True, timeout=10)
            if hb:
                print(f"    ✓ Connected to Pixhawk (System {self.serial_mav.target_system})")
            else:
                print("    ✗ No heartbeat from Pixhawk")
                return False
        except Exception as e:
            print(f"    ✗ Serial connection failed: {e}")
            return False

        # Connect to Gazebo via UDP
        print()
        print("[2] Connecting to Gazebo via UDP...")
        try:
           gazebo_url = f"udp:{self.gazebo_ip}:{self.gazebo_port}"
            self.udp_mav = mavutil.mavlink_connection(
                gazebo_url,
                source_system=255,
                input=False,  # Don't auto-receive, we'll forward
            )
            print(f"    ✓ UDP connection created to {gazebo_url}")
        except Exception as e:
            print(f"    ✗ UDP connection failed: {e}")
            return False

        # Start forwarding threads
        print()
        print("[3] Starting message forwarding...")
        self.running = True

        # Serial -> UDP thread
        self._serial_thread = threading.Thread(target=self._forward_serial_to_udp, daemon=True)
        self._serial_thread.start()
        print("    ✓ Serial → UDP thread started")

        # UDP -> Serial thread
        self._udp_thread = threading.Thread(target=self._forward_udp_to_serial, daemon=True)
        self._udp_thread.start()
        print("    ✓ UDP → Serial thread started")

        print()
        print("[4] Bridge running!")
        print("    - Pixhawk and Gazebo are now connected")
        print("    - Press Ctrl+C to stop")
        print()

        return True

    def _forward_serial_to_udp(self) -> None:
        """Forward messages from Pixhawk serial to Gazebo UDP."""
        print("[Bridge] Serial → UDP forwarding started")
        while self.running:
            try:
                if self.serial_mav:
                    msg = self.serial_mav.recv_msg()
                    if msg:
                        # Forward to Gazebo
                        if self.udp_mav:
                            self.udp_mav.mav.send(msg)
                        # Also print HIL messages for debugging
                        msg_type = msg.get_type()
                        if "HIL" in msg_type or msg_type in ["GLOBAL_POSITION_INT", "HEARTBEAT"]:
                            pass  # Could log here
            except Exception as e:
                print(f"[Bridge] Serial→UDP error: {e}")
            time.sleep(0.001)

    def _forward_udp_to_serial(self) -> None:
        """Forward messages from Gazebo UDP to Pixhawk serial."""
        print("[Bridge] UDP → Serial forwarding started")
        last_status_time = time.time()

        while self.running:
            try:
                if self.udp_mav:
                    # Use recv_match with timeout for non-blocking
                    msg = self.udp_mav.recv_match(blocking=True, timeout=0.1)
                    if msg:
                        # Forward to Pixhawk
                        if self.serial_mav:
                            self.serial_mav.mav.send(msg)

                        # Print debug info every 5 seconds
                        if time.time() - last_status_time > 5:
                            print(f"[Bridge] Forwarded: {msg.get_type()}")
                            last_status_time = time.time()

            except Exception as e:
                print(f"[Bridge] UDP→Serial error: {e}")
            time.sleep(0.001)

    def stop(self) -> None:
        """Stop the bridge."""
        print()
        print("[Bridge] Stopping...")
        self.running = False
        time.sleep(1)
        if self.serial_mav:
            self.serial_mav.close()
        if self.udp_mav:
            self.udp_mav.close()
        print("[Bridge] Stopped")

    def run_forever(self) -> None:
        """Run until interrupted."""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


def main():
    parser = argparse.ArgumentParser(description="PX4-Gazebo HITL Bridge")
    parser.add_argument("--serial", "-s", default="COM5", help="Serial port (default: COM5)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Serial baud (default: 115200)")
    parser.add_argument("--gazebo-ip", "-g", default="127.0.0.1", help="Gazebo IP (default: 127.0.0.1)")
    parser.add_argument("--gazebo-port", "-p", type=int, default=14560, help="Gazebo MAVLink port (default: 14560)")
    args = parser.parse_args()

    bridge = PX4GazeboBridge(
        serial_port=args.serial,
        serial_baud=args.baud,
        gazebo_ip=args.gazebo_ip,
        gazebo_port=args.gazebo_port,
    )

    if bridge.start():
        bridge.run_forever()


if __name__ == "__main__":
    main()
