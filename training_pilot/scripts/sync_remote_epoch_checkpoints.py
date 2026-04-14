from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll a remote Ultralytics run and pull epoch checkpoints every N epochs.")
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-port", type=int, required=True)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-key", required=True)
    parser.add_argument("--remote-run-dir", required=True)
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--epoch-step", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--idle-timeout-seconds", type=float, default=28800.0)
    parser.add_argument("--connect-timeout-seconds", type=int, default=10)
    parser.add_argument("--scp-retries", type=int, default=4)
    parser.add_argument("--scp-retry-delay-seconds", type=float, default=15.0)
    return parser.parse_args()


def remote_target(args: argparse.Namespace) -> str:
    return f"{args.ssh_user}@{args.ssh_host}"


def run_ssh(args: argparse.Namespace, remote_command: str) -> subprocess.CompletedProcess[str]:
    command = [
        "ssh",
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


def fetch_remote_state(args: argparse.Namespace) -> dict:
    remote_python = f"""
import csv, json, re
from pathlib import Path
run_dir = Path({args.remote_run_dir!r})
weights_dir = run_dir / 'weights'
results_csv = run_dir / 'results.csv'
epoch_files = []
if weights_dir.exists():
    for path in sorted(weights_dir.glob('epoch*.pt')):
        match = re.fullmatch(r'epoch(\\d+)\\.pt', path.name)
        if match:
            epoch_files.append({{'epoch': int(match.group(1)), 'name': path.name, 'size': path.stat().st_size}})
terminal_files = []
if weights_dir.exists():
    for path in [weights_dir / 'best.pt', weights_dir / 'last.pt']:
        if path.exists():
            terminal_files.append({{'name': path.name, 'size': path.stat().st_size}})
latest_epoch = None
if results_csv.exists():
    with results_csv.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    if rows:
        latest_epoch = int(float(rows[-1]['epoch']))
print(json.dumps({{
    'run_dir_exists': run_dir.exists(),
    'weights_dir_exists': weights_dir.exists(),
    'latest_epoch': latest_epoch,
    'epoch_files': epoch_files,
    'terminal_files': terminal_files,
}}))
"""
    completed = run_ssh(args, f"python3 - <<'PY'\n{remote_python}\nPY")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Remote state probe returned no output.")
    return json.loads(lines[-1])


def scp_pull(args: argparse.Namespace, remote_file: str, local_file: Path) -> None:
    local_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = local_file.with_name(f"{local_file.name}.partial")
    if temp_file.exists():
        temp_file.unlink()
    command = [
        "scp",
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
    retries = max(int(getattr(args, "scp_retries", 1)), 1)
    delay = float(getattr(args, "scp_retry_delay_seconds", 0.0))
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
                f"[sync-checkpoints] scp attempt {attempt}/{retries} failed for {remote_file}: {exc}. "
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
        return {"synced_epochs": [], "terminal_file_sizes": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if shutil.which("ssh") is None or shutil.which("scp") is None:
        raise SystemExit("Missing ssh/scp on this machine.")

    local_dir = Path(args.local_dir).resolve()
    state_path = local_dir / "sync_state.json"
    state = load_state(state_path)
    synced_epochs = {int(value) for value in state.get("synced_epochs", [])}
    synced_terminal_sizes = {
        str(key): int(value)
        for key, value in state.get("terminal_file_sizes", {}).items()
    }
    unchanged_since = time.time()

    while True:
        try:
            remote_state = fetch_remote_state(args)
        except Exception as exc:  # noqa: BLE001
            print(f"[sync-checkpoints] remote probe failed: {exc}", flush=True)
            if time.time() - unchanged_since >= args.idle_timeout_seconds:
                break
            time.sleep(args.poll_seconds)
            continue

        latest_epoch = remote_state.get("latest_epoch")
        if latest_epoch is not None:
            unchanged_since = time.time()

        eligible = [
            entry for entry in remote_state.get("epoch_files", [])
            if int(entry["epoch"]) > 0 and int(entry["epoch"]) % args.epoch_step == 0
        ]
        for entry in eligible:
            epoch = int(entry["epoch"])
            if epoch in synced_epochs:
                continue
            remote_file = f"{args.remote_run_dir}/weights/{entry['name']}"
            local_file = local_dir / entry["name"]
            try:
                scp_pull(args, remote_file, local_file)
            except Exception as exc:  # noqa: BLE001
                print(f"[sync-checkpoints] failed to pull epoch {epoch}: {exc}", flush=True)
                continue
            synced_epochs.add(epoch)
            save_state(
                state_path,
                {
                    "synced_epochs": sorted(synced_epochs),
                    "terminal_file_sizes": synced_terminal_sizes,
                    "latest_epoch_seen": latest_epoch,
                },
            )
            print(f"[sync-checkpoints] synced {entry['name']} -> {local_file}", flush=True)

        for entry in remote_state.get("terminal_files", []):
            name = str(entry["name"])
            size = int(entry["size"])
            local_file = local_dir / name
            if synced_terminal_sizes.get(name) == size and local_file.exists():
                continue
            remote_file = f"{args.remote_run_dir}/weights/{name}"
            try:
                scp_pull(args, remote_file, local_file)
            except Exception as exc:  # noqa: BLE001
                print(f"[sync-checkpoints] failed to pull rolling {name}: {exc}", flush=True)
                continue
            synced_terminal_sizes[name] = size
            save_state(
                state_path,
                {
                    "synced_epochs": sorted(synced_epochs),
                    "terminal_file_sizes": synced_terminal_sizes,
                    "latest_epoch_seen": latest_epoch,
                },
            )
            print(f"[sync-checkpoints] synced rolling {name} -> {local_file}", flush=True)

        if latest_epoch is not None and latest_epoch >= max(synced_epochs | {0}) and time.time() - unchanged_since >= args.idle_timeout_seconds:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
