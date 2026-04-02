from __future__ import annotations

from pathlib import Path
import sys
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class UiStaticArtifactTests(unittest.TestCase):
    def test_planner_uses_leaflet_satellite_map(self) -> None:
        planner_html = (REPO_ROOT / "artifacts" / "planner" / "index.html").read_text(encoding="utf-8")

        self.assertIn("leaflet@1.9.4", planner_html)
        self.assertIn("server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile", planner_html)
        self.assertIn('L.map("mission-map"', planner_html)
        self.assertIn('<div id="mission-map"></div>', planner_html)
        self.assertNotIn("<canvas id=\"mission-map\"", planner_html)

    def test_planner_and_dashboard_include_layout_guards(self) -> None:
        planner_html = (REPO_ROOT / "artifacts" / "planner" / "index.html").read_text(encoding="utf-8")
        dashboard_html = (REPO_ROOT / "artifacts" / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertIn("overflow-wrap: anywhere", planner_html)
        self.assertIn("grid-template-columns: minmax(0, 1.6fr) minmax(120px, 0.8fr)", planner_html)
        self.assertIn("overflow-wrap: anywhere", dashboard_html)
        self.assertIn("action-strip", dashboard_html)
        self.assertIn("server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile", dashboard_html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto", dashboard_html)
        self.assertIn("class=\"fpv-media\"", dashboard_html)
        self.assertIn("visibility: hidden", dashboard_html)
        self.assertIn("font-size: 0", dashboard_html)
        self.assertIn("class=\"fpv-bottom\"", dashboard_html)
        self.assertIn("class=\"status-copy\"", dashboard_html)


if __name__ == "__main__":
    unittest.main()
