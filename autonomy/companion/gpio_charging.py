from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from autonomy.companion.mock_rpi import load_ads_backend, load_board_module, load_busio_module, load_gpio_module
else:
    from .mock_rpi import load_ads_backend, load_board_module, load_busio_module, load_gpio_module


DEFAULT_OUTPUT_DIR = Path(os.environ.get("SKYLINK_GPIO_OUTPUT", Path.cwd() / "companion_gpio"))


@dataclass(frozen=True)
class ChargingConfig:
    charge_enable_pin: int = 17
    contact_channel: int = 0
    battery_channel: int = 1
    contact_threshold_v: float = 0.5
    battery_nominal_v: float = 16.8
    battery_tolerance_v: float = 1.5
    output_dir: Path = DEFAULT_OUTPUT_DIR
    cycles: int = 1
    poll_interval_s: float = 0.2


@dataclass(frozen=True)
class ChargingDecision:
    contact_voltage_v: float
    battery_voltage_v: float
    contact_detected: bool
    battery_in_range: bool
    charge_enabled: bool
    reason: str


class GPIOChargingController:
    def __init__(self, config: ChargingConfig) -> None:
        self.config = config
        self.GPIO, self._mock_gpio = load_gpio_module()
        self.board, self._mock_board = load_board_module()
        self.busio, self._mock_busio = load_busio_module()
        self.ADS, self.AnalogIn, self._mock_ads = load_ads_backend()
        self._charge_pin_ready = False
        self._ads_device: Any | None = None
        self._contact_channel: Any | None = None
        self._battery_channel: Any | None = None

    def setup(self) -> None:
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(self.config.charge_enable_pin, self.GPIO.OUT, initial=self.GPIO.LOW)
        i2c = self.busio.I2C(self.board.SCL, self.board.SDA)
        self._ads_device = self.ADS.ADS1115(i2c)
        self._contact_channel = self.AnalogIn(self._ads_device, self.config.contact_channel)
        self._battery_channel = self.AnalogIn(self._ads_device, self.config.battery_channel)
        self._charge_pin_ready = True

    def read_voltages(self) -> tuple[float, float]:
        if self._contact_channel is None or self._battery_channel is None:
            raise RuntimeError("Charging controller not setup.")
        return float(self._contact_channel.voltage), float(self._battery_channel.voltage)

    def evaluate(self, *, contact_voltage_v: float, battery_voltage_v: float) -> ChargingDecision:
        contact_detected = contact_voltage_v > self.config.contact_threshold_v
        battery_in_range = abs(battery_voltage_v - self.config.battery_nominal_v) <= self.config.battery_tolerance_v
        charge_enabled = contact_detected and battery_in_range
        if charge_enabled:
            reason = "Dock contact valid and battery voltage within charging band."
        elif not contact_detected:
            reason = "Dock contact voltage below threshold."
        else:
            reason = "Battery voltage outside safe charging band."
        return ChargingDecision(
            contact_voltage_v=contact_voltage_v,
            battery_voltage_v=battery_voltage_v,
            contact_detected=contact_detected,
            battery_in_range=battery_in_range,
            charge_enabled=charge_enabled,
            reason=reason,
        )

    def apply(self, decision: ChargingDecision) -> None:
        if not self._charge_pin_ready:
            raise RuntimeError("Charging controller not setup.")
        self.GPIO.output(
            self.config.charge_enable_pin,
            self.GPIO.HIGH if decision.charge_enabled else self.GPIO.LOW,
        )

    def run_cycle(self) -> ChargingDecision:
        contact_voltage_v, battery_voltage_v = self.read_voltages()
        decision = self.evaluate(
            contact_voltage_v=contact_voltage_v,
            battery_voltage_v=battery_voltage_v,
        )
        self.apply(decision)
        return decision

    def run(self) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.setup()
        decisions: list[dict[str, Any]] = []
        final_pin_state: dict[str, Any] = {}
        try:
            for _ in range(self.config.cycles):
                decision = self.run_cycle()
                decisions.append(asdict(decision))
                time.sleep(self.config.poll_interval_s)
            final_pin_state = dict(
                getattr(self.GPIO, "pin_state", {}).get(self.config.charge_enable_pin, {})
            )
        finally:
            self.GPIO.cleanup()
        result = {
            "config": {
                **asdict(self.config),
                "output_dir": str(self.config.output_dir),
            },
            "used_mock_gpio": self._mock_gpio,
            "used_mock_board": self._mock_board,
            "used_mock_busio": self._mock_busio,
            "used_mock_ads": self._mock_ads,
            "decisions": decisions,
            "final_pin_state": final_pin_state,
        }
        output_path = self.config.output_dir / "charging_decisions.json"
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["output_path"] = str(output_path)
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dock charging GPIO safety controller")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--charge-enable-pin", type=int, default=17)
    parser.add_argument("--contact-channel", type=int, default=0)
    parser.add_argument("--battery-channel", type=int, default=1)
    parser.add_argument("--contact-threshold-v", type=float, default=0.5)
    parser.add_argument("--battery-nominal-v", type=float, default=16.8)
    parser.add_argument("--battery-tolerance-v", type=float, default=1.5)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ChargingConfig(
        charge_enable_pin=args.charge_enable_pin,
        contact_channel=args.contact_channel,
        battery_channel=args.battery_channel,
        contact_threshold_v=args.contact_threshold_v,
        battery_nominal_v=args.battery_nominal_v,
        battery_tolerance_v=args.battery_tolerance_v,
        output_dir=args.output_dir,
        cycles=args.cycles,
        poll_interval_s=args.poll_interval,
    )
    controller = GPIOChargingController(config)
    result = controller.run()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
