from __future__ import annotations

from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.precision_landing import (
    PrecisionLandingSimulator,
    write_precision_landing_artifacts,
)


def main() -> None:
    baseline = load_system_baseline()
    simulator = PrecisionLandingSimulator(baseline)
    results, step_map = simulator.run_default_scenarios()
    output_dir = REPO_ROOT / "artifacts" / "precision_landing" / "latest"
    destination = write_precision_landing_artifacts(output_dir, results, step_map)
    print(f"Precision landing artifacts written to: {destination}")


if __name__ == "__main__":
    main()
