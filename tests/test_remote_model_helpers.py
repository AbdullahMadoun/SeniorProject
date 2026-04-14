from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from remote_model_helpers import resolve_frontend_connection, select_best_vast_offer  # noqa: E402


class RemoteModelHelpersTests(unittest.TestCase):
    def test_select_best_vast_offer_prefers_configured_gpu_order(self) -> None:
        offers = [
            {
                "id": 11,
                "gpu_name": "A100",
                "verified": True,
                "rentable": True,
                "direct_port_count": 2,
                "reliability": 0.995,
                "gpu_total_ram": 81920,
                "dph_total": 2.20,
                "dlperf": 30,
            },
            {
                "id": 22,
                "gpu_name": "RTX 4090",
                "verified": True,
                "rentable": True,
                "direct_port_count": 1,
                "reliability": 0.991,
                "gpu_total_ram": 24576,
                "dph_total": 0.92,
                "dlperf": 18,
            },
            {
                "id": 33,
                "gpu_name": "L40S",
                "verified": True,
                "rentable": True,
                "direct_port_count": 1,
                "reliability": 0.992,
                "gpu_total_ram": 46080,
                "dph_total": 1.18,
                "dlperf": 24,
            },
        ]

        selected = select_best_vast_offer(
            offers,
            preferred_gpu_names=["L40S", "RTX 4090", "A100"],
            max_total_hour=2.5,
            min_gpu_ram_gb=24,
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], 33)

    def test_select_best_vast_offer_filters_unusable_offers(self) -> None:
        offers = [
            {
                "id": 1,
                "gpu_name": "RTX 4090",
                "verified": False,
                "rentable": True,
                "direct_port_count": 1,
                "reliability": 0.99,
                "gpu_total_ram": 24576,
                "dph_total": 0.80,
            },
            {
                "id": 2,
                "gpu_name": "RTX 4090",
                "verified": True,
                "rentable": True,
                "direct_port_count": 0,
                "reliability": 0.99,
                "gpu_total_ram": 24576,
                "dph_total": 0.70,
            },
            {
                "id": 3,
                "gpu_name": "RTX 4090",
                "verified": True,
                "rentable": True,
                "direct_port_count": 1,
                "reliability": 0.96,
                "gpu_total_ram": 24576,
                "dph_total": 0.60,
            },
        ]

        selected = select_best_vast_offer(
            offers,
            preferred_gpu_names=["RTX 4090"],
            max_total_hour=1.0,
            min_gpu_ram_gb=24,
            min_reliability=0.97,
        )

        self.assertIsNone(selected)

    def test_resolve_frontend_connection_prefers_direct_when_model_ready(self) -> None:
        resolved = resolve_frontend_connection(
            bridge_base_url="http://127.0.0.1:8001",
            model_api_url="https://example.trycloudflare.com/analyze",
            model_api_key="secret-key",
            frontend_direct_model=True,
            expose_model_key=False,
            bridge_proxy_enabled=True,
        )

        self.assertTrue(resolved["DIRECT_MODEL_ENABLED"])
        self.assertFalse(resolved["ANALYZE_VIA_BRIDGE"])
        self.assertEqual(resolved["DEFAULT_MODEL_API_URL"], "https://example.trycloudflare.com/analyze")
        self.assertEqual(resolved["DEFAULT_MODEL_API_KEY"], "secret-key")

    def test_resolve_frontend_connection_keeps_bridge_when_direct_disabled(self) -> None:
        resolved = resolve_frontend_connection(
            bridge_base_url="http://127.0.0.1:8001",
            model_api_url="https://example.trycloudflare.com/analyze",
            model_api_key="secret-key",
            frontend_direct_model=False,
            expose_model_key=False,
            bridge_proxy_enabled=True,
        )

        self.assertFalse(resolved["DIRECT_MODEL_ENABLED"])
        self.assertTrue(resolved["ANALYZE_VIA_BRIDGE"])
        self.assertEqual(resolved["DEFAULT_MODEL_API_URL"], "")
        self.assertEqual(resolved["DEFAULT_MODEL_API_KEY"], "")


if __name__ == "__main__":
    unittest.main()
