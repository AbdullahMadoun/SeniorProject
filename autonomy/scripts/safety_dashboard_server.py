"""
Safety Dashboard Server - REST API + SSE streaming for 3D dashboard

Run this server, then open the dashboard:
    python safety_dashboard_server.py --port 5000

Open: http://127.0.0.1:5000/

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
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from flask import Flask, Response, jsonify, request

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.safety_engine import SafetyAction
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.mission_control import MissionPlanRequest
from autonomy.drone_system.models import VehicleMode, Waypoint

app = Flask(__name__)

baseline = load_system_baseline()
SIMULATION_FPS = 10
MISSION_RADIUS_M = 50.0


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
    horizontal_distance_to_dock_m: float
    vertical_distance_to_dock_m: float
    dock_lat: float
    dock_lon: float


class SafetyScenarioServer:
    def __init__(self, scenario_name: str) -> None:
        self.scenario_name = scenario_name
        self.baseline = load_system_baseline()
        self.engine = None
        self.frames: list[SimFrame] = []
        self.events: list[dict] = []
        self._running = False
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

    async def run_async(self) -> None:
        self._running = True
        self._start_time = time.time()

        if self.scenario_name == "battery_rtl":
            await self._run_battery_rtl()
        elif self.scenario_name == "wind_rtl":
            await self._run_wind_rtl()
        elif self.scenario_name == "battery_emergency":
            await self._run_battery_emergency()
        elif self.scenario_name == "high_wind_abort":
            await self._run_high_wind_abort()
        elif self.scenario_name == "battery_warn":
            await self._run_battery_warn()

        self._running = False

    async def _run_battery_rtl(self) -> None:
        self._add_event(0, "mode", "Mission execution started")
        yield self._make_frame(0, 100.0, 3.0, "auto_mission", None)

        for i in range(20):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(19.0, 100.0 - (i * 0.5))
            event = None
            if battery <= 25.0 and battery > 19.0 and i == 15:
                event = "battery_warning"
                self._add_event(time.time() - self._start_time, "battery", f"Battery warning: {battery:.0f}%")
            yield self._make_frame(time.time() - self._start_time, battery, 3.0, "auto_mission", event)

        self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered at {19.0:.0f}% battery")
        yield self._make_frame(time.time() - self._start_time, 19.0, 3.0, "return_to_launch", "rtl_triggered")

        for i in range(30):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 30.0
            lat = self.baseline.home.lat + (0.0001 * (1 - progress))
            lon = self.baseline.home.lon + (0.0001 * (1 - progress))
            alt = 25.0 - (5.0 * progress)
            battery = 19.0 - (i * 0.1)
            yield self._make_frame(time.time() - self._start_time, battery, 3.0, "return_to_launch", None, lat, lon, alt)

    async def _run_wind_rtl(self) -> None:
        self._add_event(0, "mode", "Mission execution started")

        for i in range(20):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            wind = 3.0 + (i * 0.1)
            event = None
            if wind >= 7.0 and i == 15:
                event = "wind_warning"
                self._add_event(time.time() - self._start_time, "wind", f"Wind increasing: {wind:.1f} m/s")
            yield self._make_frame(time.time() - self._start_time, 75.0, wind, "auto_mission", event)

        wind_mps = 8.5
        self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered - Wind {wind_mps:.1f} m/s exceeds limit")
        yield self._make_frame(time.time() - self._start_time, 75.0, wind_mps, "return_to_launch", "rtl_triggered")

        for i in range(30):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 30.0
            lat = self.baseline.home.lat + (0.0001 * (1 - progress))
            lon = self.baseline.home.lon + (0.0001 * (1 - progress))
            alt = 25.0 - (5.0 * progress)
            battery = 75.0 - (i * 0.05)
            yield self._make_frame(time.time() - self._start_time, battery, wind_mps, "return_to_launch", None, lat, lon, alt)

    async def _run_battery_emergency(self) -> None:
        self._add_event(0, "mode", "Mission execution started")

        for i in range(30):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(8.0, 100.0 - (i * 3.0))
            event = "emergency" if battery <= 10.0 and i >= 25 else None
            yield self._make_frame(time.time() - self._start_time, battery, 3.0, "auto_mission", event)

        self._add_event(time.time() - self._start_time, "land", f"EMERGENCY LANDING at {8.0:.0f}% battery")
        yield self._make_frame(time.time() - self._start_time, 8.0, 3.0, "land", "emergency_land")

        for i in range(20):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            alt = max(0.0, 25.0 - (i * 1.25))
            yield self._make_frame(time.time() - self._start_time, 8.0, 3.0, "land", None, alt=alt)

    async def _run_high_wind_abort(self) -> None:
        self._add_event(0, "mode", "Preflight checks...")
        yield self._make_frame(time.time() - self._start_time, 100.0, 9.0, "hold", None)

        wind_mps = 9.0
        self._add_event(time.time() - self._start_time, "abort", f"LAUNCH ABORTED - Wind {wind_mps:.1f} m/s exceeds limit")
        yield self._make_frame(time.time() - self._start_time, 100.0, wind_mps, "hold", "launch_aborted")

        for i in range(10):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            yield self._make_frame(time.time() - self._start_time, 100.0, wind_mps, "hold", None)

    async def _run_battery_warn(self) -> None:
        self._add_event(0, "mode", "Mission execution started")

        for i in range(50):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            battery = max(20.0, 100.0 - (i * 1.5))
            event = None
            if battery <= 25.0 and battery > 20.0 and i >= 40:
                event = "battery_warning"
                self._add_event(time.time() - self._start_time, "battery", f"Battery warning: {battery:.0f}%")
            yield self._make_frame(time.time() - self._start_time, battery, 3.0, "auto_mission", event)

            if battery <= 20.0:
                self._add_event(time.time() - self._start_time, "rtl", f"RTL triggered at {battery:.0f}%")
                yield self._make_frame(time.time() - self._start_time, battery, 3.0, "return_to_launch", "rtl_triggered")
                break

        for i in range(20):
            if not self._running:
                return
            await asyncio.sleep(1.0 / SIMULATION_FPS)
            progress = (i + 1) / 20.0
            lat = self.baseline.home.lat + (0.0001 * progress)
            lon = self.baseline.home.lon + (0.0001 * progress)
            yield self._make_frame(time.time() - self._start_time, 20.0, 3.0, "auto_mission", None, lat, lon, 25.0)

    def _make_frame(self, elapsed: float, battery: float, wind: float, mode: str,
                    event: str | None = None, lat: float | None = None, lon: float | None = None,
                    alt: float | None = None) -> SimFrame:
        if lat is None:
            lat = self.baseline.home.lat
        if lon is None:
            lon = self.baseline.home.lon
        if alt is None:
            alt = 25.0

        home_lat = self.baseline.home.lat
        home_lon = self.baseline.home.lon
        dlat = lat - home_lat
        dlon = lon - home_lon
        h_dist = ((dlat * 111320) ** 2 + (dlon * 111320 * abs(math.cos(math.radians(home_lat)))) ** 2) ** 0.5

        frame = SimFrame(
            elapsed_s=elapsed,
            lat_deg=lat,
            lon_deg=lon,
            alt_m=alt,
            heading_deg=90.0,
            battery_percent=battery,
            wind_speed_mps=wind,
            mode=mode,
            horizontal_distance_to_dock_m=h_dist,
            vertical_distance_to_dock_m=alt,
            dock_lat=home_lat,
            dock_lon=home_lon,
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


import math

current_scenario: SafetyScenarioServer | None = None
scenario_lock = threading.Lock()
sse_clients_telemetry: list[threading.Event] = []
sse_clients_events: list[threading.Event] = []


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

    with scenario_lock:
        if current_scenario:
            current_scenario.stop()
            current_scenario = None

        sc = SafetyScenarioServer(scenario_name)
        current_scenario = sc

        def on_frame(frame: SimFrame):
            for client in sse_clients_telemetry:
                client.set()
            for client in sse_clients_events:
                client.set()

        sc.subscribe(on_frame)

        def run_scenario():
            asyncio.run(sc.run_async())

        threading.Thread(target=run_scenario, daemon=True).start()

    return jsonify({"status": "started", "scenario": scenario_name})


@app.route("/api/safety/stop", methods=["POST"])
def stop_scenario():
    global current_scenario
    with scenario_lock:
        if current_scenario:
            current_scenario.stop()
    return jsonify({"status": "stopped"})


@app.route("/api/safety/state")
def get_state():
    with scenario_lock:
        if current_scenario:
            return jsonify(current_scenario.get_state())
    return jsonify({"scenario": None, "running": False, "frame_count": 0, "events": []})


@app.route("/api/safety/stream")
def events_stream():
    def generate():
        client_done = threading.Event()
        sse_clients_events.append(client_done)

        try:
            while True:
                client_done.wait(timeout=30.0)
                if not client_done.is_set():
                    yield sse_event({"status": "heartbeat"})
                    continue
                client_done.clear()

                with scenario_lock:
                    if current_scenario:
                        state = current_scenario.get_state()
                        if state["events"]:
                            yield sse_event({
                                "events": state["events"],
                                "running": state["running"],
                                "scenario": state["scenario"]
                            })
                        if not state["running"] and state["frame_count"] > 0:
                            yield sse_event({"status": "complete", "events": state["events"]})
                            break
                    else:
                        yield sse_event({"status": "waiting"})
        finally:
            if client_done in sse_clients_events:
                sse_clients_events.remove(client_done)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/safety/telemetry")
def telemetry_stream():
    def generate():
        while True:
            with scenario_lock:
                if current_scenario and current_scenario.frames:
                    frame = current_scenario.frames[-1]
                    yield sse_event(asdict(frame))
            time.sleep(1.0 / SIMULATION_FPS)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SkyLink2 Safety Control</title>
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', system-ui, sans-serif;
                background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%);
                color: #e8e8ed;
                min-height: 100vh;
                margin: 0;
                padding: 40px;
            }
            h1 { color: #00d4aa; margin: 0 0 10px; }
            h2 { color: #53b7ff; margin: 30px 0 15px; }
            .subtitle { color: #98a4b7; margin-bottom: 30px; }
            .controls { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }
            button {
                padding: 14px 28px;
                font-size: 15px;
                font-weight: 600;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                transition: all 0.2s;
            }
            button:hover { transform: translateY(-2px); }
            button:active { transform: translateY(0); }
            .btn-rtl { background: linear-gradient(135deg, #00d4aa, #00a884); color: #000; }
            .btn-wind { background: linear-gradient(135deg, #53b7ff, #3a9ae0); color: #000; }
            .btn-emergency { background: linear-gradient(135deg, #ff6b7a, #e05565); color: #fff; }
            .btn-abort { background: linear-gradient(135deg, #ffb454, #e09a3d); color: #000; }
            .btn-warn { background: linear-gradient(135deg, #98a4b7, #7a8a9d); color: #000; }
            .btn-stop { background: #2a2a3e; color: #ff6b7a; border: 2px solid #ff6b7a; }
            .status-panel {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 16px;
                padding: 20px;
                margin: 20px 0;
            }
            .status-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
            .status-row:last-child { border: none; }
            .status-label { color: #98a4b7; }
            .status-value { font-weight: 600; }
            .status-value.running { color: #00d4aa; }
            .status-value.stopped { color: #98a4b7; }
            .event-log {
                background: #020307;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 16px;
                max-height: 300px;
                overflow-y: auto;
                font-family: 'Consolas', monospace;
                font-size: 13px;
            }
            .event-item { padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
            .event-time { color: #00d4aa; margin-right: 10px; }
            .event-type { 
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                margin-right: 10px;
            }
            .type-rtl { background: rgba(255,180,84,0.2); color: #ffb454; }
            .type-land { background: rgba(0,212,170,0.2); color: #00d4aa; }
            .type-mode { background: rgba(83,183,255,0.2); color: #53b7ff; }
            .type-battery { background: rgba(255,107,122,0.2); color: #ff6b7a; }
            .type-wind { background: rgba(255,107,122,0.2); color: #ff6b7a; }
            .type-abort { background: rgba(255,107,122,0.2); color: #ff6b7a; }
            .event-message { color: #bce7da; }
            .dashboard-link {
                display: inline-block;
                margin-top: 20px;
                padding: 12px 24px;
                background: linear-gradient(135deg, rgba(0,212,170,0.2), rgba(83,183,255,0.2));
                border: 1px solid rgba(0,212,170,0.4);
                border-radius: 12px;
                color: #00d4aa;
                text-decoration: none;
                font-weight: 600;
            }
            .dashboard-link:hover { background: linear-gradient(135deg, rgba(0,212,170,0.3), rgba(83,183,255,0.3)); }
        </style>
    </head>
    <body>
        <h1>SkyLink2 Safety Scenario Control</h1>
        <p class="subtitle">Real-time safety scenario simulation with SSE telemetry streaming</p>

        <h2>Available Scenarios</h2>
        <div class="controls">
            <button class="btn-rtl" onclick="startScenario('battery_rtl')">Battery RTL</button>
            <button class="btn-wind" onclick="startScenario('wind_rtl')">Wind RTL</button>
            <button class="btn-emergency" onclick="startScenario('battery_emergency')">Emergency Land</button>
            <button class="btn-abort" onclick="startScenario('high_wind_abort')">Launch Abort</button>
            <button class="btn-warn" onclick="startScenario('battery_warn')">Battery Warning</button>
            <button class="btn-stop" onclick="stopScenario()">Stop</button>
        </div>

        <h2>Current Status</h2>
        <div class="status-panel">
            <div class="status-row">
                <span class="status-label">Scenario</span>
                <span class="status-value" id="status-scenario">None</span>
            </div>
            <div class="status-row">
                <span class="status-label">Status</span>
                <span class="status-value" id="status-running">Stopped</span>
            </div>
            <div class="status-row">
                <span class="status-label">Frames</span>
                <span class="status-value" id="status-frames">0</span>
            </div>
            <div class="status-row">
                <span class="status-label">Events</span>
                <span class="status-value" id="status-events">0</span>
            </div>
        </div>

        <h2>Event Log</h2>
        <div class="event-log" id="event-log">
            <div class="event-item" style="color: #98a4b7;">Waiting for events...</div>
        </div>

        <a href="/artifacts/dashboard/index.html" target="_blank" class="dashboard-link">
            Open 3D Dashboard
        </a>

        <script>
            let eventSource = null;
            let telemetrySource = null;

            function startScenario(scenario) {
                if (eventSource) eventSource.close();
                if (telemetrySource) telemetrySource.close();

                fetch('/api/safety/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({scenario: scenario})
                }).then(r => r.json()).then(data => {
                    console.log('Started:', data);
                    updateStatus();
                    startStreams();
                });
            }

            function stopScenario() {
                fetch('/api/safety/stop', {method: 'POST'})
                    .then(r => r.json())
                    .then(data => {
                        console.log('Stopped:', data);
                        if (eventSource) eventSource.close();
                        if (telemetrySource) telemetrySource.close();
                        updateStatus();
                    });
            }

            function updateStatus() {
                fetch('/api/safety/state')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('status-scenario').textContent = data.scenario || 'None';
                        const runningEl = document.getElementById('status-running');
                        runningEl.textContent = data.running ? 'Running' : 'Stopped';
                        runningEl.className = 'status-value ' + (data.running ? 'running' : 'stopped');
                        document.getElementById('status-frames').textContent = data.frame_count || 0;
                        document.getElementById('status-events').textContent = data.events ? data.events.length : 0;
                    });
            }

            function startStreams() {
                eventSource = new EventSource('/api/safety/stream');
                eventSource.onmessage = (e) => {
                    const data = JSON.parse(e.data);
                    if (data.events && data.events.length > 0) {
                        const log = document.getElementById('event-log');
                        log.innerHTML = data.events.map(ev => `
                            <div class="event-item">
                                <span class="event-time">${ev.t.toFixed(1)}s</span>
                                <span class="event-type type-${ev.type}">${ev.type}</span>
                                <span class="event-message">${ev.message}</span>
                            </div>
                        `).join('');
                        log.scrollTop = log.scrollHeight;
                    }
                    if (data.status === 'complete') {
                        document.getElementById('status-running').textContent = 'Complete';
                        document.getElementById('status-running').className = 'status-value stopped';
                    }
                    updateStatus();
                };

                telemetrySource = new EventSource('/api/safety/telemetry');
                telemetrySource.onmessage = (e) => {
                    // Telemetry data available for future use
                    updateStatus();
                };
            }

            updateStatus();
        </script>
    </body>
    </html>
    """


@app.route("/artifacts/dashboard/<path:filename>")
def serve_dashboard(filename):
    from flask import send_from_directory
    dashboard_dir = Path(__file__).resolve().parents[1] / "artifacts" / "dashboard"
    return send_from_directory(str(dashboard_dir), filename)


def main():
    parser = argparse.ArgumentParser(description="Safety Dashboard Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("SKYLINK2 SAFETY DASHBOARD SERVER")
    print(f"{'='*60}")
    print(f"\nServer: http://{args.host}:{args.port}")
    print(f"Control Page: http://{args.host}:{args.port}/")
    print(f"3D Dashboard: http://{args.host}:{args.port}/artifacts/dashboard/index.html")
    print(f"\nBaseline Safety Thresholds:")
    print(f"  Battery Warn: {baseline.safety.battery_warn_percent}%")
    print(f"  Battery RTL: {baseline.safety.battery_rtl_percent}%")
    print(f"  Battery Emergency: {baseline.safety.battery_emergency_percent}%")
    print(f"  Max Wind: {baseline.safety.max_operating_wind_mps} m/s")
    print(f"\nScenarios: battery_rtl, wind_rtl, battery_emergency, high_wind_abort, battery_warn")
    print(f"\nPress Ctrl+C to stop\n")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
