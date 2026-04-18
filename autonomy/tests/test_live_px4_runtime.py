from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_projection import DockTarget
from autonomy.drone_system.live_px4_runtime import stream_live_projected_targets, wait_for_mission_completion
from autonomy.drone_system.models import MissionProgress, VehicleLocalPose, VehicleMode, VehicleSnapshot, Waypoint


class _FakeGateway:
    def __init__(self, snapshots: list[VehicleSnapshot], local_pose: VehicleLocalPose) -> None:
        self._snapshots = list(snapshots)
        self._index = 0
        self._local_pose = local_pose

    async def get_snapshot(self) -> VehicleSnapshot:
        snapshot = self._snapshots[min(self._index, len(self._snapshots) - 1)]
        self._index += 1
        return snapshot

    async def get_local_pose(self) -> VehicleLocalPose:
        return self._local_pose


class _FakePublisher:
    def __init__(self) -> None:
        self.samples: list[object] = []

    def send_sample(self, sample: object) -> None:
        self.samples.append(sample)


class LivePx4RuntimeTests(unittest.TestCase):
    def test_wait_for_mission_completion_tracks_until_progress_reaches_total(self) -> None:
        gateway = _FakeGateway(
            snapshots=[
                VehicleSnapshot(
                    connected=True,
                    armed=True,
                    in_air=True,
                    mode=VehicleMode.MISSION,
                    battery_percent=99.0,
                    position=Waypoint(lat=47.0, lon=8.0, alt_m=10.0),
                    mission_progress=MissionProgress(current=0, total=3),
                ),
                VehicleSnapshot(
                    connected=True,
                    armed=True,
                    in_air=True,
                    mode=VehicleMode.MISSION,
                    battery_percent=98.0,
                    position=Waypoint(lat=47.0, lon=8.0, alt_m=10.0),
                    mission_progress=MissionProgress(current=2, total=3),
                ),
                VehicleSnapshot(
                    connected=True,
                    armed=True,
                    in_air=True,
                    mode=VehicleMode.RETURN_TO_LAUNCH,
                    battery_percent=97.0,
                    position=Waypoint(lat=47.0, lon=8.0, alt_m=10.0),
                    mission_progress=MissionProgress(current=3, total=3),
                ),
            ],
            local_pose=VehicleLocalPose(north_m=15.0, east_m=20.0, down_m=-10.0, yaw_deg=45.0),
        )

        async def _sleep(_seconds: float) -> None:
            return None

        with patch("autonomy.drone_system.live_px4_runtime.asyncio.sleep", side_effect=_sleep):
            observations = asyncio.run(wait_for_mission_completion(gateway, timeout_s=5.0))

        self.assertEqual(len(observations), 3)
        self.assertEqual(observations[-1]["snapshot"]["mission_progress"]["current"], 3)
        self.assertEqual(observations[-1]["snapshot"]["mission_progress"]["total"], 3)
        self.assertEqual(observations[-1]["snapshot"]["mode"], "return_to_launch")

    def test_stream_live_projected_targets_requires_touchdown(self) -> None:
        gateway = _FakeGateway(
            snapshots=[
                VehicleSnapshot(
                    connected=True,
                    armed=True,
                    in_air=True,
                    mode=VehicleMode.RETURN_TO_LAUNCH,
                    battery_percent=90.0,
                    position=Waypoint(lat=47.0, lon=8.0, alt_m=2.0),
                )
            ],
            local_pose=VehicleLocalPose(north_m=0.0, east_m=0.0, down_m=-2.0, yaw_deg=0.0),
        )
        publisher = _FakePublisher()

        async def _sleep(_seconds: float) -> None:
            return None

        with patch("autonomy.drone_system.live_px4_runtime.asyncio.sleep", side_effect=_sleep):
            with self.assertRaisesRegex(RuntimeError, "confirmed touchdown"):
                asyncio.run(
                    stream_live_projected_targets(
                        gateway,
                        publisher,
                        DockTarget(north_m=0.0, east_m=0.0, down_m=0.0),
                        rate_hz=2.0,
                        duration_s=1.0,
                    )
                )

    def test_stream_live_projected_targets_stops_after_ground_streak(self) -> None:
        gateway = _FakeGateway(
            snapshots=[
                VehicleSnapshot(
                    connected=True,
                    armed=False,
                    in_air=False,
                    mode=VehicleMode.LAND,
                    battery_percent=90.0,
                    position=Waypoint(lat=47.0, lon=8.0, alt_m=0.0),
                )
            ],
            local_pose=VehicleLocalPose(north_m=0.0, east_m=0.0, down_m=0.0, yaw_deg=0.0),
        )
        publisher = _FakePublisher()

        async def _sleep(_seconds: float) -> None:
            return None

        with patch("autonomy.drone_system.live_px4_runtime.asyncio.sleep", side_effect=_sleep):
            records = asyncio.run(
                stream_live_projected_targets(
                    gateway,
                    publisher,
                    DockTarget(north_m=0.0, east_m=0.0, down_m=0.0),
                    rate_hz=5.0,
                    duration_s=5.0,
                )
            )

        self.assertEqual(len(records), 3)
        self.assertEqual(len(publisher.samples), 3)
        self.assertFalse(records[-1]["snapshot"]["in_air"])


if __name__ == "__main__":
    unittest.main()
