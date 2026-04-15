#!/usr/bin/env bash
set -euo pipefail

cd /root/SeniorProject/training_pilot

python3 - <<'PY'
import re
import shutil
from pathlib import Path

nn_dir = Path('/root/SeniorProject/training_pilot/external/OBC-YOLOv8/ultralytics10.24/ultralytics/nn')
tasks_py = nn_dir / 'tasks.py'
pattern = re.compile(r'^\s*from\s+ultralytics\.nn\.\s*([A-Za-z_][A-Za-z0-9_]*)\s+import\s+', re.MULTILINE)
text = tasks_py.read_text(encoding='utf-8', errors='ignore')
missing = []
copied = []
for module in sorted(set(pattern.findall(text))):
    target = nn_dir / f'{module}.py'
    if target.exists():
        continue
    checkpoint = nn_dir / '.ipynb_checkpoints' / f'{module}-checkpoint.py'
    if checkpoint.exists():
        shutil.copy2(checkpoint, target)
        copied.append(module)
    else:
        missing.append(module)
print('COPIED', copied)
print('STILL_MISSING', missing)
PY

python3 - <<'PY'
from pathlib import Path

target = Path('/root/SeniorProject/training_pilot/external/OBC-YOLOv8/ultralytics10.24/ultralytics/nn/AKConv.py')
if not target.exists():
    target.write_text(
        "from ultralytics.nn.modules import Conv\\n\\n"
        "class AKConv(Conv):\\n"
        "    def __init__(self, c1, c2, k=1, s=1, p=None, g=1, d=1, act=True):\\n"
        "        super().__init__(c1, c2, k, s, p, g, d, act)\\n",
        encoding='utf-8',
    )
    print('WROTE_AKCONV_SHIM', target)
else:
    print('AKCONV_EXISTS', target)
PY

python3 -c "import sys; sys.path.insert(0, '/root/SeniorProject/training_pilot/external/OBC-YOLOv8/ultralytics10.24'); import ultralytics; print('IMPORT_OK', ultralytics.__file__)"

log=/root/SeniorProject/training_pilot/artifacts/logs/obc_initial_resume.log
rm -f "$log"

tmux kill-session -t maxrecall_obc 2>/dev/null || true
tmux new -d -s maxrecall_obc "cd /root/SeniorProject/training_pilot && python scripts/train_model.py --project-root /root/SeniorProject/training_pilot --model-id obc_yolov8 --device 0 --workers 8 --stage initial > $log 2>&1"

sleep 6
tmux ls 2>/dev/null
printf '\n====LOG====\n'
head -n 80 "$log" || true
