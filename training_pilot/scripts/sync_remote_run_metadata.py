from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll and pull small remote run metadata files to a local directory.")
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-port", type=int, required=True)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-key", required=True)
    parser.add_argument("--remote-file", action="append", required=True, help="Remote file path to mirror. Repeat as needed.")
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--idle-timeout-seconds", type=float, default=28800.0)
    parser.add_argument("--connect-timeout-seconds", type=int, default=20)
    parser.add_argument("--scp-retries", type=int, default=4)
    parser.add_argument("--scp-retry-delay-seconds", type=float, default=10.0)
    return parser.parse_args()


def remote_target(args: argparse.Namespace) -> str:
    return f"{args.ssh_user}@{args.ssh_host}"


def host_key_options() -> list[str]:
    null_path = "NUL" if os.name == "nt" else "/dev/null"
    return [
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={null_path}",
    ]


def run_ssh(args: argparse.Namespace, remote_command: str) -> subprocess.CompletedProcess[str]:
    command = [
        "ssh",
        *host_key_options(),
        "-o",
        f"ConnectTimeout={args.connect_timeout_seconds}",
        "-i",
        args.ssh_key,
        "-p",
        str(args.ssh_port),
        remote_target(args),
        remote_command,
    ]
    return subprocess.run(command, check=True, capture_output=True, text=True)


def probe_remote_files(args: argparse.Namespace) -> dict[str, dict[str, object]]:
    payload = json.dumps(args.remote_file)
    remote_python = f"""
import json
from pathlib import Path
paths = json.loads({payload!r})
out = {{}}
for raw in paths:
    path = Path(raw)
    out[raw] = {{
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() and path.is_file() else -1,
        "mtime": path.stat().st_mtime if path.exists() and path.is_file() else -1,
        "name": path.name,
    }}
print(json.dumps(out))
"""
    completed = run_ssh(args, f"python3 - <<'PY'\n{remote_python}\nPY")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Remote metadata probe returned no output.")
    return json.loads(lines[-1])


def scp_pull(args: argparse.Namespace, remote_file: str, local_file: Path) -> None:
    local_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = local_file.with_name(f"{local_file.name}.partial")
    if temp_file.exists():
        temp_file.unlink()
    command = [
        "scp",
        *host_key_options(),
        "-o",
        f"ConnectTimeout={args.connect_timeout_seconds}",
        "-o",
        "ServerAliveInterval=20",
        "-o",
        "ServerAliveCountMax=6",
        "-i",
        args.ssh_key,
        "-P",
        str(args.ssh_port),
        f"{remote_target(args)}:{remote_file}",
        str(temp_file),
    ]
    retries = max(int(args.scp_retries), 1)
    delay = float(args.scp_retry_delay_seconds)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            subprocess.run(command, check=True)
            temp_file.replace(local_file)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if temp_file.exists():
                temp_file.unlink()
            if attempt == retries:
                break
            print(
                f"[sync-metadata] scp attempt {attempt}/{retries} failed for {remote_file}: {exc}. "
                f"Retrying in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    if temp_file.exists():
        temp_file.unlink()
    if last_error is not None:
        raise last_error


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if shutil.which("ssh") is None or shutil.which("scp") is None:
        raise SystemExit("Missing ssh/scp on this machine.")

    local_dir = Path(args.local_dir).resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    state_path = local_dir / "metadata_sync_state.json"
    state = load_state(state_path)
    known = {str(key): value for key, value in state.get("files", {}).items()}
    unchanged_since = time.time()

    while True:
        try:
            remote = probe_remote_files(args)
        except Exception as exc:  # noqa: BLE001
            print(f"[sync-metadata] remote probe failed: {exc}", flush=True)
            if time.time() - unchanged_since >= args.idle_timeout_seconds:
                break
            time.sleep(args.poll_seconds)
            continue

        any_change = False
        any_existing = False
        for remote_file, info in remote.items():
            exists = bool(info.get("exists"))
            if not exists:
                continue
            any_existing = True
            size = int(info.get("size", -1))
            mtime = float(info.get("mtime", -1))
            name = str(info.get("name"))
            fingerprint = {"size": size, "mtime": mtime}
            if known.get(remote_file) == fingerprint and (local_dir / name).exists():
                continue
            try:
                scp_pull(args, remote_file, local_dir / name)
            except Exception as exc:  # noqa: BLE001
                print(f"[sync-metadata] failed to pull {remote_file}: {exc}", flush=True)
                continue
            known[remote_file] = fingerprint
            any_change = True
            print(f"[sync-metadata] synced {remote_file} -> {local_dir / name}", flush=True)

        if any_change or any_existing:
            unchanged_since = time.time()
            save_state(state_path, {"files": known})

        if time.time() - unchanged_since >= args.idle_timeout_seconds:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
