from __future__ import annotations

from dataclasses import dataclass

from .config import SystemBaseline
from .safety_engine import SafetyReason


@dataclass(frozen=True)
class WeatherReading:
    steady_wind_mps: float
    gust_wind_mps: float | None = None
    source: str = "synthetic"


@dataclass(frozen=True)
class WeatherGateDecision:
    launch_allowed: bool
    mission_continue_allowed: bool
    dock_allowed: bool
    effective_wind_mps: float
    reasons: tuple[SafetyReason, ...]
    details: tuple[str, ...]


class MissionWeatherGate:
    def __init__(self, baseline: SystemBaseline) -> None:
        self._baseline = baseline

    def assess(self, reading: WeatherReading) -> WeatherGateDecision:
        gust_wind_mps = reading.gust_wind_mps if reading.gust_wind_mps is not None else reading.steady_wind_mps
        effective_wind_mps = max(reading.steady_wind_mps, gust_wind_mps)
        max_wind_mps = self._baseline.safety.max_operating_wind_mps

        if effective_wind_mps > max_wind_mps:
            return WeatherGateDecision(
                launch_allowed=False,
                mission_continue_allowed=False,
                dock_allowed=False,
                effective_wind_mps=effective_wind_mps,
                reasons=(SafetyReason.WIND_LIMIT_EXCEEDED,),
                details=(
                    f"Effective wind {effective_wind_mps:.1f} m/s exceeds "
                    f"configured limit {max_wind_mps:.1f} m/s.",
                ),
            )

        return WeatherGateDecision(
            launch_allowed=True,
            mission_continue_allowed=True,
            dock_allowed=True,
            effective_wind_mps=effective_wind_mps,
            reasons=(),
            details=(
                f"Effective wind {effective_wind_mps:.1f} m/s is within "
                f"configured limit {max_wind_mps:.1f} m/s.",
            ),
        )
