from __future__ import annotations

from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.showcase_builder import default_replay_bundle_manifest_path, write_showcase


OUTPUT_DIR = REPO_ROOT / "artifacts" / "showcase" / "latest"


def main() -> None:
    manifest_path = default_replay_bundle_manifest_path(REPO_ROOT)
    showcase_data = write_showcase(
        replay_bundle_manifest_path=manifest_path,
        output_dir=OUTPUT_DIR,
    )
    print(f"Showcase written to: {OUTPUT_DIR}")
    print(f"Dock proof status: {showcase_data['dock']['proof_status']}")


if __name__ == "__main__":
    main()
