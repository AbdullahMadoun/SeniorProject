from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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

    async def connect(self) -> None:
        if System is None:
            raise RuntimeError("mavsdk is not installed.")
        self._drone = System()
        await asyncio.wait_for(
            self._drone.connect(system_address=self._system_address),
            timeout=self._connect_timeout_s,
        )
        await self._first_matching(self._drone.core.connection_state(), lambda state: state.is_connected)

    async def disconnect(self) -> None:
        drone = self._drone
        self._drone = None
        if drone is None:
            return
        stop_server = getattr(drone, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()

    async def get_snapshot(self) -> VehicleSnapshot:
        if self._drone is None:
            return VehicleSnapshot(
                connected=False,
                armed=False,
                in_air=False,
                mode=VehicleMode.DISCONNECTED,
            )

        position = await self._read_once(self._drone.telemetry.position())
        battery = await self._read_once(self._drone.telemetry.battery())
        armed = await self._read_once(self._drone.telemetry.armed())
        in_air = await self._read_once(self._drone.telemetry.in_air())
        flight_mode = await self._read_once(self._drone.telemetry.flight_mode())
        mission_progress = await self._read_once_or_default(
            self._drone.mission.mission_progress(),
            default=MissionProgress(),
            transform=lambda progress: MissionProgress(
                current=int(progress.current),
                total=int(progress.total),
            ),
        )

        mode_value = str(flight_mode).split(".")[-1].lower()
        mode = VehicleMode.HOLD
        if "mission" in mode_value:
            mode = VehicleMode.MISSION
        elif "return" in mode_value:
            mode = VehicleMode.RETURN_TO_LAUNCH
        elif "land" in mode_value:
            mode = VehicleMode.LAND

        return VehicleSnapshot(
            connected=True,
            armed=bool(armed),
            in_air=bool(in_air),
            mode=mode,
            battery_percent=self._normalize_battery_percent(float(battery.remaining_percent)),
            position=Waypoint(
                lat=float(position.latitude_deg),
                lon=float(position.longitude_deg),
                alt_m=float(position.relative_altitude_m),
            ),
            mission_progress=mission_progress,
        )

    async def get_local_pose(self) -> VehicleLocalPose | None:
        if self._drone is None:
            return None

        position_velocity_ned = await self._read_once(self._drone.telemetry.position_velocity_ned())
        attitude_euler = await self._read_once(self._drone.telemetry.attitude_euler())
        return VehicleLocalPose(
            north_m=float(position_velocity_ned.position.north_m),
            east_m=float(position_velocity_ned.position.east_m),
            down_m=float(position_velocity_ned.position.down_m),
            yaw_deg=float(attitude_euler.yaw_deg),
            roll_deg=float(attitude_euler.roll_deg),
            pitch_deg=float(attitude_euler.pitch_deg),
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
        await drone.mission.upload_mission(MissionPlan(mission_items))

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
        await self._require_drone().action.arm()

    async def disarm(self) -> None:
        await self._require_drone().action.disarm()

    async def start_mission(self) -> None:
        await self._require_drone().mission.start_mission()

    async def return_to_launch(self) -> None:
        await self._require_drone().action.return_to_launch()

    async def land(self) -> None:
        await self._require_drone().action.land()

    def _require_drone(self):
        if self._drone is None:
            raise RuntimeError("Vehicle is not connected.")
        return self._drone

    async def _read_once(self, stream):
        async for item in stream:
            return item
        raise RuntimeError("Telemetry stream ended before a value was received.")

    async def _read_once_or_default(self, stream, default, transform=lambda item: item, timeout_s: float = 3.0):
        try:
            item = await asyncio.wait_for(self._read_once(stream), timeout=timeout_s)
        except Exception:
            return default
        return transform(item)

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
