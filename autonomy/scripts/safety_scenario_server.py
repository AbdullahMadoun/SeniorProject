"""
Safety Scenario Server - Real-time 3D visualization of RTL scenarios

Run this server, then open the dashboard to see scenarios in 3D:
    python safety_scenario_server.py --scenario battery_rtl

Then open: http://127.0.0.1:5000/artifacts/dashboard/index.html

Scenarios:
    battery_rtl   - Battery at 19% triggers RTL during flight
    wind_rtl      - Wind at 8.5 m/s triggers RTL during flight  
    battery_emergency - Battery at 8% triggers immediate LAND_NOW
    high_wind_abort   - Wind at 9 m/s aborts preflight launch
    battery_warn      - Battery at 25% triggers warning (continues mission)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import threading
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable
from flask import Flask, Response, jsonify, request
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.safety_engine import (
    MissionSafetyEngine,
    SafetyAction,
    SafetyReason,
)
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import VehicleMode, Waypoint

app = Flask(__name__)

baseline = load_system_baseline()
SIMULATION_FPS = 10  # Telemetry update rate
MISSION_RADIUS_M = 50.0  # Mission orbit radius from home


@dataclass
class SimFrame:
    elapsed_s: float
    lat_deg: float
    lon_deg: float
    alt_m: float
    heading_deg: float
    battery_percent: float
    wind_speed_mps: float
    mode: str
    action: str
    event: str | None
    safety_state: str


class SafetyScenarioServer:
    def __init__(self, scenario_name: str) -> None:
        self.scenario_name = scenario_name
        self.baseline = load_system_baseline()
        self.engine = MissionSafetyEngine(self.baseline)
        self.frames: list[SimFrame] = []
        self.events: list[dict] = []
        self._running = False
        self._current_frame = 0
        self._start_time = 0.0
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[SimFrame], None]] = []

    def subscribe(self, callback: Callable[[SimFrame], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[SimFrame], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _emit_frame(self, frame: SimFrame) -> None:
        for sub in self._subscribers:
            try:
                sub(frame)
            except Exception:
                pass

    def _add_event(self, elapsed: float, event_type: str, message: str) -> None:
        self.events.append({"t": elapsed, "type": event_type, "message": message})

    async def run_battery_rtl(self) -> list[SimFrame]:
        """Battery at 19% triggers RTL during flight"""
        self._running = True
        self._start_time = time.time()
        gateway = InMemoryVehicleGateway(self.baseline)
        mission = self._create_mission()
        geofence = build_home_geofence(self.baseline.home, self.baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await gateway.arm()
        await gateway.start_mission()

        self._add_event(0, "mode", "Mission execution started")
        yield self._make_frame(0, gateway, 100.0, 3.0, "auto_mission", None)

        # Fly normal mission for a bit
        for i in range(20):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(19.0, 100.0 - (i * 0.5))
            mode = "auto_mission"
            event = None
            
            if battery <= 25.0 and battery > 19.0:
                if i == 15:
                    event = "battery_warning"
                    self._add_event(time.time() - self._start_time, "battery", f"Battery warning: {battery:.0f}%")
            
            yield self._make_frame(time.time() - self._start_time, gateway, battery, 3.0, mode, event)

        # Battery drops to RTL threshold
        gateway.snapshot = gateway.snapshot.__class__(
            connected=True, armed=True, in_air=True, mode=VehicleMode.MISSION,
            battery_percent=19.0, position=gateway.snapshot.position,
            mission_progress=gateway.snapshot.mission_progress,
        )

        decision = await self.engine.enforce_inflight_policy(gateway, wind_mps=3.0)
        if decision.action == SafetyAction.RETURN_TO_LAUNCH:
            await gateway.return_to_launch()
            self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered at {19.0:.0f}% battery")
            yield self._make_frame(time.time() - self._start_time, gateway, 19.0, 3.0, "return_to_launch", "rtl_triggered")

        # Simulate return flight
        for i in range(30):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 30.0
            lat = self.baseline.home.lat + (0.0001 * (1 - progress))
            lon = self.baseline.home.lon + (0.0001 * (1 - progress))
            pos = Waypoint(lat=lat, lon=lon, alt_m=25.0 - (5.0 * progress))
            gateway.snapshot = gateway.snapshot.__class__(
                connected=True, armed=True, in_air=True, mode=VehicleMode.RETURN_TO_LAUNCH,
                battery_percent=19.0 - (i * 0.1), position=pos,
                mission_progress=gateway.snapshot.mission_progress,
            )
            yield self._make_frame(time.time() - self._start_time, gateway, 19.0 - (i * 0.1), 3.0, "return_to_launch", None)

        self._running = False
        return self.frames

    async def run_wind_rtl(self) -> list[SimFrame]:
        """Wind at 8.5 m/s triggers RTL during flight"""
        self._running = True
        self._start_time = time.time()
        gateway = InMemoryVehicleGateway(self.baseline)
        mission = self._create_mission()
        geofence = build_home_geofence(self.baseline.home, self.baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await gateway.arm()
        await gateway.start_mission()

        self._add_event(0, "mode", "Mission execution started")

        # Fly normal mission
        for i in range(20):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            wind = 3.0 + (i * 0.1)
            event = None
            if wind >= 7.0 and i == 15:
                event = "wind_warning"
                self._add_event(time.time() - self._start_time, "wind", f"Wind increasing: {wind:.1f} m/s")
            yield self._make_frame(time.time() - self._start_time, gateway, 75.0, wind, "auto_mission", event)

        # Wind exceeds limit
        gateway.snapshot = gateway.snapshot.__class__(
            connected=True, armed=True, in_air=True, mode=VehicleMode.MISSION,
            battery_percent=75.0, position=gateway.snapshot.position,
            mission_progress=gateway.snapshot.mission_progress,
        )

        wind_mps = 8.5
        decision = await self.engine.enforce_inflight_policy(gateway, wind_mps=wind_mps)
        if decision.action == SafetyAction.RETURN_TO_LAUNCH:
            await gateway.return_to_launch()
            self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered - Wind {wind_mps:.1f} m/s exceeds limit")
            yield self._make_frame(time.time() - self._start_time, gateway, 75.0, wind_mps, "return_to_launch", "rtl_triggered")

        # Simulate return flight
        for i in range(30):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 30.0
            lat = self.baseline.home.lat + (0.0001 * (1 - progress))
            lon = self.baseline.home.lon + (0.0001 * (1 - progress))
            pos = Waypoint(lat=lat, lon=lon, alt_m=25.0 - (5.0 * progress))
            gateway.snapshot = gateway.snapshot.__class__(
                connected=True, armed=True, in_air=True, mode=VehicleMode.RETURN_TO_LAUNCH,
                battery_percent=75.0 - (i * 0.05), position=pos,
                mission_progress=gateway.snapshot.mission_progress,
            )
            yield self._make_frame(time.time() - self._start_time, gateway, 75.0 - (i * 0.05), wind_mps, "return_to_launch", None)

        self._running = False
        return self.frames

    async def run_battery_emergency(self) -> list[SimFrame]:
        """Battery at 8% triggers immediate LAND_NOW"""
        self._running = True
        self._start_time = time.time()
        gateway = InMemoryVehicleGateway(self.baseline)
        mission = self._create_mission()
        geofence = build_home_geofence(self.baseline.home, self.baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await gateway.arm()
        await gateway.start_mission()

        self._add_event(0, "mode", "Mission execution started")

        # Fly until critical battery
        for i in range(30):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(8.0, 100.0 - (i * 3.0))
            event = None
            if battery <= 10.0 and i >= 25:
                event = "emergency"
            yield self._make_frame(time.time() - self._start_time, gateway, battery, 3.0, "auto_mission", event)

        # Critical battery - trigger LAND_NOW
        gateway.snapshot = gateway.snapshot.__class__(
            connected=True, armed=True, in_air=True, mode=VehicleMode.MISSION,
            battery_percent=8.0, position=gateway.snapshot.position,
            mission_progress=gateway.snapshot.mission_progress,
        )

        decision = await self.engine.enforce_inflight_policy(gateway, wind_mps=3.0)
        if decision.action == SafetyAction.LAND_NOW:
            await gateway.land()
            self._add_event(time.time() - self._start_time, "land", f"EMERGENCY LANDING at {8.0:.0f}% battery")
            yield self._make_frame(time.time() - self._start_time, gateway, 8.0, 3.0, "land", "emergency_land")

        # Simulate descent
        for i in range(20):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            alt = max(0.0, 25.0 - (i * 1.25))
            pos = Waypoint(lat=gateway.snapshot.position.lat, lon=gateway.snapshot.position.lon, alt_m=alt)
            gateway.snapshot = gateway.snapshot.__class__(
                connected=True, armed=False, in_air=(alt > 0), mode=VehicleMode.LAND,
                battery_percent=8.0, position=pos,
                mission_progress=gateway.snapshot.mission_progress,
            )
            yield self._make_frame(time.time() - self._start_time, gateway, 8.0, 3.0, "land", None)

        self._running = False
        return self.frames

    async def run_high_wind_abort(self) -> list[SimFrame]:
        """Wind at 9 m/s aborts preflight launch"""
        self._running = True
        self._start_time = time.time()
        gateway = InMemoryVehicleGateway(self.baseline)
        mission = self._create_mission()
        geofence = build_home_geofence(self.baseline.home, self.baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)

        self._add_event(0, "mode", "Preflight checks...")
        yield self._make_frame(time.time() - self._start_time, gateway, 100.0, 9.0, "hold", None)

        # High wind detected at preflight
        wind_mps = 9.0
        decision = await self.engine.assess_preflight_from_gateway(gateway, mission, wind_mps=wind_mps)
        if decision.action == SafetyAction.ABORT_LAUNCH:
            self._add_event(time.time() - self._start_time, "abort", f"LAUNCH ABORTED - Wind {wind_mps:.1f} m/s exceeds limit")
            yield self._make_frame(time.time() - self._start_time, gateway, 100.0, wind_mps, "hold", "launch_aborted")

        # Stay in hold
        for i in range(10):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            yield self._make_frame(time.time() - self._start_time, gateway, 100.0, wind_mps, "hold", None)

        self._running = False
        return self.frames

    async def run_battery_warn(self) -> list[SimFrame]:
        """Battery at 25% triggers warning but mission continues"""
        self._running = True
        self._start_time = time.time()
        gateway = InMemoryVehicleGateway(self.baseline)
        mission = self._create_mission()
        geofence = build_home_geofence(self.baseline.home, self.baseline.mission_limits.max_radius_m)

        await gateway.connect()
        await gateway.upload_geofence(geofence)
        await gateway.upload_mission(mission)
        await gateway.arm()
        await gateway.start_mission()

        self._add_event(0, "mode", "Mission execution started")

        # Battery draining
        for i in range(50):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(20.0, 100.0 - (i * 1.5))
            event = None
            if battery <= 25.0 and battery > 20.0 and i >= 40:
                event = "battery_warning"
                self._add_event(time.time() - self._start_time, "battery", f"Battery warning: {battery:.0f}%")
            yield self._make_frame(time.time() - self._start_time, gateway, battery, 3.0, "auto_mission", event)

            # At 20%, RTL kicks in
            if battery <= 20.0:
                gateway.snapshot = gateway.snapshot.__class__(
                    connected=True, armed=True, in_air=True, mode=VehicleMode.MISSION,
                    battery_percent=battery, position=gateway.snapshot.position,
                    mission_progress=gateway.snapshot.mission_progress,
                )
                decision = await self.engine.enforce_inflight_policy(gateway, wind_mps=3.0)
                if decision.action == SafetyAction.RETURN_TO_LAUNCH:
                    await gateway.return_to_launch()
                    self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered at {battery:.0f}%")
                    yield self._make_frame(time.time() - self._start_time, gateway, battery, 3.0, "return_to_launch", "rtl_triggered")
                    break

        # Complete mission
        for i in range(20):
            if not self._running:
                break
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 20.0
            lat = self.baseline.home.lat + (0.0001 * progress)
            lon = self.baseline.home.lon + (0.0001 * progress)
            pos = Waypoint(lat=lat, lon=lon, alt_m=25.0)
            gateway.snapshot = gateway.snapshot.__class__(
                connected=True, armed=True, in_air=True, mode=VehicleMode.MISSION,
                battery_percent=20.0, position=pos,
                mission_progress=gateway.snapshot.mission_progress,
            )
            yield self._make_frame(time.time() - self._start_time, gateway, 20.0, 3.0, "auto_mission", None)

        self._running = False
        return self.frames

    def _create_mission(self) -> MissionPlanRequest:
        return MissionPlanRequest(
            mission_id=f"scenario-{self.scenario_name}",
            home=self.baseline.home,
            waypoints=(
                Waypoint(lat=26.307150, lon=50.145900, alt_m=25.0),
                Waypoint(lat=26.307220, lon=50.146060, alt_m=25.0),
            ),
            cruise_speed_mps=self.baseline.speed_band.nominal_mps,
        )

    def _make_frame(self, elapsed: float, gateway: InMemoryVehicleGateway,
                    battery: float, wind: float, mode: str, event: str | None) -> SimFrame:
        pos = gateway.snapshot.position
        frame = SimFrame(
            elapsed_s=elapsed,
            lat_deg=pos.lat if pos else self.baseline.home.lat,
            lon_deg=pos.lon if pos else self.baseline.home.lon,
            alt_m=pos.alt_m if pos else self.baseline.home.alt_m,
            heading_deg=90.0,
            battery_percent=battery,
            wind_speed_mps=wind,
            mode=mode,
            action="continue",
            event=event,
            safety_state="nominal" if event is None else event,
        )
        self.frames.append(frame)
        self._emit_frame(frame)
        return frame

    def stop(self) -> None:
        self._running = False

    def get_state(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "running": self._running,
            "frame_count": len(self.frames),
            "events": self.events,
            "baseline": {
                "battery_warn_percent": self.baseline.safety.battery_warn_percent,
                "battery_rtl_percent": self.baseline.safety.battery_rtl_percent,
                "battery_emergency_percent": self.baseline.safety.battery_emergency_percent,
                "max_operating_wind_mps": self.baseline.safety.max_operating_wind_mps,
                "home_lat": self.baseline.home.lat,
                "home_lon": self.baseline.home.lon,
            }
        }


# Global state
current_scenario: SafetyScenarioServer | None = None
sse_clients: list[threading.Event] = []


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.route("/api/safety/scenarios")
def list_scenarios():
    return jsonify({
        "scenarios": [
            {"id": "battery_rtl", "name": "Battery RTL", "description": "Battery at 19% triggers RTL"},
            {"id": "wind_rtl", "name": "Wind RTL", "description": "Wind at 8.5 m/s triggers RTL"},
            {"id": "battery_emergency", "name": "Emergency Land", "description": "Battery at 8% triggers LAND_NOW"},
            {"id": "high_wind_abort", "name": "Launch Abort", "description": "Wind at 9 m/s aborts launch"},
            {"id": "battery_warn", "name": "Battery Warning", "description": "Battery at 25% triggers warning"},
        ]
    })


@app.route("/api/safety/start", methods=["POST"])
def start_scenario():
    global current_scenario
    data = request.get_json() or {}
    scenario_name = data.get("scenario", "battery_rtl")

    if current_scenario:
        current_scenario.stop()

    async def run_async():
        global current_scenario
        sc = SafetyScenarioServer(scenario_name)
        current_scenario = sc

        if scenario_name == "battery_rtl":
            await sc.run_battery_rtl()
        elif scenario_name == "wind_rtl":
            await sc.run_wind_rtl()
        elif scenario_name == "battery_emergency":
            await sc.run_battery_emergency()
        elif scenario_name == "high_wind_abort":
            await sc.run_high_wind_abort()
        elif scenario_name == "battery_warn":
            await sc.run_battery_warn()

    threading.Thread(target=lambda: asyncio.run(run_async()), daemon=True).start()
    return jsonify({"status": "started", "scenario": scenario_name})


@app.route("/api/safety/stop", methods=["POST"])
def stop_scenario():
    global current_scenario
    if current_scenario:
        current_scenario.stop()
    return jsonify({"status": "stopped"})


@app.route("/api/safety/state")
def get_state():
    if current_scenario:
        return jsonify(current_scenario.get_state())
    return jsonify({"scenario": None, "running": False})


@app.route("/api/safety/stream")
def safety_stream():
    def generate():
        client_done = threading.Event()
        sse_clients.append(client_done)

        def on_frame(frame: SimFrame):
            for client in sse_clients:
                client.set()

        if current_scenario:
            current_scenario.subscribe(on_frame)

        try:
            while True:
                client_done.wait(timeout=30.0)
                client_done.clear()
                if current_scenario:
                    state = current_scenario.get_state()
                    if state["frames"]:
                        last_frame = state["frames"][-1]
                        yield sse_event({
                            "frame": asdict(last_frame),
                            "events": state["events"],
                            "baseline": state["baseline"]
                        })
                    if not state["running"] and state["frame_count"] > 0:
                        yield sse_event({"status": "complete", "events": state["events"]})
                        break
                else:
                    yield sse_event({"status": "waiting"})
        finally:
            if current_scenario:
                current_scenario.unsubscribe(on_frame)
            if client_done in sse_clients:
                sse_clients.remove(client_done)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/safety/telemetry")
def telemetry_stream():
    """Simplified telemetry for dashboard compatibility"""
    def generate():
        while True:
            if current_scenario and current_scenario.frames:
                frame = current_scenario.frames[-1]
                state = current_scenario.get_state()

                # Build telemetry frame compatible with dashboard
                tel = {
                    "elapsed_s": frame.elapsed_s,
                    "lat_deg": frame.lat_deg,
                    "lon_deg": frame.lon_deg,
                    "alt_m": frame.alt_m,
                    "heading_deg": frame.heading_deg,
                    "battery_percent": frame.battery_percent,
                    "wind_speed_mps": frame.wind_speed_mps,
                    "mode": frame.mode,
                    "horizontal_distance_to_dock_m": 50.0,
                    "vertical_distance_to_dock_m": frame.alt_m,
                    "dock_lat": baseline.home.lat,
                    "dock_lon": baseline.home.lon,
                }
                yield sse_event(tel)
            time.sleep(1.0 / SIMULATION_FPS)

    return Response(generate(), mimetype="text/event-stream")


# Dashboard integration routes
@app.route("/artifacts/dashboard/<path:filename>")
def serve_dashboard(filename):
    from flask import send_from_directory
    dashboard_dir = Path(__file__).resolve().parents[1] / "artifacts" / "dashboard"
    return send_from_directory(str(dashboard_dir), filename)


@app.route("/")
def index():
    return """
    <html><head><title>SkyLink2 Safety Scenario Simulator</title></head>
    <body style="font-family: Arial; background: #0a0a0f; color: #fff; padding: 40px;">
    <h1 style="color: #00d4aa;">SkyLink2 Safety Scenario Simulator</h1>
    <p>Real-time 3D visualization of RTL safety scenarios</p>

    <h2>Available Scenarios</h2>
    <ul>
        <li><b>Battery RTL:</b> Battery at 19% triggers Return-to-Launch</li>
        <li><b>Wind RTL:</b> Wind at 8.5 m/s triggers Return-to-Launch</li>
        <li><b>Emergency Land:</b> Battery at 8% triggers immediate LAND_NOW</li>
        <li><b>Launch Abort:</b> Wind at 9 m/s aborts preflight launch</li>
        <li><b>Battery Warning:</b> Battery at 25% triggers warning (mission continues)</li>
    </ul>

    <h2>Controls</h2>
    <div style="margin: 20px 0;">
        <button onclick="startScenario('battery_rtl')" style="padding: 15px 30px; margin: 5px; font-size: 16px; background: #00d4aa; border: none; border-radius: 8px; cursor: pointer;">Battery RTL</button>
        <button onclick="startScenario('wind_rtl')" style="padding: 15px 30px; margin: 5px; font-size: 16px; background: #53b7ff; border: none; border-radius: 8px; cursor: pointer;">Wind RTL</button>
        <button onclick="startScenario('battery_emergency')" style="padding: 15px 30px; margin: 5px; font-size: 16px; background: #ff6b7a; border: none; border-radius: 8px; cursor: pointer;">Emergency Land</button>
        <button onclick="startScenario('high_wind_abort')" style="padding: 15px 30px; margin: 5px; font-size: 16px; background: #ffb454; border: none; border-radius: 8px; cursor: pointer;">Launch Abort</button>
        <button onclick="startScenario('battery_warn')" style="padding: 15px 30px; margin: 5px; font-size: 16px; background: #98a4b7; border: none; border-radius: 8px; cursor: pointer;">Battery Warning</button>
    </div>

    <div id="status" style="margin: 20px 0; padding: 15px; background: #1a1a2e; border-radius: 8px;">
        Status: <span id="status-text">Ready</span>
    </div>

    <div id="events" style="margin: 20px 0; padding: 15px; background: #1a1a2e; border-radius: 8px; max-height: 200px; overflow-y: auto;">
        <h3>Events</h3>
        <ul id="event-list"></ul>
    </div>

    <h2>3D Dashboard</h2>
    <p><a href="/artifacts/dashboard/index.html" target="_blank" style="color: #00d4aa; font-size: 18px;">Open 3D Dashboard →</a></p>

    <script>
    let eventSource = null;

    function startScenario(scenario) {
        document.getElementById('status-text').textContent = 'Starting ' + scenario + '...';

        fetch('/api/safety/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scenario: scenario})
        }).then(r => r.json()).then(data => {
            document.getElementById('status-text').textContent = 'Running: ' + data.scenario;
            if (eventSource) eventSource.close();
            eventSource = new EventSource('/api/safety/stream');
            eventSource.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.events) {
                    const list = document.getElementById('event-list');
                    list.innerHTML = data.events.map(ev =>
                        `<li>[${ev.t.toFixed(1)}s] <b>${ev.type}</b>: ${ev.message}</li>`
                    ).join('');
                }
                if (data.status === 'complete') {
                    document.getElementById('status-text').textContent = 'Complete';
                }
            };
        });
    }
    </script>
    </body></html>
    """


def main():
    parser = argparse.ArgumentParser(description="Safety Scenario Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--scenario", default="battery_rtl",
                       choices=["battery_rtl", "wind_rtl", "battery_emergency",
                               "high_wind_abort", "battery_warn"],
                       help="Scenario to run")
    parser.add_argument("--auto-start", action="store_true", help="Auto-start scenario on load")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("SKYLINK2 SAFETY SCENARIO SERVER")
    print(f"{'='*60}")
    print(f"\nServer: http://{args.host}:{args.port}")
    print(f"3D Dashboard: http://{args.host}:{args.port}/artifacts/dashboard/index.html")
    print(f"\nBaseline Safety Thresholds:")
    print(f"  Battery Warn: {baseline.safety.battery_warn_percent}%")
    print(f"  Battery RTL: {baseline.safety.battery_rtl_percent}%")
    print(f"  Battery Emergency: {baseline.safety.battery_emergency_percent}%")
    print(f"  Max Wind: {baseline.safety.max_operating_wind_mps} m/s")
    print(f"\nScenarios: battery_rtl, wind_rtl, battery_emergency, high_wind_abort, battery_warn")
    print(f"\nPress Ctrl+C to stop\n")

    if args.auto_start:
        @app.before_request
        def auto_start():
            pass  # TODO: auto-start scenario

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
