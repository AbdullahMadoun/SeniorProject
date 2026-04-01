from __future__ import annotations

from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.replay_bundle import build_replay_bundle


OUTPUT_DIR = REPO_ROOT / "artifacts" / "replay_bundle" / "latest"


def main() -> None:
    manifest = build_replay_bundle(
        repo_root=REPO_ROOT,
        output_dir=OUTPUT_DIR,
    )
    print(f"Replay bundle written to: {OUTPUT_DIR}")
    print(f"Dock proof status: {manifest['summary']['dock_proof_status']}")


if __name__ == "__main__":
    main()
