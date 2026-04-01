from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.media_binding import discover_media_bindings


class MediaBindingTests(unittest.TestCase):
    def test_discover_media_bindings_reads_video_paths_from_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            media_dir = repo_root / "artifacts" / "media" / "latest"
            media_dir.mkdir(parents=True, exist_ok=True)
            (media_dir / "README.md").write_text(
                "# Media\n\n- `gazebo.mp4`\n- `qgc.webm`\n",
                encoding="utf-8",
            )
            (media_dir / "gazebo.mp4").write_bytes(b"video")
            (media_dir / "qgc.webm").write_bytes(b"video")

            bindings = discover_media_bindings(repo_root)

            self.assertEqual(len(bindings), 2)
            self.assertEqual(bindings[0]["declared_in"], "README.md")
            self.assertTrue(bindings[0]["web_path"].startswith("/artifacts/media/latest/"))


if __name__ == "__main__":
    unittest.main()
