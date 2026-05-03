from __future__ import annotations

from pathlib import Path
import sys

AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTONOMY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomy.drone_system.dashboard_builder import (
    default_replay_bundle_manifest_path,
    write_dashboard,
)


OUTPUT_DIR = REPO_ROOT / "artifacts" / "dashboard"


def main() -> None:
    manifest_path = default_replay_bundle_manifest_path(REPO_ROOT)
    dashboard_data = write_dashboard(
        replay_bundle_manifest_path=manifest_path,
        output_dir=OUTPUT_DIR,
    )
    print(f"Dashboard written to: {OUTPUT_DIR}")
    print(f"Dock proof status: {dashboard_data['latest_replay']['dock']['proof_status']}")


if __name__ == "__main__":
    main()
