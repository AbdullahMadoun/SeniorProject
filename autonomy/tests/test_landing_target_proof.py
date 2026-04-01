from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.landing_target_proof import (
    count_bridge_direction,
    extract_ulog_relative_path,
    parse_shell_observation,
    parse_receiver_observation,
)


class LandingTargetProofTests(unittest.TestCase):
    def test_extract_ulog_relative_path_reads_logger_line(self) -> None:
        text = "INFO  [logger] Opened full log file: ./log/2026-04-01/10_10_27.ulg"
        self.assertEqual(extract_ulog_relative_path(text), "2026-04-01/10_10_27.ulg")

    def test_parse_shell_observation_detects_topic_and_never_published_state(self) -> None:
        text = "\n".join(
            (
                "TOPIC: vehicle_status",
                "never published",
                "TOPIC: landing_target_pose",
            )
        )
        observation = parse_shell_observation(text)
        self.assertTrue(observation.vehicle_status_seen)
        self.assertTrue(observation.landing_target_pose_seen)
        self.assertTrue(observation.never_published_seen)

    def test_count_bridge_direction_counts_exact_bridge_and_direction(self) -> None:
        text = "\n".join(
            (
                "[bridge] gcs host->px4 172.23.64.1:54764 -> 127.0.0.1:18570 bytes=72",
                "[bridge] gcs host->px4 172.23.64.1:54764 -> 127.0.0.1:18570 bytes=72",
                "[bridge] offboard host->px4 172.23.64.1:49220 -> 127.0.0.1:14580 bytes=72",
            )
        )
        self.assertEqual(count_bridge_direction(text, bridge_name="gcs", direction="host->px4"), 2)

    def test_parse_receiver_observation_reads_first_nonzero_decode(self) -> None:
        text = "\n".join(
            (
                "INFO  [mavlink] LANDING_TARGET rx: position_valid=1 frame=1 x=1.250 y=-0.750 z=0.000",
                "INFO  [mavlink] LANDING_TARGET rx: position_valid=1 frame=1 x=1.250 y=-0.750 z=0.000",
            )
        )
        observation = parse_receiver_observation(text)
        self.assertEqual(observation.count, 2)
        self.assertEqual(observation.first_match["position_valid"], 1)
        self.assertEqual(observation.first_match["frame"], 1)
        self.assertEqual(observation.first_match["x"], 1.25)

    def test_parse_receiver_observation_handles_wrapped_terminal_lines(self) -> None:
        text = (
            "pxh> INFO  [mavlink] LANDING_TARGET rx: position_valid=1 frame=1 x=0.000 y=-0.000 z=0.025\n"
            "\u001b[2K\n"
            "pxh> "
        )
        observation = parse_receiver_observation(text)
        self.assertEqual(observation.count, 1)
        self.assertEqual(observation.first_match["z"], 0.025)
