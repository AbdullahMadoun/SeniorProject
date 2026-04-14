from __future__ import annotations

from pathlib import Path
import tempfile
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.models import Waypoint
from autonomy.drone_system.synthetic_telemetry import generate_synthetic_telemetry_csv


class SyntheticTelemetryTests(unittest.TestCase):
    def test_csv_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "telemetry.csv"
            generated = generate_synthetic_telemetry_csv(
                output_csv=output,
                home=Waypoint(lat=26.307114, lon=50.145884, alt_m=25.0),
                width_m=44.0,
                height_m=44.0,
                row_spacing_m=5.0,
                altitude_m=25.0,
                frames=30,
                fps=10.0,
            )
            self.assertTrue(generated.exists())
            lines = generated.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 31)


if __name__ == "__main__":
    unittest.main()
