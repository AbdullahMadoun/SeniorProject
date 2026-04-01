from __future__ import annotations

from pathlib import Path
import sys


AUTONOMY_ROOT = Path(__file__).resolve().parents[1]
if str(AUTONOMY_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_ROOT))

from drone_system.capability_report import generate_report, to_markdown


def main() -> None:
    report = generate_report()
    output_path = AUTONOMY_ROOT / "docs" / "phase0_capability_report.md"
    output_path.write_text(to_markdown(report), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
