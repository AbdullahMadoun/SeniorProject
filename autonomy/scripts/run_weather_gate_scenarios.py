from __future__ import annotations

from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.weather_scenario_runner import run_weather_scenarios_to_directory


def main() -> None:
    baseline = load_system_baseline()
    output_dir = AUTONOMY_ROOT.parent / "artifacts" / "weather_scenarios" / "latest"
    result_dir = run_weather_scenarios_to_directory(baseline, output_dir)
    print(f"Weather scenario artifacts written to: {result_dir}")


if __name__ == "__main__":
    main()
