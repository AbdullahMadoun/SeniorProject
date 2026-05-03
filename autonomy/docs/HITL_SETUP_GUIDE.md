# PX4 HITL Simulation Setup Guide

## Overview

This guide sets up Hardware-In-The-Loop (HITL) simulation where:
- **Pixhawk4** runs real PX4 firmware with HITL enabled
- **Gazebo** provides simulated flight environment
- **MAVLink** bridges Pixhawk serial to Gazebo UDP

## Prerequisites

1. Pixhawk4 connected via USB to COM5
2. QGroundControl (for initial HITL configuration)
3. PX4 Firmware with HITL support
4. Gazebo + PX4 SITL/HITL plugin

## Step 1: Enable HITL Mode (Already Done via QGroundControl)

In QGroundControl:
1. Go to **Setup → Parameters**
2. Set **SYS_HITL** = 2
3. Save and reboot Pixhawk

## Step 2: Verify Connection

Close QGroundControl, then run:

```bash
python autonomy/scripts/test_mavlink_connection.py --port COM5 --duration 10
```

Expected output:
```
✓ Connected! System 1, Autopilot: 12
Heartbeats: 10
GPS readings: 10
...
```

## Step 3: Test Waypoint Mission

With Pixhawk connected and in HITL mode (or normal mode for testing):

```bash
python autonomy/scripts/test_waypoint_mission.py --port COM5 --duration 60
```

This will:
1. Upload 4 waypoint mission
2. Arm the vehicle
3. Set to AUTO mode
4. Monitor execution for 60 seconds

## Step 4: Run Gazebo HITL (Requires Gazebo Installation)

### Option A: Gazebo with PX4

```bash
# In one terminal - Start Gazebo HITL
cd /path/to/PX4-Autopilot
make px4_sitl_default gazebo

# In another terminal - Start bridge
python autonomy/scripts/px4_gazebo_bridge.py --serial COM5 --baud 115200
```

### Option B: JSBSim (Fixed Wing)

```bash
# Start JSBSim with MAVLink
jsbsim --simulation、消防 [--mavlink | --script=px4.xml]
```

## Architecture

```
┌─────────────┐    Serial USB    ┌─────────────────┐    UDP    ┌─────────┐
│  Pixhawk4   │ ←──────────────→ │ px4_gazebo_     │ ←────────→ │ Gazebo  │
│  (HITL)     │    115200 baud   │ bridge.py        │  14560    │  HITL   │
└─────────────┘                  └─────────────────┘            └─────────┘
                                            ↑
                                            │
                                    MAVLink Commands
                                    (ARM, Waypoints,
                                     Mission Upload)
```

## Troubleshooting

### "Permission denied" on COM5
- QGroundControl or another program has the port open
- Close all ground station software

### No heartbeats
- Check USB cable
- Check Pixhawk is powered
- Verify correct COM port

### Parameters won't set
- Use QGroundControl to set parameters
- Some parameters require reboot to take effect

### Gazebo not receiving data
- Check firewall allows UDP port 14560
- Verify Gazebo is running PX4 SITL model

## Scripts Available

| Script | Purpose |
|--------|---------|
| `test_mavlink_connection.py` | Verify MAVLink connection works |
| `test_waypoint_mission.py` | Upload and test waypoint mission |
| `px4_gazebo_bridge.py` | Bridge MAVLink between Pixhawk and Gazebo |
| `probe_pixhawk_sensors.py` | Probe for connected sensors |

## For Waypoint Testing Without Gazebo

You can test waypoint missions in these modes:

1. **Normal Flight Mode** - Real GPS, fly actual mission
2. **HITL Mode** - Pixhawk uses simulated data from this script
3. **SITL Mode** - px4 runs on computer, no Pixhawk needed

Start with `test_waypoint_mission.py` to verify your Pixhawk accepts missions!
