from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_stream import (
    LandingTargetPublisher,
    build_stationary_landing_target_samples,
    connection_string_for_endpoint,
)


class _FakeMav:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def landing_target_send(self, *args) -> None:
        self.calls.append(args)


class _FakeConnection:
    def __init__(self) -> None:
        self.mav = _FakeMav()


class LandingTargetStreamTests(unittest.TestCase):
    def test_build_stationary_landing_target_samples_uses_requested_rate(self) -> None:
        samples = build_stationary_landing_target_samples(duration_s=5.0, rate_hz=10.0)

        self.assertEqual(len(samples), 50)
        self.assertEqual(samples[-1].time_usec - samples[0].time_usec, 4_900_000)
        self.assertEqual(samples[0].frame, samples[-1].frame)

    def test_publisher_sends_all_samples(self) -> None:
        fake_connection = _FakeConnection()
        samples = build_stationary_landing_target_samples(duration_s=1.0, rate_hz=2.0)

        with patch(
            "autonomy.drone_system.landing_target_stream.mavutil.mavlink_connection",
            return_value=fake_connection,
        ), patch("autonomy.drone_system.landing_target_stream.time.sleep", return_value=None):
            publisher = LandingTargetPublisher("udpout:127.0.0.1:14550")
            sent_count = publisher.send_samples(samples, rate_hz=2.0)

        self.assertEqual(sent_count, len(samples))
        self.assertEqual(len(fake_connection.mav.calls), len(samples))
        self.assertEqual(fake_connection.mav.calls[-1][0] - fake_connection.mav.calls[0][0], 500_000)

    def test_publisher_send_sample_emits_single_message(self) -> None:
        fake_connection = _FakeConnection()
        sample = build_stationary_landing_target_samples(duration_s=1.0, rate_hz=1.0)[0]

        with patch(
            "autonomy.drone_system.landing_target_stream.mavutil.mavlink_connection",
            return_value=fake_connection,
        ):
            publisher = LandingTargetPublisher("udpout:127.0.0.1:14550")
            publisher.send_sample(sample)

        self.assertEqual(len(fake_connection.mav.calls), 1)
        self.assertEqual(fake_connection.mav.calls[0][0], sample.time_usec)

    def test_connection_string_for_endpoint_uses_gcs_by_default_target_port(self) -> None:
        self.assertEqual(
            connection_string_for_endpoint("gcs", bridge_ip="172.23.68.199"),
            "udpout:172.23.68.199:14550",
        )

    def test_connection_string_for_endpoint_rejects_unsupported_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            connection_string_for_endpoint("invalid", bridge_ip="172.23.68.199")
