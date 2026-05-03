from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import SystemBaseline
from .precision_landing import PrecisionLandingTuning


@dataclass(frozen=True)
class Px4ParameterSetting:
    name: str
    param_type: str
    value: int | float
    rationale: str


@dataclass(frozen=True)
class AppliedPx4ParameterSetting:
    name: str
    param_type: str
    desired_value: int | float
    applied_value: int | float
    rationale: str


PX4_PRECISION_LANDING_RUNTIME_SETTINGS = (
    Px4ParameterSetting(
        name="RTL_RETURN_ALT",
        param_type="float",
        value=15.0,
        rationale="Maintain safe climb altitude before the precision landing approach.",
    ),
    Px4ParameterSetting(
        name="RTL_DESCEND_ALT",
        param_type="float",
        value=5.0,
        rationale="Transition to the final precision-landing descent from a stable loiter altitude.",
    ),
    Px4ParameterSetting(
        name="RTL_LAND_DELAY",
        param_type="float",
        value=0.0,
        rationale="Avoid unnecessary hover delay before the landing controller takes over.",
    ),
    Px4ParameterSetting(
        name="MPC_LAND_SPEED",
        param_type="float",
        value=0.4,
        rationale="Slow the final touchdown for a controlled dock approach.",
    ),
    Px4ParameterSetting(
        name="MPC_LAND_ALT1",
        param_type="float",
        value=5.0,
        rationale="Begin the landing-speed ramp at the upper descent gate.",
    ),
    Px4ParameterSetting(
        name="MPC_LAND_ALT2",
        param_type="float",
        value=1.0,
        rationale="Reach the slow landing speed close to the dock.",
    ),
    Px4ParameterSetting(
        name="EKF2_AID_MASK",
        param_type="int",
        value=321,
        rationale="Allow PX4 to fuse landing-target information with the standard navigation aids.",
    ),
)


def build_px4_precision_landing_profile(
    baseline: SystemBaseline,
    tuning: PrecisionLandingTuning | None = None,
) -> tuple[Px4ParameterSetting, ...]:
    landing_tuning = tuning or PrecisionLandingTuning()
    rtl_mode_value = 2 if baseline.docking.rtl_precision_land_mode == "required" else 1
    return (
        Px4ParameterSetting(
            name="RTL_PLD_MD",
            param_type="int",
            value=rtl_mode_value,
            rationale="Enable required precision landing during RTL recovery.",
        ),
        Px4ParameterSetting(
            name="LTEST_MODE",
            param_type="int",
            value=1,
            rationale="Dock target is stationary relative to the home frame.",
        ),
        Px4ParameterSetting(
            name="PLD_HACC_RAD",
            param_type="float",
            value=float(baseline.docking.landing_accuracy_target_m),
            rationale="Begin descent once horizontal landing error is inside the landing accuracy target.",
        ),
        Px4ParameterSetting(
            name="PLD_BTOUT",
            param_type="float",
            value=float(landing_tuning.reacquire_timeout_s),
            rationale="Abort landing-target tracking when the target is lost beyond the configured reacquire timeout.",
        ),
        Px4ParameterSetting(
            name="PLD_FAPPR_ALT",
            param_type="float",
            value=float(landing_tuning.flare_altitude_m),
            rationale="Enter final approach near the range-assisted flare altitude.",
        ),
        Px4ParameterSetting(
            name="PLD_MAX_SRCH",
            param_type="int",
            value=3,
            rationale="Allow bounded retries before falling back from required search behavior.",
        ),
    )


async def apply_px4_precision_landing_profile(
    param_plugin,
    settings: tuple[Px4ParameterSetting, ...],
) -> tuple[AppliedPx4ParameterSetting, ...]:
    applied: list[AppliedPx4ParameterSetting] = []
    for setting in settings:
        if setting.param_type == "int":
            await param_plugin.set_param_int(setting.name, int(setting.value))
            readback = int(await param_plugin.get_param_int(setting.name))
        elif setting.param_type == "float":
            await param_plugin.set_param_float(setting.name, float(setting.value))
            readback = float(await param_plugin.get_param_float(setting.name))
        else:
            raise ValueError(f"Unsupported PX4 parameter type: {setting.param_type}")

        applied.append(
            AppliedPx4ParameterSetting(
                name=setting.name,
                param_type=setting.param_type,
                desired_value=setting.value,
                applied_value=readback,
                rationale=setting.rationale,
            )
        )
    return tuple(applied)


def applied_profile_to_dict(
    applied_settings: tuple[AppliedPx4ParameterSetting, ...],
) -> list[dict[str, object]]:
    return [asdict(setting) for setting in applied_settings]


def build_px4_precision_landing_runtime_profile(
    baseline: SystemBaseline,
    tuning: PrecisionLandingTuning | None = None,
) -> tuple[Px4ParameterSetting, ...]:
    base_settings = list(build_px4_precision_landing_profile(baseline, tuning))
    names = {setting.name for setting in base_settings}
    for runtime_setting in PX4_PRECISION_LANDING_RUNTIME_SETTINGS:
        if runtime_setting.name not in names:
            base_settings.append(runtime_setting)
    return tuple(base_settings)


async def configure_px4_precision_landing(
    drone,
    baseline: SystemBaseline,
    tuning: PrecisionLandingTuning | None = None,
) -> tuple[AppliedPx4ParameterSetting, ...]:
    settings = build_px4_precision_landing_runtime_profile(baseline, tuning)
    return await apply_px4_precision_landing_profile(drone.param, settings)
