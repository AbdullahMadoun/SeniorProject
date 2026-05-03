from __future__ import annotations

import re
import shutil
from pathlib import Path

from common import resolve_project_root


def main() -> None:
    project_root = resolve_project_root(None)
    nn_dir = project_root / "external" / "OBC-YOLOv8" / "ultralytics10.24" / "ultralytics" / "nn"
    tasks_py = nn_dir / "tasks.py"
    if not tasks_py.exists():
        raise FileNotFoundError(f"Missing OBC tasks.py: {tasks_py}")

    pattern = re.compile(r"^\s*from\s+ultralytics\.nn\.\s*([A-Za-z_][A-Za-z0-9_]*)\s+import\s+", re.MULTILINE)
    modules = sorted(set(pattern.findall(tasks_py.read_text(encoding="utf-8", errors="ignore"))))

    copied: list[str] = []
    missing: list[str] = []
    for module in modules:
        if module == "modules":
            continue
        target = nn_dir / f"{module}.py"
        if target.exists():
            continue
        checkpoint = nn_dir / ".ipynb_checkpoints" / f"{module}-checkpoint.py"
        if checkpoint.exists():
            shutil.copy2(checkpoint, target)
            copied.append(module)
        else:
            missing.append(module)

    akconv = nn_dir / "AKConv.py"
    if not akconv.exists():
        akconv.write_text(
            "from ultralytics.nn.modules import Conv\n\n"
            "class AKConv(Conv):\n"
            "    def __init__(self, c1, c2, k=1, s=1, p=None, g=1, d=1, act=True):\n"
            "        super().__init__(c1, c2, k, s, p, g, d, act)\n",
            encoding="utf-8",
        )

    print({"copied": copied, "missing": missing, "akconv_present": akconv.exists()})


if __name__ == "__main__":
    main()
