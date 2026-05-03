from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.geometry import generate_lawnmower_pattern, validate_mission_area
from autonomy.drone_system.models import Waypoint


class GeometryTests(unittest.TestCase):
    def test_area_validation_accepts_valid_pattern(self) -> None:
        home = Waypoint(lat=26.307114, lon=50.145884, alt_m=25.0)
        waypoints = generate_lawnmower_pattern(home, 44.0, 44.0, 11.0, 25.0)
        result = validate_mission_area(waypoints[:4], max_area_m2=2500.0, max_dimension_m=50.0)
        self.assertLessEqual(result.area_m2, 2500.0)
        self.assertLessEqual(result.north_span_m, 50.0)
        self.assertLessEqual(result.east_span_m, 50.0)

    def test_area_validation_rejects_large_pattern(self) -> None:
        waypoints = [
            Waypoint(lat=26.307000, lon=50.145000, alt_m=25.0),
            Waypoint(lat=26.308700, lon=50.145000, alt_m=25.0),
            Waypoint(lat=26.308700, lon=50.146700, alt_m=25.0),
            Waypoint(lat=26.307000, lon=50.146700, alt_m=25.0),
        ]
        with self.assertRaises(ValueError):
            validate_mission_area(waypoints, max_area_m2=2500.0, max_dimension_m=50.0)


if __name__ == "__main__":
    unittest.main()
