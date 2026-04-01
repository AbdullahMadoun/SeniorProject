from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import SystemBaseline
from .mission_control import MissionPlanRequest, validate_mission_request
from .models import VehicleMode, VehicleSnapshot
from .vehicle_interface import VehicleGateway


class SafetyAction(str, Enum):
    CONTINUE = "continue"
    WARN = "warn"
    ABORT_LAUNCH = "abort_launch"
    RETURN_TO_LAUNCH = "return_to_launch"
    LAND_NOW = "land_now"


class SafetyReason(str, Enum):
    VEHICLE_DISCONNECTED = "vehicle_disconnected"
    BATTERY_WARN_THRESHOLD = "battery_warn_threshold"
    BATTERY_RTL_THRESHOLD = "battery_rtl_threshold"
    BATTERY_EMERGENCY_THRESHOLD = "battery_emergency_threshold"
    BATTERY_TELEMETRY_UNAVAILABLE = "battery_telemetry_unavailable"
    WIND_LIMIT_EXCEEDED = "wind_limit_exceeded"
    MISSION_INVALID = "mission_invalid"


@dataclass(frozen=True)
class SafetyDecision:
    action: SafetyAction
    reasons: tuple[SafetyReason, ...] = ()
    details: tuple[str, ...] = ()


class MissionSafetyEngine:
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline

    def assess_preflight(
        self,
        snapshot: VehicleSnapshot,
        request: MissionPlanRequest,
        wind_mps: float,
    ) -> SafetyDecision:
        reasons: list[SafetyReason] = []
        details: list[str] = []

        if not snapshot.connected:
            reasons.append(SafetyReason.VEHICLE_DISCONNECTED)
            details.append("Vehicle is not connected.")

        try:
            validate_mission_request(request, self._baseline)
        except ValueError as exc:
            reasons.append(SafetyReason.MISSION_INVALID)
            details.append(str(exc))

        if wind_mps > self._baseline.safety.max_operating_wind_mps:
            reasons.append(SafetyReason.WIND_LIMIT_EXCEEDED)
            details.append(
                f"Wind {wind_mps:.1f} m/s exceeds "
                f"{self._baseline.safety.max_operating_wind_mps:.1f} m/s."
            )

        battery = snapshot.battery_percent
        if battery is None:
            reasons.append(SafetyReason.BATTERY_TELEMETRY_UNAVAILABLE)
            details.append("Battery telemetry is unavailable.")
        elif battery <= self._baseline.safety.battery_rtl_percent:
            reasons.append(SafetyReason.BATTERY_RTL_THRESHOLD)
            details.append(
                f"Battery {battery:.1f}% is at or below RTL threshold "
                f"{self._baseline.safety.battery_rtl_percent:.1f}%."
            )
        elif battery <= self._baseline.safety.battery_warn_percent:
            return SafetyDecision(
                action=SafetyAction.WARN,
                reasons=(SafetyReason.BATTERY_WARN_THRESHOLD,),
                details=(
                    f"Battery {battery:.1f}% is below warn threshold "
                    f"{self._baseline.safety.battery_warn_percent:.1f}%.",
                ),
            )

        if reasons:
            return SafetyDecision(
                action=SafetyAction.ABORT_LAUNCH,
                reasons=tuple(reasons),
                details=tuple(details),
            )
        return SafetyDecision(action=SafetyAction.CONTINUE)

    def assess_inflight(self, snapshot: VehicleSnapshot, wind_mps: float) -> SafetyDecision:
        battery = snapshot.battery_percent

        if wind_mps > self._baseline.safety.max_operating_wind_mps:
            return SafetyDecision(
                action=SafetyAction.RETURN_TO_LAUNCH,
                reasons=(SafetyReason.WIND_LIMIT_EXCEEDED,),
                details=(
                    f"Wind {wind_mps:.1f} m/s exceeds "
                    f"{self._baseline.safety.max_operating_wind_mps:.1f} m/s.",
                ),
            )

        if battery is None:
            return SafetyDecision(
                action=SafetyAction.RETURN_TO_LAUNCH,
                reasons=(SafetyReason.BATTERY_TELEMETRY_UNAVAILABLE,),
                details=("Battery telemetry is unavailable during flight.",),
            )

        if battery <= self._baseline.safety.battery_emergency_percent:
            return SafetyDecision(
                action=SafetyAction.LAND_NOW,
                reasons=(SafetyReason.BATTERY_EMERGENCY_THRESHOLD,),
                details=(
                    f"Battery {battery:.1f}% is at or below emergency threshold "
                    f"{self._baseline.safety.battery_emergency_percent:.1f}%.",
                ),
            )

        if battery <= self._baseline.safety.battery_rtl_percent:
            return SafetyDecision(
                action=SafetyAction.RETURN_TO_LAUNCH,
                reasons=(SafetyReason.BATTERY_RTL_THRESHOLD,),
                details=(
                    f"Battery {battery:.1f}% is at or below RTL threshold "
                    f"{self._baseline.safety.battery_rtl_percent:.1f}%.",
                ),
            )

        if battery <= self._baseline.safety.battery_warn_percent:
            return SafetyDecision(
                action=SafetyAction.WARN,
                reasons=(SafetyReason.BATTERY_WARN_THRESHOLD,),
                details=(
                    f"Battery {battery:.1f}% is below warn threshold "
                    f"{self._baseline.safety.battery_warn_percent:.1f}%.",
                ),
            )

        return SafetyDecision(action=SafetyAction.CONTINUE)

    async def assess_preflight_from_gateway(
        self,
        gateway: VehicleGateway,
        request: MissionPlanRequest,
        wind_mps: float,
    ) -> SafetyDecision:
        return self.assess_preflight(await gateway.get_snapshot(), request, wind_mps)

    async def enforce_inflight_policy(self, gateway: VehicleGateway, wind_mps: float) -> SafetyDecision:
        snapshot = await gateway.get_snapshot()
        decision = self.assess_inflight(snapshot, wind_mps)

        if decision.action == SafetyAction.RETURN_TO_LAUNCH and snapshot.mode != VehicleMode.RETURN_TO_LAUNCH:
            await gateway.return_to_launch()
        elif decision.action == SafetyAction.LAND_NOW and snapshot.mode != VehicleMode.LAND:
            await gateway.land()

        return decision
