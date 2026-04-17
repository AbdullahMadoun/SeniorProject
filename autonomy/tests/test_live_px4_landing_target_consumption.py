from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.scripts.prove_live_px4_landing_target_consumption import (
    default_observer_connection_string,
    default_publisher_connection_string,
    resolve_host_mode,
    use_direct_px4_transport,
)


class LivePx4LandingTargetConsumptionTests(unittest.TestCase):
    def test_resolve_host_mode_defaults_to_linux_on_posix(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "autonomy.scripts.prove_live_px4_landing_target_consumption.os.name",
            "posix",
        ):
            self.assertEqual(resolve_host_mode(), "linux")

    def test_use_direct_px4_transport_defaults_true_in_linux_mode(self) -> None:
        with patch.dict("os.environ", {"SKYLINK_PX4_HOST_MODE": "linux"}, clear=True):
            self.assertTrue(use_direct_px4_transport())

    def test_use_direct_px4_transport_accepts_explicit_false_override(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SKYLINK_PX4_HOST_MODE": "linux",
                "LANDING_TARGET_DIRECT_PX4": "0",
            },
            clear=True,
        ):
            self.assertFalse(use_direct_px4_transport())

    def test_default_observer_connection_string_uses_direct_px4_port(self) -> None:
        self.assertEqual(
            default_observer_connection_string(endpoint="gcs", direct_px4=True),
            "udpout:127.0.0.1:18570",
        )

    def test_default_publisher_connection_string_uses_bridge_ip_when_not_direct(self) -> None:
        self.assertEqual(
            default_publisher_connection_string(
                endpoint="gcs",
                direct_px4=False,
                bridge_ip="172.23.68.199",
            ),
            "udpout:172.23.68.199:14550",
        )
