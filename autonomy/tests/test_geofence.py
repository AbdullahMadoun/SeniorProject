from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.config import load_system_baseline
from autonomy.drone_system.geofence import build_home_geofence
from autonomy.drone_system.vehicle_interface import InMemoryVehicleGateway


class GeofenceTests(unittest.TestCase):
    def test_build_home_geofence_uses_home_and_radius(self) -> None:
        baseline = load_system_baseline()
        geofence = build_home_geofence(baseline.home, baseline.mission_limits.max_radius_m)
        self.assertEqual(geofence.center, baseline.home)
        self.assertEqual(geofence.radius_m, 100.0)

    def test_in_memory_gateway_stores_uploaded_geofence(self) -> None:
        async def _run() -> None:
            baseline = load_system_baseline()
            gateway = InMemoryVehicleGateway(baseline)
            await gateway.connect()
            geofence = build_home_geofence(baseline.home, baseline.mission_limits.max_radius_m)
            await gateway.upload_geofence(geofence)
            self.assertEqual(gateway.uploaded_geofence, geofence)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
