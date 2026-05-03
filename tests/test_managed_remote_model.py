from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from managed_remote_model import ManagedRemoteModelState  # noqa: E402


class ManagedRemoteModelTests(unittest.TestCase):
    def test_vast_mode_refuses_to_lease_without_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = ManagedRemoteModelState(
                bundle_root=root,
                state_file=root / "state.json",
                log_file=root / "state.log",
                instance_file=root / "instance.txt",
            )
            env = {
                "SKYLINK_REMOTE_MODEL_PROVIDER": "vastai",
                "SKYLINK_VAST_API_KEY": "vast-token",
                "SKYLINK_REMOTE_MODEL_SSH_KEY_FILE": str(root / "missing_key"),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                with self.assertRaisesRegex(RuntimeError, "SSH private key file not found"):
                    state._resolve_ssh_target()

    def test_remote_env_contains_runtime_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = ManagedRemoteModelState(
                bundle_root=root,
                state_file=root / "state.json",
                log_file=root / "state.log",
                instance_file=root / "instance.txt",
            )
            env = {
                "SKYLINK_REMOTE_MODEL_REMOTE_PATH": "/opt/skylink-model-server",
                "SKYLINK_REMOTE_MODEL_ENABLE_VLM": "false",
                "SKYLINK_REMOTE_MODEL_VLM_MODEL": "Qwen/Qwen2.5-VL-7B-Instruct-AWQ",
                "SKYLINK_REMOTE_MODEL_PORT": "17612",
                "SKYLINK_REMOTE_MODEL_ENABLE_QUICK_TUNNEL": "true",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                rendered = state._build_remote_env("api-key", "203.0.113.10")

        self.assertIn("API_KEY=api-key", rendered)
        self.assertIn("ENABLE_VLM=false", rendered)
        self.assertIn("ENABLE_YOLO_V8=false", rendered)
        self.assertIn("MODEL_NAME=Qwen/Qwen2.5-VL-7B-Instruct-AWQ", rendered)
        self.assertIn("PUBLIC_HOST=203.0.113.10", rendered)
        self.assertIn("ENABLE_QUICK_TUNNEL=true", rendered)


if __name__ == "__main__":
    unittest.main()
