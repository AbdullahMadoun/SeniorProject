from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)

from .config import SystemBaseline
from .geofence import GeofenceCircle
from .geometry import latlon_to_local_m
from .mission_control import MissionPlanRequest, validate_mission_request
from .models import MissionProgress, VehicleLocalPose, VehicleMode, VehicleSnapshot, Waypoint

try:
    from mavsdk import System  # type: ignore
    from mavsdk.geofence import Circle, FenceType, GeofenceData, Point  # type: ignore
    from mavsdk.mission import MissionItem, MissionPlan  # type: ignore
except ImportError:  # pragma: no cover
    System = None
    Circle = None
    FenceType = None
    GeofenceData = None
    Point = None
    MissionItem = None
    MissionPlan = None


CONNECT_MAX_RETRIES = 5
CONNECT_BASE_DELAY_S = 0.1
CONNECT_BACKOFF_FACTOR = 2.0

UPLOAD_MAX_RETRIES = 3
UPLOAD_BASE_DELAY_S = 0.5
UPLOAD_BACKOFF_FACTOR = 2.0
UPLOAD_TIMEOUT_S = 30.0

ARM_MAX_RETRIES = 3
ARM_BASE_DELAY_S = 0.5
ARM_BACKOFF_FACTOR = 1.5


class TelemetryError(RuntimeError):
    """Base exception for telemetry failures."""
    pass


class TelemetryStreamClosed(TelemetryError):
    """Raised when telemetry stream ends unexpectedly."""
    pass


@dataclass
class _TelemetryCache:
    position: Any | None = None
    battery: Any | None = None
    armed: bool | None = None
    in_air: bool | None = None
    flight_mode: Any | None = None
    mission_progress: MissionProgress | None = None
    position_velocity_ned: Any | None = None
    attitude_euler: Any | None = None
    gps_info: Any | None = None


class VehicleGateway(ABC):
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_snapshot(self) -> VehicleSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def get_local_pose(self) -> VehicleLocalPose | None:
        raise NotImplementedError

    @abstractmethod
    async def upload_mission(self, request: MissionPlanRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upload_geofence(self, request: GeofenceCircle) -> None:
        raise NotImplementedError

    @abstractmethod
    async def arm(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disarm(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def start_mission(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def return_to_launch(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def land(self) -> None:
        raise NotImplementedError


@dataclass
class InMemoryVehicleGateway(VehicleGateway):
    baseline: SystemBaseline
    snapshot: VehicleSnapshot = field(
        default_factory=lambda: VehicleSnapshot(
            connected=False,
            armed=False,
            in_air=False,
            mode=VehicleMode.DISCONNECTED,
        )
    )
    uploaded_mission: MissionPlanRequest | None = None
    uploaded_geofence: GeofenceCircle | None = None

    def __post_init__(self) -> None:
        super().__init__(self.baseline)

    async def connect(self) -> None:
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=False,
            in_air=False,
            mode=VehicleMode.HOLD,
            battery_percent=100.0,
            position=self.baseline.home,
            mission_progress=MissionProgress(),
        )

    async def disconnect(self) -> None:
        self.snapshot = VehicleSnapshot(
            connected=False,
            armed=False,
            in_air=False,
            mode=VehicleMode.DISCONNECTED,
        )

    async def get_snapshot(self) -> VehicleSnapshot:
        return self.snapshot

    async def get_local_pose(self) -> VehicleLocalPose | None:
        if not self.snapshot.connected or self.snapshot.position is None:
            return None

        north_m, east_m = latlon_to_local_m(
            self.snapshot.position.lat,
            self.snapshot.position.lon,
            self.baseline.home.lat,
            self.baseline.home.lon,
        )
        return VehicleLocalPose(
            north_m=north_m,
            east_m=east_m,
            down_m=-self.snapshot.position.alt_m,
            yaw_deg=0.0,
            roll_deg=0.0,
            pitch_deg=0.0,
        )

    async def upload_mission(self, request: MissionPlanRequest) -> None:
        validate_mission_request(request, self._baseline)
        if not self.snapshot.connected:
            raise RuntimeError("Vehicle is not connected.")
        self.uploaded_mission = request
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=self.snapshot.armed,
            in_air=False,
            mode=VehicleMode.HOLD,
            battery_percent=self.snapshot.battery_percent,
            position=request.home,
            mission_progress=MissionProgress(current=0, total=len(request.waypoints)),
        )

    async def upload_geofence(self, request: GeofenceCircle) -> None:
        if not self.snapshot.connected:
            raise RuntimeError("Vehicle is not connected.")
        self.uploaded_geofence = request

    async def arm(self) -> None:
        if not self.snapshot.connected:
            raise RuntimeError("Vehicle is not connected.")
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=True,
            in_air=self.snapshot.in_air,
            mode=self.snapshot.mode,
            battery_percent=self.snapshot.battery_percent,
            position=self.snapshot.position,
            mission_progress=self.snapshot.mission_progress,
        )

    async def disarm(self) -> None:
        self.snapshot = VehicleSnapshot(
            connected=self.snapshot.connected,
            armed=False,
            in_air=False,
            mode=VehicleMode.HOLD if self.snapshot.connected else VehicleMode.DISCONNECTED,
            battery_percent=self.snapshot.battery_percent,
            position=self.snapshot.position,
            mission_progress=self.snapshot.mission_progress,
        )

    async def start_mission(self) -> None:
        if not self.snapshot.armed:
            raise RuntimeError("Vehicle must be armed before mission start.")
        if self.uploaded_mission is None:
            raise RuntimeError("Mission must be uploaded before mission start.")
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=True,
            in_air=True,
            mode=VehicleMode.MISSION,
            battery_percent=self.snapshot.battery_percent,
            position=self.uploaded_mission.waypoints[0],
            mission_progress=MissionProgress(current=1, total=len(self.uploaded_mission.waypoints)),
        )

    async def advance_to_waypoint(self, waypoint_index: int) -> None:
        if self.uploaded_mission is None:
            raise RuntimeError("Mission must be uploaded before advancing mission state.")
        if waypoint_index < 1 or waypoint_index > len(self.uploaded_mission.waypoints):
            raise ValueError("Waypoint index out of range.")
        target = self.uploaded_mission.waypoints[waypoint_index - 1]
        self.snapshot = VehicleSnapshot(
            connected=True,
            armed=True,
            in_air=True,
            mode=VehicleMode.MISSION,
            battery_percent=self.snapshot.battery_percent,
            position=target,
            mission_progress=MissionProgress(current=waypoint_index, total=len(self.uploaded_mission.waypoints)),
        )

    async def return_to_launch(self) -> None:
        self.snapshot = VehicleSnapshot(
            connected=self.snapshot.connected,
            armed=self.snapshot.armed,
            in_air=self.snapshot.in_air,
            mode=VehicleMode.RETURN_TO_LAUNCH,
            battery_percent=self.snapshot.battery_percent,
            position=self.baseline.home,
            mission_progress=self.snapshot.mission_progress,
        )

    async def land(self) -> None:
        self.snapshot = VehicleSnapshot(
            connected=self.snapshot.connected,
            armed=False,
            in_air=False,
            mode=VehicleMode.LAND,
            battery_percent=self.snapshot.battery_percent,
            position=self.snapshot.position or self.baseline.home,
            mission_progress=self.snapshot.mission_progress,
        )


class MavsdkVehicleGateway(VehicleGateway):
    TELEMETRY_MAX_CONSECUTIVE_FAILURES = 5
    TELEMETRY_RECONNECT_DELAY_S = 5.0

    def __init__(
        self,
        baseline: SystemBaseline,
        system_address: str = "udpin://0.0.0.0:14540",
        connect_timeout_s: float = 15.0,
    ) -> None:
        super().__init__(baseline)
        self._system_address = system_address
        self._connect_timeout_s = connect_timeout_s
        self._drone = None
        self._telemetry_lock = asyncio.Lock()
        self._param_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._telemetry_stream_closed = False
        self._telemetry_reconnect_task: asyncio.Task | None = None
        self._reconnect_attempts = 0
        self._telemetry_cache = _TelemetryCache()
        self._telemetry_tasks: list[asyncio.Task[None]] = []
        self._disconnecting = False

    async def connect(self) -> None:
        if System is None:
            raise RuntimeError("mavsdk is not installed.")

        last_exception = None
        delay_s = CONNECT_BASE_DELAY_S
        self._disconnecting = False
        self._reset_telemetry_cache()

        for attempt in range(CONNECT_MAX_RETRIES):
            try:
                self._drone = System()
                await asyncio.wait_for(
                    self._drone.connect(system_address=self._system_address),
                    timeout=self._connect_timeout_s,
                )
                await self._first_matching(
                    self._drone.core.connection_state(),
                    lambda state: state.is_connected,
                    timeout_s=self._connect_timeout_s,
                )
                await self._configure_telemetry_rates()
                self._start_telemetry_monitors()
                self._consecutive_failures = 0
                self._telemetry_stream_closed = False
                _logger.info(f"Connected to {self._system_address} after {attempt + 1} attempt(s)")
                return
            except Exception as exc:
                last_exception = exc
                _logger.warning(f"Connection attempt {attempt + 1}/{CONNECT_MAX_RETRIES} failed: {exc}")
                if attempt < CONNECT_MAX_RETRIES - 1:
                    await asyncio.sleep(delay_s)
                    delay_s *= CONNECT_BACKOFF_FACTOR

        raise RuntimeError(f"Failed to connect to {self._system_address} after {CONNECT_MAX_RETRIES} attempts") from last_exception

    async def disconnect(self) -> None:
        drone = self._drone
        self._disconnecting = True
        self._drone = None
        await self._cancel_telemetry_tasks()
        current_task = asyncio.current_task()
        if self._telemetry_reconnect_task is not None and self._telemetry_reconnect_task is not current_task:
            self._telemetry_reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._telemetry_reconnect_task
        self._telemetry_reconnect_task = None
        self._telemetry_stream_closed = False
        self._consecutive_failures = 0
        self._reconnect_attempts = 0
        self._reset_telemetry_cache()
        if drone is None:
            self._disconnecting = False
            return
        stop_server = getattr(drone, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()
        self._disconnecting = False

    async def get_snapshot(self) -> VehicleSnapshot:
        vehicle_snapshot_disconnected = VehicleSnapshot(
            connected=False,
            armed=False,
            in_air=False,
            mode=VehicleMode.DISCONNECTED,
        )

        if self._drone is None:
            return vehicle_snapshot_disconnected

        position = self._telemetry_cache.position
        battery = self._telemetry_cache.battery
        armed = self._telemetry_cache.armed
        in_air = self._telemetry_cache.in_air
        flight_mode = self._telemetry_cache.flight_mode
        mission_progress = self._telemetry_cache.mission_progress

        if (
            position is None
            and battery is None
            and armed is None
            and in_air is None
            and flight_mode is None
            and mission_progress is None
        ):
            return vehicle_snapshot_disconnected

        mode_value = str(flight_mode).split(".")[-1].lower() if flight_mode is not None else ""
        mode = VehicleMode.HOLD
        if "mission" in mode_value:
            mode = VehicleMode.MISSION
        elif "return" in mode_value:
            mode = VehicleMode.RETURN_TO_LAUNCH
        elif "land" in mode_value:
            mode = VehicleMode.LAND

        return VehicleSnapshot(
            connected=not self._telemetry_stream_closed,
            armed=bool(armed),
            in_air=bool(in_air),
            mode=mode,
            battery_percent=(
                self._normalize_battery_percent(float(battery.remaining_percent))
                if battery is not None
                else None
            ),
            position=(
                Waypoint(
                    lat=float(position.latitude_deg),
                    lon=float(position.longitude_deg),
                    alt_m=float(position.relative_altitude_m),
                )
                if position is not None
                else None
            ),
            mission_progress=mission_progress or MissionProgress(),
        )

    async def get_local_pose(self) -> VehicleLocalPose | None:
        if self._drone is None:
            return None

        position_velocity_ned = self._telemetry_cache.position_velocity_ned
        attitude_euler = self._telemetry_cache.attitude_euler
        if position_velocity_ned is None or attitude_euler is None:
            return None
        return VehicleLocalPose(
            north_m=float(position_velocity_ned.position.north_m),
            east_m=float(position_velocity_ned.position.east_m),
            down_m=float(position_velocity_ned.position.down_m),
            yaw_deg=float(attitude_euler.yaw_deg),
            roll_deg=float(attitude_euler.roll_deg),
            pitch_deg=float(attitude_euler.pitch_deg),
        )

    async def get_gps_info(self) -> dict[str, Any]:
        if self._drone is None:
            return {}
        position = self._telemetry_cache.position
        gps_info = self._telemetry_cache.gps_info
        if position is None:
            return {}
        payload: dict[str, Any] = {
            "lat": float(position.latitude_deg),
            "lon": float(position.longitude_deg),
            "relative_altitude_m": float(position.relative_altitude_m),
            "absolute_altitude_m": float(position.absolute_altitude_m),
        }
        if gps_info is not None:
            payload["num_satellites"] = int(getattr(gps_info, "num_satellites", 0))
            payload["fix_type"] = str(getattr(gps_info, "fix_type", "")).split(".")[-1].lower()
        return payload

    async def wait_for_live_position(
        self,
        *,
        timeout_s: float = 45.0,
        poll_interval_s: float = 0.5,
    ) -> tuple[VehicleSnapshot, VehicleLocalPose]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        last_snapshot = await self.get_snapshot()
        while loop.time() < deadline:
            last_snapshot = await self.get_snapshot()
            local_pose = await self.get_local_pose()
            if last_snapshot.position is not None and local_pose is not None:
                return last_snapshot, local_pose
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError(
            "Timed out waiting for live PX4 position telemetry. "
            f"last_mode={last_snapshot.mode.value}, "
            f"battery={last_snapshot.battery_percent}, "
            f"has_position={last_snapshot.position is not None}."
        )

    async def upload_mission(self, request: MissionPlanRequest) -> None:
        validate_mission_request(request, self._baseline)
        drone = self._require_drone()
        if MissionItem is None or MissionPlan is None:
            raise RuntimeError("mavsdk mission plugin is not installed.")

        mission_items = [
            MissionItem(
                waypoint.lat,
                waypoint.lon,
                waypoint.alt_m,
                request.cruise_speed_mps,
                True,
                float("nan"),
                float("nan"),
                MissionItem.CameraAction.NONE,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                MissionItem.VehicleAction.NONE,
            )
            for waypoint in request.waypoints
        ]

        await drone.mission.set_return_to_launch_after_mission(request.rtl_after_mission)

        last_exception = None
        delay_s = UPLOAD_BASE_DELAY_S

        for attempt in range(UPLOAD_MAX_RETRIES):
            try:
                await asyncio.wait_for(
                    drone.mission.upload_mission(MissionPlan(mission_items)),
                    timeout=UPLOAD_TIMEOUT_S,
                )
                _logger.info(f"Mission uploaded ({len(mission_items)} items) after {attempt + 1} attempt(s)")
                return
            except Exception as exc:
                last_exception = exc
                _logger.warning(f"Mission upload attempt {attempt + 1}/{UPLOAD_MAX_RETRIES} failed: {exc}")
                if attempt < UPLOAD_MAX_RETRIES - 1:
                    await asyncio.sleep(delay_s)
                    delay_s *= UPLOAD_BACKOFF_FACTOR

        raise RuntimeError(f"Mission upload failed after {UPLOAD_MAX_RETRIES} attempts") from last_exception

    async def upload_geofence(self, request: GeofenceCircle) -> None:
        drone = self._require_drone()
        if Point is None or Circle is None or FenceType is None or GeofenceData is None:
            raise RuntimeError("mavsdk geofence plugin is not installed.")
        circle = Circle(
            Point(request.center.lat, request.center.lon),
            request.radius_m,
            FenceType.INCLUSION,
        )
        await drone.geofence.upload_geofence(GeofenceData([], [circle]))

    async def arm(self) -> None:
        drone = self._require_drone()
        last_exception = None
        delay_s = ARM_BASE_DELAY_S

        for attempt in range(ARM_MAX_RETRIES):
            try:
                await asyncio.wait_for(drone.action.arm(), timeout=10.0)
                _logger.info(f"Vehicle armed on attempt {attempt + 1}")
                return
            except Exception as exc:
                last_exception = exc
                _logger.warning(f"Arm attempt {attempt + 1}/{ARM_MAX_RETRIES} failed: {exc}")
                if attempt < ARM_MAX_RETRIES - 1:
                    await asyncio.sleep(delay_s)
                    delay_s *= ARM_BACKOFF_FACTOR

        raise RuntimeError(f"Arm failed after {ARM_MAX_RETRIES} attempts") from last_exception

    async def disarm(self) -> None:
        await self._require_drone().action.disarm()

    async def start_mission(self) -> None:
        await self._require_drone().mission.start_mission()

    async def return_to_launch(self) -> None:
        await self._require_drone().action.return_to_launch()

    async def land(self) -> None:
        await self._require_drone().action.land()

    async def set_param_float(self, name: str, value: float) -> float:
        drone = self._require_drone()
        async with self._param_lock:
            await drone.param.set_param_float(name, float(value))
            return float(await drone.param.get_param_float(name))

    async def set_param_int(self, name: str, value: int) -> int:
        drone = self._require_drone()
        async with self._param_lock:
            await drone.param.set_param_int(name, int(value))
            return int(await drone.param.get_param_int(name))

    async def apply_parameter_overrides(
        self,
        *,
        float_params: dict[str, float] | None = None,
        int_params: dict[str, int] | None = None,
    ) -> dict[str, dict[str, Any]]:
        applied: dict[str, dict[str, Any]] = {}
        for name, value in (float_params or {}).items():
            readback = await self.set_param_float(name, float(value))
            applied[name] = {"param_type": "float", "desired_value": float(value), "applied_value": readback}
        for name, value in (int_params or {}).items():
            readback = await self.set_param_int(name, int(value))
            applied[name] = {"param_type": "int", "desired_value": int(value), "applied_value": readback}
        return applied

    def _require_drone(self):
        if self._drone is None:
            raise RuntimeError("Vehicle is not connected.")
        return self._drone

    async def _configure_telemetry_rates(self) -> None:
        drone = self._require_drone()
        telemetry = drone.telemetry
        rate_requests = (
            ("set_rate_position", 5.0),
            ("set_rate_position_velocity_ned", 8.0),
            ("set_rate_attitude_euler", 10.0),
            ("set_rate_battery", 2.0),
            ("set_rate_gps_info", 2.0),
        )
        for method_name, rate_hz in rate_requests:
            method = getattr(telemetry, method_name, None)
            if method is None:
                continue
            try:
                await method(rate_hz)
            except Exception:
                continue

    def _reset_telemetry_cache(self) -> None:
        self._telemetry_cache = _TelemetryCache()

    def _start_telemetry_monitors(self) -> None:
        drone = self._require_drone()
        self._telemetry_tasks = [
            asyncio.create_task(self._monitor_stream("position", drone.telemetry.position())),
            asyncio.create_task(self._monitor_stream("battery", drone.telemetry.battery())),
            asyncio.create_task(
                self._monitor_stream(
                    "armed",
                    drone.telemetry.armed(),
                    transform=lambda item: bool(item),
                )
            ),
            asyncio.create_task(
                self._monitor_stream(
                    "in_air",
                    drone.telemetry.in_air(),
                    transform=lambda item: bool(item),
                )
            ),
            asyncio.create_task(self._monitor_stream("flight_mode", drone.telemetry.flight_mode())),
            asyncio.create_task(
                self._monitor_stream(
                    "mission_progress",
                    drone.mission.mission_progress(),
                    transform=lambda progress: MissionProgress(
                        current=int(progress.current),
                        total=int(progress.total),
                    ),
                )
            ),
            asyncio.create_task(
                self._monitor_stream(
                    "position_velocity_ned",
                    drone.telemetry.position_velocity_ned(),
                )
            ),
            asyncio.create_task(
                self._monitor_stream(
                    "attitude_euler",
                    drone.telemetry.attitude_euler(),
                )
            ),
            asyncio.create_task(
                self._monitor_stream(
                    "gps_info",
                    drone.telemetry.gps_info(),
                )
            ),
        ]

    async def _cancel_telemetry_tasks(self) -> None:
        if not self._telemetry_tasks:
            return
        for task in self._telemetry_tasks:
            task.cancel()
        for task in self._telemetry_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._telemetry_tasks.clear()

    async def _monitor_stream(self, cache_name: str, stream, *, transform=lambda item: item) -> None:
        try:
            async for item in stream:
                setattr(self._telemetry_cache, cache_name, transform(item))
                self._consecutive_failures = 0
                self._telemetry_stream_closed = False
            if not self._disconnecting:
                self._handle_telemetry_failure(
                    TelemetryStreamClosed(f"{cache_name} stream ended before disconnect"),
                    disconnected_snapshot=VehicleSnapshot(
                        connected=False,
                        armed=False,
                        in_air=False,
                        mode=VehicleMode.DISCONNECTED,
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._disconnecting:
                self._handle_telemetry_failure(
                    TelemetryError(f"{cache_name} stream error: {exc}"),
                    disconnected_snapshot=VehicleSnapshot(
                        connected=False,
                        armed=False,
                        in_air=False,
                        mode=VehicleMode.DISCONNECTED,
                    ),
                )

    async def _read_once(self, stream):
        async for item in stream:
            return item
        raise RuntimeError("Telemetry stream ended before a value was received.")

    async def _read_once_or_default(
        self,
        stream,
        default=None,
        transform=lambda item: item,
        timeout_s: float = 3.0,
    ):
        async def _consume():
            async for item in stream:
                return transform(item)
            raise TelemetryStreamClosed("Stream ended before a value was received")

        task = asyncio.create_task(_consume())
        done, pending = await asyncio.wait([task], timeout=timeout_s)
        
        if pending:
            # Cancel the task but don't await its completion to avoid deadlock
            # with ignoring-cancellation gRPC cores.
            task.cancel()
            raise TelemetryStreamClosed(f"Stream timed out after {timeout_s}s")
            
        try:
            return task.result()
        except TelemetryStreamClosed:
            raise
        except Exception as exc:
            raise TelemetryError(f"Unexpected stream error: {exc}") from exc

    def _handle_telemetry_failure(
        self,
        exc: TelemetryError,
        *,
        disconnected_snapshot: VehicleSnapshot,
    ) -> VehicleSnapshot:
        self._consecutive_failures += 1
        _logger.warning(
            f"Telemetry stream failure #{self._consecutive_failures}: {exc}"
        )

        if self._consecutive_failures >= self.TELEMETRY_MAX_CONSECUTIVE_FAILURES:
            _logger.critical(
                f"Max telemetry failures ({self.TELEMETRY_MAX_CONSECUTIVE_FAILURES}) reached. "
                "Marking stream as closed, initiating reconnection..."
            )
            self._telemetry_stream_closed = True

            if self._telemetry_reconnect_task is None or self._telemetry_reconnect_task.done():
                self._telemetry_reconnect_task = asyncio.create_task(
                    self._attempt_telemetry_reconnect()
                )

        return disconnected_snapshot

    async def _attempt_telemetry_reconnect(self) -> None:
        """Background task to reconnect after telemetry failures."""
        self._reconnect_attempts += 1
        max_attempts = 3
        delay_s = self.TELEMETRY_RECONNECT_DELAY_S * self._reconnect_attempts

        _logger.info(f"Telemetry reconnection attempt {self._reconnect_attempts}/{max_attempts} in {delay_s}s...")

        await asyncio.sleep(delay_s)

        try:
            await self.disconnect()
            self._disconnecting = False
            await self.connect()

            self._consecutive_failures = 0
            self._telemetry_stream_closed = False
            self._reconnect_attempts = 0
            _logger.info("Telemetry reconnection successful!")

        except Exception as exc:
            _logger.error(f"Telemetry reconnection failed: {exc}")

            if self._reconnect_attempts < max_attempts:
                self._telemetry_reconnect_task = asyncio.create_task(
                    self._attempt_telemetry_reconnect()
                )
            else:
                _logger.critical(
                    f"Telemetry reconnection failed after {max_attempts} attempts. "
                    "Manual intervention required."
                )
                self._reconnect_attempts = 0

    async def _first_matching(self, stream, predicate, timeout_s: float = 10.0):
        async def _consume():
            async for item in stream:
                if predicate(item):
                    return item
            raise RuntimeError("Stream ended before a matching value was received.")

        return await asyncio.wait_for(_consume(), timeout=timeout_s)

    @staticmethod
    def _normalize_battery_percent(value: float) -> float:
        if value <= 1.0:
            return value * 100.0
        return value
