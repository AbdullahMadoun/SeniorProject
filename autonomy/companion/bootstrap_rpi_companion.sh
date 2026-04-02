#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv-pi}"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements-rpi.txt"

APT_PACKAGES=(
  python3
  python3-venv
  python3-pip
  python3-dev
  git
  i2c-tools
  python3-smbus
  libatlas-base-dev
  libopenblas-dev
  libjpeg-dev
  libtiff5-dev
  libavcodec-dev
  libavformat-dev
  libswscale-dev
  libgtk-3-dev
  pkg-config
)

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found" >&2
  exit 1
fi

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "[bootstrap] installing apt packages"
$SUDO apt-get update
$SUDO apt-get install -y "${APT_PACKAGES[@]}"

if command -v raspi-config >/dev/null 2>&1; then
  echo "[bootstrap] enabling I2C and UART"
  $SUDO raspi-config nonint do_i2c 0 || true
  $SUDO raspi-config nonint do_serial_cons 1 || true
  $SUDO raspi-config nonint do_serial_hw 0 || true
else
  echo "[bootstrap] raspi-config not found, skipping non-interactive interface enablement"
fi

echo "[bootstrap] creating virtual environment at $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip wheel setuptools
python -m pip install -r "$REQUIREMENTS_FILE"
python -m pip install opencv-contrib-python-headless

echo "[bootstrap] verifying imports"
python - <<'PY'
import importlib

required = [
    "numpy",
    "pymavlink",
    "board",
    "busio",
    "adafruit_ads1x15.ads1115",
    "cv2",
]
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)

if missing:
    raise SystemExit(f"missing imports after bootstrap: {missing}")

print("bootstrap verification passed")
PY

echo "[bootstrap] complete"

