#!/usr/bin/env bash
set -euo pipefail

write_status() {
  python3 - "$1" "$2" <<'PY'
from __future__ import annotations
import json, sys, time
from pathlib import Path
path = Path('/opt/skylink2/artifacts/demo/job_status.json')
payload = {
    'step': sys.argv[1],
    'detail': sys.argv[2],
    'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2) + "\n", encoding='utf-8')
print(json.dumps(payload), flush=True)
PY
}

reset_environment_file() {
  cat >/etc/environment <<'EOF'
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EOF
}

upload_tmpfiles() {
  local source="$1"
  local remote_name="$2"
  if [ ! -f "$source" ]; then
    return 1
  fi
  local response
  response="$(curl -fsS -F "file=@${source};filename=${remote_name}" https://tmpfiles.org/api/v1/upload)"
  python3 - "$response" <<'PY'
from __future__ import annotations
import json, sys
raw = sys.argv[1]
url = json.loads(raw)['data']['url']
print(url.replace('http://tmpfiles.org/', 'https://tmpfiles.org/dl/'), flush=True)
PY
}

wait_for_px4_ready() {
  python3 - <<'PY'
from __future__ import annotations
import time
from pathlib import Path

log_path = Path('/opt/skylink2/artifacts/demo/px4.log')
patterns = (
    'Startup script returned successfully',
    'Ready for takeoff!',
    'INFO  [mavlink] mode: Normal',
)
deadline = time.time() + 1800
while time.time() < deadline:
    text = log_path.read_text(encoding='utf-8', errors='ignore') if log_path.exists() else ''
    if any(pattern in text for pattern in patterns):
        print('PX4 readiness markers detected in px4.log', flush=True)
        raise SystemExit(0)
    time.sleep(5)
raise SystemExit('Timed out waiting for PX4 SITL readiness')
PY
}

run_px4_ubuntu_setup() {
  # `ubuntu.sh` exits successfully after consuming enough `yes` input, which leaves
  # `yes` terminated by SIGPIPE. With `pipefail` enabled that would incorrectly abort
  # the whole bootstrap despite the setup succeeding.
  set +o pipefail
  yes | bash ./Tools/setup/ubuntu.sh --no-nuttx
  local status=$?
  set -o pipefail
  return "$status"
}

export DEBIAN_FRONTEND=noninteractive
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

write_status bootstrap 'installing base packages'
apt-get update
apt-get install -y --no-install-recommends \
  bash ca-certificates curl git jq lsb-release python3 python3-pip python3-venv rsync wget iproute2 net-tools
reset_environment_file

rm -rf /opt/skylink2
git clone --depth 1 --branch codex-px4-final-20260417 https://github.com/AbdullahMadoun/SeniorProject.git /opt/skylink2
mkdir -p /opt/skylink2/artifacts/demo

write_status px4_clone 'cloning PX4-Autopilot v1.14.3'
mkdir -p /opt/skylink2/vendor
if [ ! -d /opt/skylink2/vendor/PX4-Autopilot ]; then
  git clone https://github.com/PX4/PX4-Autopilot.git --depth 1 --branch v1.14.3 --recurse-submodules --shallow-submodules /opt/skylink2/vendor/PX4-Autopilot
fi
(git -C /opt/skylink2/vendor/PX4-Autopilot/platforms/nuttx/NuttX/nuttx fetch --tags --force origin || true)

write_status deps 'running PX4 ubuntu setup'
cd /opt/skylink2/vendor/PX4-Autopilot
reset_environment_file
run_px4_ubuntu_setup
reset_environment_file

write_status venv 'creating autonomy virtual environment'
python3 -m venv /opt/skylink2/autonomy/.venv
source /opt/skylink2/autonomy/.venv/bin/activate
python -m pip install --upgrade pip wheel 'setuptools<82'
python -m pip install mavsdk numpy pymavlink psutil pyulog fastapi uvicorn
python -m pip install --force-reinstall 'empy==3.3.4'

write_status px4_start 'starting PX4 SITL build and runtime'
(
  cd /opt/skylink2/vendor/PX4-Autopilot
  env HEADLESS=1 make px4_sitl gz_x500 2>&1 | tee /opt/skylink2/artifacts/demo/px4.log
) &

wait_for_px4_ready

write_status record 'running record_px4_landing_demo.py against live SITL'
cd /opt/skylink2
write_status companion 'starting simulated companion camera loop'
export SKYLINK_CAMERA_CALIBRATION="/opt/skylink2/autonomy/fixtures/sim_calibration.json"
export SKYLINK_ENABLE_COMPANION_SIM=1
/opt/skylink2/autonomy/.venv/bin/python -m autonomy.companion.rpi_companion_sim \
  2>&1 | tee /opt/skylink2/artifacts/demo/companion.log &
COMPANION_PID=$!
sleep 2
if /opt/skylink2/autonomy/.venv/bin/python /opt/skylink2/autonomy/scripts/record_px4_landing_demo.py 2>&1 | tee /opt/skylink2/artifacts/demo/record.log; then
  kill "${COMPANION_PID}" 2>/dev/null || true
  write_status upload 'uploading generated artifacts'
  JSON_URL="$(upload_tmpfiles /opt/skylink2/artifacts/demo/landing_trajectory.json landing_trajectory.bin)"
  HTML_URL="$(upload_tmpfiles /opt/skylink2/artifacts/demo/precision_landing_3d_demo.html precision_landing_3d_demo.bin)"
  echo "LANDING_TRAJECTORY_URL=${JSON_URL}"
  echo "LANDING_DEMO_HTML_URL=${HTML_URL}"
  write_status complete 'artifacts uploaded to temporary download URLs'
else
  kill "${COMPANION_PID}" 2>/dev/null || true
  write_status upload 'uploading failure logs'
  RECORD_URL="$(upload_tmpfiles /opt/skylink2/artifacts/demo/record.log record.log.bin || true)"
  PX4_URL="$(upload_tmpfiles /opt/skylink2/artifacts/demo/px4.log px4.log.bin || true)"
  COMPANION_URL="$(upload_tmpfiles /opt/skylink2/artifacts/demo/companion.log companion.log.bin || true)"
  echo "RECORD_LOG_URL=${RECORD_URL}"
  echo "PX4_LOG_URL=${PX4_URL}"
  echo "COMPANION_LOG_URL=${COMPANION_URL}"
  write_status failed 'record_px4_landing_demo.py failed; inspect uploaded logs'
  exit 1
fi
