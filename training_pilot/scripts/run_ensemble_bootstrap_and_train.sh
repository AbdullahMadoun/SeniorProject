#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="${DEVICE:-0}"
WORKERS="${WORKERS:-8}"
PYTHON_BIN="${PYTHON_BIN:-python}"

python_import_check() {
  local code="$1"
  "${PYTHON_BIN}" -c "$code"
}

cd "$ROOT_DIR"

echo "=== ENSEMBLE BOOTSTRAP START ==="
date
"${PYTHON_BIN}" --version
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader

if ! "${PYTHON_BIN}" - <<'PY'
import importlib
mods = [
    "ultralytics",
    "huggingface_hub",
    "yaml",
    "PIL",
    "pandas",
    "albumentations",
    "cv2",
]
missing = []
for mod in mods:
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(mod)
if missing:
    raise SystemExit(1)
PY
then
  "${PYTHON_BIN}" -m pip install -r requirements.txt
else
  echo "[ensemble] base Python requirements already satisfied; skipping full reinstall"
fi
"${PYTHON_BIN}" scripts/02_download_weights.py

if [ -f external/yolov12/requirements.txt ]; then
  sed -i 's|.*flash_attn.*\.whl.*|# removed local wheel - treated as optional by codex bootstrap|' external/yolov12/requirements.txt
fi
"${PYTHON_BIN}" -m pip install -e external/yolov12
if ! python_import_check 'import ultralytics, timm'; then
  echo "[ensemble] yolov12 import smoke test failed after editable install" >&2
  exit 1
fi

if [ -f external/OBC-YOLOv8/requirements.txt ]; then
  "${PYTHON_BIN}" scripts/repair_obc_repo.py
  if ! python_import_check 'import sys; sys.path.insert(0, "external/OBC-YOLOv8/ultralytics10.24"); import ultralytics'; then
    echo "[ensemble] OBC import smoke test failed; installing repo requirements" >&2
    "${PYTHON_BIN}" -m pip install -r external/OBC-YOLOv8/requirements.txt
    "${PYTHON_BIN}" scripts/repair_obc_repo.py
  else
    echo "[ensemble] OBC import smoke test passed; skipping repo requirements"
  fi
fi

echo "[ensemble] skipping RoadDamageDetection repo requirements; using bundled weights only"

echo "=== ENSEMBLE BOOTSTRAP DONE ==="
date

echo "=== ENSEMBLE TRAIN START ==="
date
DEVICE="${DEVICE}" WORKERS="${WORKERS}" PYTHON_BIN="${PYTHON_BIN}" bash scripts/03_train_all.sh
echo "=== ENSEMBLE TRAIN DONE ==="
date
