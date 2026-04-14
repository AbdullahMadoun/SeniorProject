from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from sync_remote_epoch_checkpoints import fetch_remote_state, remote_target, run_ssh, scp_pull


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Watch a remote training run, keep syncing critical checkpoints, take a final local snapshot "
            "when training stops, verify key files, and optionally destroy the Vast instance."
        )
    )
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-port", type=int, required=True)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-key", required=True)
    parser.add_argument("--remote-project-root", required=True)
    parser.add_argument("--remote-run-dir", required=True)
    parser.add_argument("--train-session", default="", help="Optional tmux session name for the training process.")
    parser.add_argument("--local-export-root", required=True, help="Directory where the final remote snapshot will be saved.")
    parser.add_argument(
        "--local-live-cache",
        required=True,
        help="Directory where live checkpoints such as best.pt/last.pt/epoch25.pt will be mirrored during training.",
    )
    parser.add_argument("--epoch-step", type=int, default=25)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--stop-stable-polls", type=int, default=3)
    parser.add_argument(
        "--quiesce-seconds",
        type=float,
        default=120.0,
        help="Wait this long after the stop condition before taking the final snapshot, then re-probe to confirm nothing changed.",
    )
    parser.add_argument("--idle-timeout-seconds", type=float, default=43200.0)
    parser.add_argument("--connect-timeout-seconds", type=int, default=10)
    parser.add_argument("--scp-retries", type=int, default=4)
    parser.add_argument("--scp-retry-delay-seconds", type=float, default=15.0)
    parser.add_argument("--extra-remote-path", action="append", default=[])
    parser.add_argument("--instance-id", type=int, default=0)
    parser.add_argument("--api-key", default=os.getenv("VAST_API_KEY", ""))
    parser.add_argument(
        "--vast-probe-script",
        default=str(Path.home() / ".codex" / "skills" / "vast-docker-remote-compute" / "scripts" / "vast_probe.py"),
    )
    parser.add_argument("--arm-destroy", action="store_true", help="Actually destroy the instance after final verification.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate connectivity, remote paths, and current run state, then exit without monitoring or destroying.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {
            "synced_epochs": [],
            "terminal_file_sizes": {},
            "latest_epoch_seen": None,
            "final_snapshot_complete": False,
            "destroyed": False,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_local_tools() -> None:
    missing = [name for name in ("ssh", "scp") if shutil.which(name) is None]
    if missing:
        raise SystemExit(f"Missing required local tool(s): {', '.join(missing)}")


def tmux_session_alive(args: argparse.Namespace) -> bool:
    if not args.train_session.strip():
        return True
    remote_cmd = (
        f"if tmux has-session -t {json.dumps(args.train_session)} 2>/dev/null; "
        "then echo alive; else echo gone; fi"
    )
    completed = run_ssh(args, remote_cmd)
    return completed.stdout.strip().splitlines()[-1].strip() == "alive"


def remote_sha256_map(args: argparse.Namespace, remote_paths: list[str]) -> dict[str, dict[str, str | int]]:
    payload = json.dumps(remote_paths)
    remote_python = f"""
import hashlib, json
from pathlib import Path
paths = json.loads({payload!r})
out = {{}}
for raw in paths:
    path = Path(raw)
    if not path.exists():
        out[raw] = {{"exists": False}}
        continue
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    out[raw] = {{
        "exists": True,
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
    }}
print(json.dumps(out))
"""
    completed = run_ssh(args, f"python3 - <<'PY'\n{remote_python}\nPY")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Remote sha256 probe returned no output.")
    return json.loads(lines[-1])


def remote_tree_sha256_map(args: argparse.Namespace, remote_root: str) -> dict[str, dict[str, str | int]]:
    remote_python = f"""
import hashlib, json
from pathlib import Path
root = Path({remote_root!r})
out = {{}}
if root.exists():
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        out[str(path.relative_to(root)).replace('\\\\', '/')] = {{
            "sha256": digest.hexdigest(),
            "size": path.stat().st_size,
        }}
print(json.dumps({{"exists": root.exists(), "files": out}}))
"""
    completed = run_ssh(args, f"python3 - <<'PY'\n{remote_python}\nPY")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Remote tree sha256 probe returned no output for {remote_root}.")
    return json.loads(lines[-1])


def remote_state_signature(remote_state: dict) -> dict:
    return {
        "latest_epoch": remote_state.get("latest_epoch"),
        "terminal_files": {
            str(entry["name"]): int(entry["size"])
            for entry in remote_state.get("terminal_files", [])
        },
        "epoch_files": {
            str(entry["name"]): int(entry["size"])
            for entry in remote_state.get("epoch_files", [])
        },
    }


def remote_path_inventory(args: argparse.Namespace, remote_paths: list[str]) -> dict[str, dict[str, object]]:
    payload = json.dumps(remote_paths)
    remote_python = f"""
import json
from pathlib import Path
paths = json.loads({payload!r})
out = {{}}
for raw in paths:
    path = Path(raw)
    out[raw] = {{
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "is_file": path.is_file(),
    }}
print(json.dumps(out))
"""
    completed = run_ssh(args, f"python3 - <<'PY'\n{remote_python}\nPY")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Remote path inventory probe returned no output.")
    return json.loads(lines[-1])


def sync_live_checkpoints(args: argparse.Namespace, local_live_cache: Path, state: dict, remote_state: dict) -> bool:
    changed = False
    synced_epochs = {int(value) for value in state.get("synced_epochs", [])}
    terminal_file_sizes = {
        str(key): int(value)
        for key, value in state.get("terminal_file_sizes", {}).items()
    }

    eligible_epochs = [
        entry
        for entry in remote_state.get("epoch_files", [])
        if int(entry["epoch"]) > 0 and int(entry["epoch"]) % args.epoch_step == 0
    ]
    for entry in eligible_epochs:
        epoch = int(entry["epoch"])
        if epoch in synced_epochs:
            continue
        remote_file = f"{args.remote_run_dir}/weights/{entry['name']}"
        local_file = local_live_cache / entry["name"]
        scp_pull(args, remote_file, local_file)
        synced_epochs.add(epoch)
        changed = True
        print(f"[watchdog] synced scheduled checkpoint {entry['name']} -> {local_file}", flush=True)

    for entry in remote_state.get("terminal_files", []):
        name = str(entry["name"])
        size = int(entry["size"])
        local_file = local_live_cache / name
        if terminal_file_sizes.get(name) == size and local_file.exists():
            continue
        remote_file = f"{args.remote_run_dir}/weights/{name}"
        scp_pull(args, remote_file, local_file)
        terminal_file_sizes[name] = size
        changed = True
        print(f"[watchdog] synced rolling {name} -> {local_file}", flush=True)

    if changed:
        state["synced_epochs"] = sorted(synced_epochs)
        state["terminal_file_sizes"] = terminal_file_sizes
        state["latest_epoch_seen"] = remote_state.get("latest_epoch")
    return changed


def scp_pull_tree(args: argparse.Namespace, remote_path: str, destination_root: Path) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    basename = Path(remote_path.rstrip("/")).name
    local_target = destination_root / basename
    if local_target.exists():
        if local_target.is_dir():
            shutil.rmtree(local_target)
        else:
            local_target.unlink()
    command = [
        "scp",
        "-r",
        "-o",
        f"ConnectTimeout={args.connect_timeout_seconds}",
        "-i",
        args.ssh_key,
        "-P",
        str(args.ssh_port),
        f"{remote_target(args)}:{remote_path}",
        str(destination_root),
    ]
    subprocess.run(command, check=True)
    return local_target


def final_snapshot_paths(args: argparse.Namespace) -> list[str]:
    return [
        args.remote_run_dir,
        f"{args.remote_project_root}/scripts",
        f"{args.remote_project_root}/configs",
        f"{args.remote_project_root}/train_from_guide_config.py",
        f"{args.remote_project_root}/guide_utils.py",
        f"{args.remote_project_root}/artifacts/logs",
        *args.extra_remote_path,
    ]


def verify_snapshot(args: argparse.Namespace, snapshot_root: Path, remote_state: dict) -> dict:
    run_name = Path(args.remote_run_dir).name
    local_run_dir = snapshot_root / run_name
    if not local_run_dir.exists():
        raise FileNotFoundError(f"Missing local run snapshot: {local_run_dir}")

    remote_paths = [
        f"{args.remote_run_dir}/args.yaml",
        f"{args.remote_run_dir}/results.csv",
        f"{args.remote_run_dir}/weights/best.pt",
        f"{args.remote_run_dir}/weights/last.pt",
    ]
    for entry in remote_state.get("epoch_files", []):
        epoch = int(entry["epoch"])
        if epoch > 0 and epoch % args.epoch_step == 0:
            remote_paths.append(f"{args.remote_run_dir}/weights/{entry['name']}")
    remote_hashes = remote_sha256_map(args, remote_paths)

    comparisons: list[dict] = []
    for remote_path in remote_paths:
        remote_info = remote_hashes[remote_path]
        if not remote_info.get("exists"):
            raise FileNotFoundError(f"Remote key file disappeared before verification: {remote_path}")
        local_path = local_run_dir / Path(remote_path).relative_to(args.remote_run_dir)
        if not local_path.exists():
            raise FileNotFoundError(f"Missing local copy for key file: {local_path}")
        local_hash = sha256_file(local_path)
        remote_hash = str(remote_info["sha256"])
        if local_hash != remote_hash:
            raise ValueError(f"Hash mismatch for {remote_path}: local={local_hash} remote={remote_hash}")
        comparisons.append(
            {
                "remote_path": remote_path,
                "local_path": str(local_path),
                "sha256": local_hash,
                "size": int(remote_info["size"]),
            }
        )
    verified_trees: list[dict] = []
    for remote_tree in [
        f"{args.remote_project_root}/scripts",
        f"{args.remote_project_root}/configs",
    ]:
        remote_tree_info = remote_tree_sha256_map(args, remote_tree)
        if not remote_tree_info.get("exists"):
            raise FileNotFoundError(f"Missing remote tree during verification: {remote_tree}")
        local_tree = snapshot_root / Path(remote_tree).name
        if not local_tree.exists():
            raise FileNotFoundError(f"Missing local tree snapshot: {local_tree}")
        remote_files = remote_tree_info.get("files", {})
        local_files = {
            str(path.relative_to(local_tree)).replace("\\", "/"): path
            for path in local_tree.rglob("*")
            if path.is_file()
        }
        if set(remote_files) != set(local_files):
            missing_local = sorted(set(remote_files) - set(local_files))
            extra_local = sorted(set(local_files) - set(remote_files))
            raise ValueError(
                f"Tree mismatch for {remote_tree}: missing_local={missing_local[:10]} extra_local={extra_local[:10]}"
            )
        file_count = 0
        for relative_path, remote_info in sorted(remote_files.items()):
            local_path = local_files[relative_path]
            local_hash = sha256_file(local_path)
            remote_hash = str(remote_info["sha256"])
            if local_hash != remote_hash:
                raise ValueError(
                    f"Tree hash mismatch for {remote_tree}/{relative_path}: local={local_hash} remote={remote_hash}"
                )
            file_count += 1
        verified_trees.append(
            {
                "remote_tree": remote_tree,
                "local_tree": str(local_tree),
                "file_count": file_count,
            }
        )
    return {
        "snapshot_root": str(snapshot_root),
        "run_name": run_name,
        "verified_files": comparisons,
        "verified_trees": verified_trees,
    }


def wait_for_quiesce(args: argparse.Namespace, baseline_signature: dict) -> dict:
    if args.quiesce_seconds > 0:
        print(f"[watchdog] stop condition met; waiting {args.quiesce_seconds:.0f}s for remote quiesce", flush=True)
        time.sleep(args.quiesce_seconds)
    remote_state = fetch_remote_state(args)
    session_alive = tmux_session_alive(args)
    signature = remote_state_signature(remote_state)
    if session_alive:
        raise RuntimeError("Training session came back during quiesce window. Refusing final snapshot/destroy.")
    if signature != baseline_signature:
        raise RuntimeError(
            "Remote run changed during quiesce window. Refusing destroy so the run cannot be truncated mid-write."
        )
    return remote_state


def assert_remote_unchanged_since_quiesce(args: argparse.Namespace, baseline_signature: dict) -> dict:
    remote_state = fetch_remote_state(args)
    session_alive = tmux_session_alive(args)
    signature = remote_state_signature(remote_state)
    if session_alive:
        raise RuntimeError("Training session is alive again after snapshot copy. Refusing destroy.")
    if signature != baseline_signature:
        raise RuntimeError("Remote run changed while the final snapshot was being copied. Refusing destroy.")
    return remote_state


def destroy_instance(args: argparse.Namespace) -> dict:
    if not args.arm_destroy:
        return {"status": "skipped", "reason": "dry_run"}
    if not args.instance_id:
        raise ValueError("--instance-id is required when --arm-destroy is set.")
    api_key = (args.api_key or "").strip()
    if not api_key:
        raise ValueError("Missing Vast API key. Pass --api-key or set VAST_API_KEY.")
    vast_probe = Path(args.vast_probe_script).resolve()
    if not vast_probe.exists():
        raise FileNotFoundError(f"Missing vast_probe.py: {vast_probe}")
    command = [
        "python",
        str(vast_probe),
        "--api-key",
        api_key,
        "destroy-instance",
        "--instance-id",
        str(args.instance_id),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = {}
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = {"stdout": completed.stdout}
    return {"status": "destroyed", "response": payload}


def main() -> None:
    args = parse_args()
    ensure_local_tools()
    local_export_root = Path(args.local_export_root).resolve()
    local_live_cache = Path(args.local_live_cache).resolve()
    local_live_cache.mkdir(parents=True, exist_ok=True)
    state_path = local_export_root / "watchdog_state.json"
    state = load_state(state_path)

    if args.preflight_only:
        remote_state = fetch_remote_state(args)
        session_alive = tmux_session_alive(args)
        snapshot_paths = final_snapshot_paths(args)
        inventory = remote_path_inventory(args, snapshot_paths)
        missing = [path for path, info in inventory.items() if not info.get("exists")]
        report = {
            "remote_run_dir": args.remote_run_dir,
            "train_session": args.train_session,
            "session_alive": session_alive,
            "remote_state": remote_state,
            "snapshot_paths": inventory,
            "destroy_armed": args.arm_destroy,
        }
        print(json.dumps(report, indent=2), flush=True)
        if missing:
            raise FileNotFoundError(f"Missing remote snapshot path(s): {missing}")
        return

    previous_epoch = state.get("latest_epoch_seen")
    stable_polls = 0
    last_progress_time = time.time()

    while True:
        remote_state = fetch_remote_state(args)
        latest_epoch = remote_state.get("latest_epoch")
        state_changed = sync_live_checkpoints(args, local_live_cache, state, remote_state)
        if state_changed:
            save_state(state_path, state)

        if latest_epoch is not None and latest_epoch != previous_epoch:
            previous_epoch = latest_epoch
            stable_polls = 0
            last_progress_time = time.time()
            state["latest_epoch_seen"] = latest_epoch
            save_state(state_path, state)
        else:
            stable_polls += 1

        session_alive = tmux_session_alive(args)
        terminal_names = {str(entry["name"]) for entry in remote_state.get("terminal_files", [])}
        has_terminal_files = {"best.pt", "last.pt"}.issubset(terminal_names)
        stopped = (not session_alive) and has_terminal_files and stable_polls >= args.stop_stable_polls
        if stopped:
            print(
                f"[watchdog] training appears finished: session_alive={session_alive}, "
                f"latest_epoch={latest_epoch}, stable_polls={stable_polls}",
                flush=True,
            )
            break

        if time.time() - last_progress_time >= args.idle_timeout_seconds:
            raise TimeoutError(
                f"No epoch progress observed for {args.idle_timeout_seconds} seconds. "
                "Refusing to destroy the instance automatically."
            )

        time.sleep(args.poll_seconds)

    quiesced_state = wait_for_quiesce(args, remote_state_signature(remote_state))
    sync_live_checkpoints(args, local_live_cache, state, quiesced_state)
    save_state(state_path, state)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"{Path(args.remote_run_dir).name}_snapshot_{stamp}"
    staging_root = local_export_root / f"{snapshot_name}.incomplete"
    snapshot_root = local_export_root / snapshot_name
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    copied_paths: list[dict] = []
    for remote_path in final_snapshot_paths(args):
        local_path = scp_pull_tree(args, remote_path, staging_root)
        copied_paths.append({"remote_path": remote_path, "local_path": str(local_path)})
        print(f"[watchdog] final snapshot copied {remote_path} -> {local_path}", flush=True)

    final_remote_state = assert_remote_unchanged_since_quiesce(args, remote_state_signature(quiesced_state))
    verification = verify_snapshot(args, staging_root, final_remote_state)
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    staging_root.replace(snapshot_root)
    copied_paths = [
        {
            "remote_path": entry["remote_path"],
            "local_path": str(snapshot_root / Path(entry["local_path"]).relative_to(staging_root)),
        }
        for entry in copied_paths
    ]
    destroy_result = destroy_instance(args)

    final_manifest = {
        "remote_run_dir": args.remote_run_dir,
        "remote_project_root": args.remote_project_root,
        "local_live_cache": str(local_live_cache),
        "snapshot_root": str(snapshot_root),
        "latest_epoch": final_remote_state.get("latest_epoch"),
        "copied_paths": copied_paths,
        "verification": verification,
        "destroy_result": destroy_result,
    }
    final_manifest_path = snapshot_root / "auto_snapshot_destroy_manifest.json"
    final_manifest_path.write_text(json.dumps(final_manifest, indent=2), encoding="utf-8")

    state["final_snapshot_complete"] = True
    state["destroyed"] = destroy_result.get("status") == "destroyed"
    state["final_manifest"] = str(final_manifest_path)
    save_state(state_path, state)

    print(json.dumps(final_manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
