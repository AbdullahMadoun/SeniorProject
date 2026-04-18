from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from remote_model_helpers import normalize_vast_instance, parse_csv_list, select_best_vast_offer


def _env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(0, len(value) - 8)}{value[-4:]}"


def _normalize_offer_type(value: str) -> str:
    lowered = str(value or "").strip().lower().replace("_", "").replace("-", "")
    if lowered in {"ondemand", "ondemand"}:
        return "ondemand"
    if lowered in {"bid", "interruptible"}:
        return "bid"
    return lowered or "ondemand"


def _run_command(command: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


class VastAiClient:
    def __init__(self, api_key: str, *, timeout: float = 60.0):
        self._client = httpx.Client(
            base_url="https://console.vast.ai/api/v0",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def show_user(self) -> dict[str, Any]:
        response = self._client.get("/users/current/")
        response.raise_for_status()
        return response.json()

    def show_instances(self) -> list[dict[str, Any]]:
        response = self._client.get("/instances/")
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("instances") or [])

    def show_instance(self, instance_id: int) -> dict[str, Any]:
        response = self._client.get(f"/instances/{instance_id}/")
        response.raise_for_status()
        payload = response.json()
        return dict(payload.get("instances") or {})

    def search_offers(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._client.post("/bundles/", json=filters)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return list(payload.get("offers") or payload.get("results") or payload.get("bundles") or payload.get("rows") or [])
        if isinstance(payload, list):
            return list(payload)
        return []

    def create_instance(self, offer_id: int, payload: dict[str, Any]) -> int:
        response = self._client.put(f"/asks/{offer_id}/", json=payload)
        response.raise_for_status()
        data = response.json()
        instance_id = data.get("new_contract")
        if not instance_id:
            raise RuntimeError(f"Vast.ai did not return a new instance id: {data}")
        return int(instance_id)

    def attach_ssh_key(self, instance_id: int, ssh_key: str) -> None:
        response = self._client.post(f"/instances/{instance_id}/ssh/", json={"ssh_key": ssh_key})
        response.raise_for_status()


@dataclass
class ManagedRemoteModelState:
    bundle_root: Path
    state_file: Path
    log_file: Path
    instance_file: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    output_tail: list[str] = field(default_factory=list)
    status: str = "disabled"
    error: str = ""
    provider: str = ""
    remote_host: str = ""
    remote_port: int = 22
    remote_user: str = "root"
    analyze_url: str = ""
    public_base_url: str = ""
    api_key: str = ""
    instance_id: int | None = None
    started_at: float | None = None
    last_attempt_at: float | None = None
    thread: threading.Thread | None = None
 
    def __post_init__(self) -> None:
        """Load last known state from disk immediately on instantiation."""
        if self.state_file.exists():
            try:
                import json
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                with self.lock:
                    self.status = data.get("status", "disabled")
                    self.error = data.get("error", "")
                    self.provider = data.get("provider", "ssh")
                    self.remote_host = data.get("remote_host", "")
                    self.remote_port = data.get("remote_port", 22)
                    self.analyze_url = data.get("analyze_url", "")
                    # Initialize masking from persisted masked key if available
                    self.api_key = data.get("api_key_masked", "")
                    self.instance_id = data.get("instance_id")
                    self.started_at = data.get("started_at")
                    self.output_tail = data.get("output_tail") or []
            except Exception:
                pass



    def _write_state(self) -> None:
        payload = {
            "status": self.status,
            "error": self.error,
            "provider": self.provider,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "remote_user": self.remote_user,
            "analyze_url": self.analyze_url,
            "public_base_url": self.public_base_url,
            "api_key_masked": _mask_secret(self.api_key),
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "last_attempt_at": self.last_attempt_at,
            "output_tail": self.output_tail[-25:],
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _append_output(self, line: str) -> None:
        clean = line.strip()
        if not clean:
            return
        timestamped = f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {clean}"
        with self.lock:
            self.output_tail.append(timestamped)
            if len(self.output_tail) > 120:
                self.output_tail = self.output_tail[-120:]
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(timestamped + "\n")
        self._write_state()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "error": self.error,
                "provider": self.provider,
                "remote_host": self.remote_host,
                "remote_port": self.remote_port,
                "remote_user": self.remote_user,
                "analyze_url": self.analyze_url,
                "public_base_url": self.public_base_url,
                "api_key_masked": _mask_secret(self.api_key),
                "instance_id": self.instance_id,
                "started_at": self.started_at,
                "output_tail": list(self.output_tail[-15:]),
            }

    def api_key_value(self) -> str:
        with self.lock:
            return self.api_key

    def start(self) -> None:
        enabled = _env_flag("SKYLINK_REMOTE_MODEL_AUTOSTART", False)
        if not enabled:
            with self.lock:
                self.status = "disabled"
                self.error = ""
                self.provider = str(os.getenv("SKYLINK_REMOTE_MODEL_PROVIDER", "ssh")).strip().lower()
                self.remote_host = ""
                self.remote_port = 22
                self.remote_user = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_USER", "root")).strip() or "root"
                self.analyze_url = ""
                self.public_base_url = ""
                self.api_key = ""
                self.instance_id = None
                self.started_at = None
                self.last_attempt_at = None
                self.output_tail = []
            self._write_state()
            return

        retry_seconds = int(os.getenv("SKYLINK_REMOTE_MODEL_RETRY_SECONDS", "60"))
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            if self.status == "ready" and self.analyze_url:
                return
            now = time.time()
            if self.last_attempt_at and (now - self.last_attempt_at) < retry_seconds and self.status == "failed":
                return
            self.status = "starting"
            self.error = ""
            self.provider = str(os.getenv("SKYLINK_REMOTE_MODEL_PROVIDER", "ssh")).strip().lower() or "ssh"
            self.started_at = self.started_at or now
            self.last_attempt_at = now
            self.output_tail = self.output_tail[-30:]
        self._write_state()
        self.thread = threading.Thread(target=self._worker, name="skylink-remote-model", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Signaling the worker to stop is handled via object destruction in this simplistic impl,
        but we provide the method to satisfy the server lifespan protocol."""
        with self.lock:
            if self.status == "starting":
                self.status = "disabled"
                self.error = "Bridge shutdown before completion."
            self._write_state()



    def _worker(self) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.instance_file.parent.mkdir(parents=True, exist_ok=True)
            self._append_output("Preparing managed remote model startup.")
            api_key = self._ensure_model_api_key()
            ssh_targets = self._resolve_ssh_target()
            self._sync_and_bootstrap_remote(api_key, ssh_targets)
            self._append_output("Managed remote model is ready.")
            with self.lock:
                self.status = "ready"
            self._write_state()
        except Exception as exc:
            with self.lock:
                self.status = "failed"
                self.error = str(exc)
            self._append_output(f"Startup failed: {exc}")
            self._write_state()

    def _ensure_model_api_key(self) -> str:
        key_path = self.bundle_root / "managed_model_api_key.txt"
        configured = str(os.getenv("SKYLINK_REMOTE_MODEL_API_KEY", "")).strip()
        if configured:
            key = configured
        elif key_path.exists():
            key = key_path.read_text(encoding="utf-8").strip()
        else:
            key = uuid.uuid4().hex
            key_path.write_text(key, encoding="utf-8")
        with self.lock:
            self.api_key = key
        return key

    def _load_public_ssh_key(self) -> str:
        inline_value = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_PUBLIC_KEY", "")).strip()
        if inline_value:
            return inline_value

        public_key_file = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_PUBLIC_KEY_FILE", "")).strip()
        if public_key_file and Path(public_key_file).exists():
            return Path(public_key_file).read_text(encoding="utf-8").strip()

        private_key_file = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KEY_FILE", "")).strip()
        if private_key_file:
            pub_candidate = Path(private_key_file + ".pub")
            if pub_candidate.exists():
                return pub_candidate.read_text(encoding="utf-8").strip()

        return ""

    def _resolve_ssh_target(self) -> list[tuple[str, int, str]]:
        provider = str(os.getenv("SKYLINK_REMOTE_MODEL_PROVIDER", "ssh")).strip().lower() or "ssh"
        user = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_USER", "root")).strip() or "root"

        if provider != "vastai":
            host = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_HOST", "")).strip()
            if not host:
                raise RuntimeError("SKYLINK_REMOTE_MODEL_SSH_HOST is required for SSH-managed startup.")
            port = int(os.getenv("SKYLINK_REMOTE_MODEL_SSH_PORT", "22"))
            with self.lock:
                self.provider = provider
                self.remote_host = host
                self.remote_port = port
                self.remote_user = user
            return [(host, port, user)]

        vast_api_key = str(os.getenv("SKYLINK_VAST_API_KEY", "")).strip()
        private_key_file = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KEY_FILE", "")).strip()
        if not vast_api_key:
            raise RuntimeError("SKYLINK_VAST_API_KEY is required for Vast.ai automation.")
        if not private_key_file:
            raise RuntimeError(
                "SKYLINK_REMOTE_MODEL_SSH_KEY_FILE is required before leasing a Vast.ai instance."
            )
        if not Path(private_key_file).exists():
            raise RuntimeError(f"SSH private key file not found: {private_key_file}")

        public_key = self._load_public_ssh_key()
        if not public_key:
            raise RuntimeError(
                "A matching public SSH key is required before leasing a Vast.ai instance. "
                "Set SKYLINK_REMOTE_MODEL_SSH_PUBLIC_KEY or SKYLINK_REMOTE_MODEL_SSH_PUBLIC_KEY_FILE."
            )

        client = VastAiClient(vast_api_key, timeout=float(os.getenv("SKYLINK_VAST_API_TIMEOUT", "60")))
        try:
            instance_id = self._reuse_or_create_vast_instance(client)
            client.attach_ssh_key(instance_id, public_key)
            instance = self._wait_for_vast_instance(client, instance_id)
        finally:
            client.close()

        normalized = normalize_vast_instance(instance)
        if not normalized["ready"]:
            raise RuntimeError(f"Vast.ai instance {instance_id} is not SSH-ready.")

        with self.lock:
            self.provider = "vastai"
            self.instance_id = int(instance_id)
            self.remote_host = normalized["ssh_host"]
            self.remote_port = int(normalized["ssh_port"])
            self.remote_user = user
        self.instance_file.write_text(str(instance_id), encoding="utf-8")
        self._append_output(
            f"Using Vast.ai instance {instance_id} at {normalized['ssh_host']}:{normalized['ssh_port']}."
        )
        candidates: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int]] = set()
        for host, port in [
            (normalized["ssh_host"], int(normalized["ssh_port"])),
            (normalized["public_ip"], int(normalized["ssh_port"])),
            (normalized["public_ip"], 22),
        ]:
            if not host or not port:
                continue
            key = (host, port)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((host, port, user))
        return candidates

    def _reuse_or_create_vast_instance(self, client: VastAiClient) -> int:
        deploy_mode = str(os.getenv("SKYLINK_REMOTE_MODEL_DEPLOY_MODE", "docker_vm")).strip().lower()
        configured_id = str(os.getenv("SKYLINK_VAST_INSTANCE_ID", "")).strip()
        if configured_id:
            self._append_output(f"Using configured Vast.ai instance id {configured_id}.")
            return int(configured_id)

        if self.instance_file.exists():
            persisted = self.instance_file.read_text(encoding="utf-8").strip()
            if persisted:
                try:
                    instance = client.show_instance(int(persisted))
                    if not instance or not instance.get("id"):
                        raise RuntimeError("stale-instance")
                    self._append_output(f"Reusing persisted Vast.ai instance id {persisted}.")
                    return int(persisted)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        self._append_output(f"Discarding stale Vast.ai instance id {persisted}.")
                        self.instance_file.unlink(missing_ok=True)
                    else:
                        raise
                except RuntimeError as exc:
                    if str(exc) == "stale-instance":
                        self._append_output(f"Discarding stale Vast.ai instance id {persisted}.")
                        self.instance_file.unlink(missing_ok=True)
                    else:
                        raise

        label = str(os.getenv("SKYLINK_VAST_INSTANCE_LABEL", "skylink-managed-model")).strip()
        for instance in client.show_instances():
            if str(instance.get("label") or "").strip() == label:
                normalized = normalize_vast_instance(instance)
                instance_id = int(instance.get("id"))
                self._append_output(f"Reusing existing Vast.ai instance {instance_id} with label {label}.")
                if normalized["ready"] or normalized["status"] in {"running", "loading", "starting"}:
                    return instance_id

        filters: dict[str, Any] = {
            "rentable": {"eq": True},
            "num_gpus": {"gte": int(os.getenv("SKYLINK_VAST_NUM_GPUS", "1"))},
            "reliability": {"gte": float(os.getenv("SKYLINK_VAST_MIN_RELIABILITY", "0.97"))},
            "limit": int(os.getenv("SKYLINK_VAST_SEARCH_LIMIT", "25")),
            "type": _normalize_offer_type(os.getenv("SKYLINK_VAST_OFFER_TYPE", "ondemand")),
        }
        if _env_flag("SKYLINK_VAST_REQUIRE_VERIFIED", True):
            filters["verified"] = {"eq": True}
        preferred_gpus = parse_csv_list(os.getenv("SKYLINK_VAST_PREFERRED_GPU_NAMES", "RTX 4090,L40S,A100,H100"))
        if preferred_gpus:
            filters["gpu_name"] = {"in": preferred_gpus}
        min_gpu_ram = float(os.getenv("SKYLINK_VAST_MIN_GPU_RAM_GB", "24"))
        if min_gpu_ram > 0:
            filters["gpu_total_ram"] = {"gte": int(min_gpu_ram * 1024)}
        if deploy_mode == "docker_vm":
            filters["vms_enabled"] = {"eq": True}

        self._append_output("Searching Vast.ai offers.")
        offers = client.search_offers(filters)
        offer = select_best_vast_offer(
            offers,
            preferred_gpu_names=preferred_gpus,
            max_total_hour=float(os.getenv("SKYLINK_VAST_MAX_HOURLY_USD", "1.5")),
            min_gpu_ram_gb=min_gpu_ram,
            min_reliability=float(os.getenv("SKYLINK_VAST_MIN_RELIABILITY", "0.97")),
            require_verified=_env_flag("SKYLINK_VAST_REQUIRE_VERIFIED", True),
            require_direct_ports=True,
        )
        if not offer:
            raise RuntimeError("No Vast.ai offer satisfied the configured GPU, reliability, and price constraints.")

        offer_id = int(offer["id"])
        self._append_output(
            f"Selected Vast.ai offer {offer_id} ({offer.get('gpu_name', 'unknown GPU')}, ${offer.get('dph_total', '?')}/h)."
        )
        if deploy_mode == "docker_vm":
            create_payload = {
                "image": str(os.getenv("SKYLINK_VAST_VM_IMAGE", "docker.io/vastai/kvm:ubuntu_terminal")).strip(),
                "label": label,
                "disk": int(os.getenv("SKYLINK_VAST_DISK_GB", "96")),
                "runtype": "ssh",
                "target_state": "running",
                "cancel_unavail": True,
                "vm": True,
            }
        else:
            create_payload = {
                "image": str(os.getenv("SKYLINK_VAST_IMAGE", "vastai/base-image:@vastai-automatic-tag")).strip(),
                "label": label,
                "disk": int(os.getenv("SKYLINK_VAST_DISK_GB", "64")),
                "runtype": str(os.getenv("SKYLINK_VAST_RUNTYPE", "ssh_direct")).strip(),
                "target_state": "running",
                "cancel_unavail": True,
            }
        instance_id = client.create_instance(offer_id, create_payload)
        self._append_output(f"Created Vast.ai instance {instance_id}.")
        self.instance_file.write_text(str(instance_id), encoding="utf-8")
        return instance_id

    def _wait_for_vast_instance(self, client: VastAiClient, instance_id: int) -> dict[str, Any]:
        timeout_seconds = int(os.getenv("SKYLINK_VAST_WAIT_READY_SECONDS", "900"))
        started = time.time()
        while (time.time() - started) < timeout_seconds:
            instance = client.show_instance(instance_id)
            normalized = normalize_vast_instance(instance)
            self._append_output(
                f"Vast.ai instance {instance_id} status: {normalized['status']} "
                f"{normalized['ssh_host']}:{normalized['ssh_port']}"
            )
            if normalized["ready"]:
                return instance
            time.sleep(10)
        raise RuntimeError(f"Timed out waiting for Vast.ai instance {instance_id} to become SSH-ready.")

    def _sync_and_bootstrap_remote(self, api_key: str, ssh_targets: list[tuple[str, int, str]]) -> None:
        remote_path = str(os.getenv("SKYLINK_REMOTE_MODEL_REMOTE_PATH", "/opt/skylink-model-server")).strip()
        ssh_command = shutil.which("ssh")
        scp_command = shutil.which("scp")
        if not ssh_command or not scp_command:
            raise RuntimeError("OpenSSH client tools (ssh/scp) are required for managed remote startup.")

        model_server_dir = self._resolve_existing_path("model_server")
        training_weights_dir = self._resolve_existing_path("training_pilot/weights")
        deploy_model_dir = self._resolve_existing_path("deploy/model_server")
        bootstrap_script = self._resolve_existing_path("deploy/model_server/bootstrap_remote.sh")
        external_yolo12_dir = self._resolve_existing_path("external/yolov12")
        if not model_server_dir:
            raise RuntimeError("model_server bundle is missing from the runtime image.")
        if not training_weights_dir:
            raise RuntimeError("training_pilot/weights is missing from the runtime image.")
        if not deploy_model_dir:
            raise RuntimeError("deploy/model_server is missing from the runtime image.")
        if not bootstrap_script:
            raise RuntimeError("deploy/model_server/bootstrap_remote.sh is missing from the runtime image.")

        selected_target = self._wait_for_any_ssh_access(ssh_command, ssh_targets)

        host, port, user = selected_target
        env_text = self._build_remote_env(api_key, host)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as handle:
            handle.write(env_text)
            temp_env_file = Path(handle.name)

        try:
            ssh_args = self._ssh_base_args(port)
            target = f"{user}@{host}"
            quoted_remote_path = shlex.quote(remote_path)
            quoted_training_path = shlex.quote(f"{remote_path}/training_pilot")
            quoted_external_path = shlex.quote(f"{remote_path}/external")
            self._append_output(f"Creating remote directory {remote_path}.")
            _run_command(
                [
                    ssh_command,
                    *ssh_args,
                    target,
                    f"mkdir -p {quoted_remote_path} {quoted_training_path} {quoted_external_path}",
                ],
                timeout=120,
            )

            self._append_output("Uploading model_server bundle.")
            _run_command([scp_command, *self._scp_base_args(port), "-r", str(model_server_dir), f"{target}:{remote_path}"], timeout=900)
            self._append_output("Uploading training weights bundle.")
            _run_command(
                [scp_command, *self._scp_base_args(port), "-r", str(training_weights_dir), f"{target}:{remote_path}/training_pilot"],
                timeout=1800,
            )
            if external_yolo12_dir:
                self._append_output("Uploading bundled YOLO12 fork.")
                _run_command(
                    [scp_command, *self._scp_base_args(port), "-r", str(external_yolo12_dir), f"{target}:{remote_path}/external"],
                    timeout=1800,
                )
            self._append_output("Uploading deploy/model_server assets.")
            _run_command(
                [scp_command, *self._scp_base_args(port), "-r", str(deploy_model_dir), f"{target}:{remote_path}/deploy"],
                timeout=900,
            )
            self._append_output("Uploading remote bootstrap script.")
            _run_command([scp_command, *self._scp_base_args(port), str(bootstrap_script), f"{target}:{remote_path}/bootstrap_remote.sh"], timeout=120)
            self._append_output("Uploading runtime environment.")
            _run_command([scp_command, *self._scp_base_args(port), str(temp_env_file), f"{target}:{remote_path}/.env"], timeout=120)

            remote_model_path = f"{remote_path}/model_server"
            remote_bootstrap_path = f"{remote_path}/bootstrap_remote.sh"
            remote_command = (
                f"chmod +x {shlex.quote(remote_bootstrap_path)} {shlex.quote(remote_model_path + '/run.sh')} && "
                f"ROOT_DIR={shlex.quote(remote_path)} {shlex.quote(remote_bootstrap_path)} bootstrap"
            )
            self._append_output("Running remote bootstrap.")
            completed = _run_command([ssh_command, *ssh_args, target, remote_command], timeout=int(os.getenv("SKYLINK_REMOTE_MODEL_BOOTSTRAP_TIMEOUT", "7200")))
            if completed.stdout.strip():
                self._append_output(completed.stdout.strip())

            status_command = f"ROOT_DIR={shlex.quote(remote_path)} {shlex.quote(remote_bootstrap_path)} status"
            self._append_output("Querying remote status.")
            status_result = _run_command([ssh_command, *ssh_args, target, status_command], timeout=120)
            payload = json.loads(status_result.stdout.strip())
            analyze_url = str(payload.get("analyze_url") or "").strip()
            public_base_url = str(payload.get("reachable_base_url") or payload.get("public_base_url") or "").strip()
            if not analyze_url:
                raise RuntimeError(f"Remote bootstrap succeeded but no analyze_url was returned: {payload}")

            with self.lock:
                self.analyze_url = analyze_url
                self.public_base_url = public_base_url
                self.remote_host = host
                self.remote_port = port
                self.remote_user = user
        finally:
            temp_env_file.unlink(missing_ok=True)

    def _wait_for_any_ssh_access(
        self,
        ssh_command: str,
        ssh_targets: list[tuple[str, int, str]],
    ) -> tuple[str, int, str]:
        timeout_seconds = int(os.getenv("SKYLINK_REMOTE_MODEL_SSH_READY_TIMEOUT", "300"))
        poll_seconds = int(os.getenv("SKYLINK_REMOTE_MODEL_SSH_READY_POLL_SECONDS", "5"))
        started = time.time()
        last_error = ""

        while (time.time() - started) < timeout_seconds:
            for host, port, user in ssh_targets:
                target = f"{user}@{host}"
                ssh_args = self._ssh_base_args(port)
                try:
                    self._append_output(f"Checking SSH access on {target}:{port}.")
                    result = _run_command(
                        [
                            ssh_command,
                            *ssh_args,
                            "-o",
                            "BatchMode=yes",
                            target,
                            "echo ssh-ready",
                        ],
                        timeout=30,
                    )
                    if "ssh-ready" in (result.stdout or ""):
                        self._append_output(f"SSH endpoint is accepting authenticated connections on {target}:{port}.")
                        return host, port, user
                except subprocess.CalledProcessError as exc:
                    last_error = (exc.stderr or exc.stdout or str(exc)).strip()
                    self._append_output(f"Waiting for SSH readiness on {target}:{port}: {last_error}")
                except Exception as exc:
                    last_error = str(exc)
                    self._append_output(f"Waiting for SSH readiness on {target}:{port}: {last_error}")
            time.sleep(poll_seconds)

        raise RuntimeError(f"Timed out waiting for SSH access. Last error: {last_error}")

    def _build_remote_env(self, api_key: str, ssh_host: str) -> str:
        remote_path = str(os.getenv("SKYLINK_REMOTE_MODEL_REMOTE_PATH", "/opt/skylink-model-server")).strip()
        model_dir = f"{remote_path}/model_server"
        enable_vlm = _env_flag("SKYLINK_REMOTE_MODEL_ENABLE_VLM", True)
        vlm_backend = os.getenv("SKYLINK_REMOTE_MODEL_VLM_BACKEND", "local").strip().lower()
        if vlm_backend not in {"local", "api", "disabled"}:
            vlm_backend = "local"
        install_local_vlm = enable_vlm and vlm_backend == "local"
        remote_deploy_mode = os.getenv("SKYLINK_REMOTE_MODEL_DEPLOY_MODE", "docker_vm").strip().lower() or "docker_vm"
        raw_enable_yolo_v8 = os.getenv("SKYLINK_REMOTE_MODEL_ENABLE_YOLO_V8")
        if raw_enable_yolo_v8 is None or not str(raw_enable_yolo_v8).strip():
            enable_yolo_v8 = enable_vlm
        else:
            enable_yolo_v8 = str(raw_enable_yolo_v8).strip().lower() in {"1", "true", "yes", "on"}
        values = {
            "API_KEY": api_key,
            "HOST": "0.0.0.0",
            "PORT": os.getenv("SKYLINK_REMOTE_MODEL_PORT", "17612"),
            "ENABLE_VLM": str(enable_vlm).lower(),
            "VLM_BACKEND": vlm_backend,
            "INSTALL_LOCAL_VLM": str(install_local_vlm).lower(),
            "ENABLE_YOLO_V8": str(enable_yolo_v8).lower(),
            "MODEL_NAME": os.getenv("SKYLINK_REMOTE_MODEL_VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"),
            "VLM_MODEL": os.getenv("SKYLINK_REMOTE_MODEL_VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"),
            "GPU_MEM_UTIL": os.getenv("SKYLINK_REMOTE_MODEL_GPU_MEM_UTIL", "0.80"),
            "MAX_MODEL_LEN": os.getenv("SKYLINK_REMOTE_MODEL_MAX_MODEL_LEN", "16384"),
            "MAX_OUTPUT_TOKENS": os.getenv("SKYLINK_REMOTE_MODEL_MAX_OUTPUT_TOKENS", "16384"),
            "DETECTOR_MODE": "ensemble",
            "ENSEMBLE_ENABLED": "true",
            "ENSEMBLE_MEMBERS": os.getenv(
                "SKYLINK_REMOTE_MODEL_ENSEMBLE_MEMBERS",
                "rezzzq_yolo12s_rdd2022,ozair_yolov8_rdd2022,oracl4_yolov8_rdd2022",
            ),
            "ENSEMBLE_MODE": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MODE", "msflip"),
            "ENSEMBLE_WEIGHT_MODE": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_WEIGHT_MODE", "equal"),
            "ENSEMBLE_WBF_IOU": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_WBF_IOU", "0.40"),
            "ENSEMBLE_WBF_SKIP": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_WBF_SKIP", "0.05"),
            "ENSEMBLE_FINAL_THRESHOLD": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_FINAL_THRESHOLD", "0.30"),
            "ENSEMBLE_MIN_SUPPORT": os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MIN_SUPPORT", "2"),
            "ENSEMBLE_MODEL_REZZZQ": str(
                os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MODEL_REZZZQ")
                or f"{remote_path}/training_pilot/weights/rdd_trained_local/yolo12s_rezzzq_v5align/best.pt"
            ).strip(),
            "ENSEMBLE_MODEL_OZAIR": str(
                os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MODEL_OZAIR")
                or f"{remote_path}/training_pilot/weights/rdd_trained_local/ozair_yolov8_custom/best.pt"
            ).strip(),
            "ENSEMBLE_MODEL_ORACL4": str(
                os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MODEL_ORACL4")
                or f"{remote_path}/training_pilot/weights/rdd_trained_local/oracl4_yolov8_custom/best.pt"
            ).strip(),
            "ENSEMBLE_MODEL_OBC": str(os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_MODEL_OBC", "")).strip(),
            "ENSEMBLE_CALIBRATION_MANIFEST": str(os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_CALIBRATION_MANIFEST", "")).strip(),
            "ENSEMBLE_SELECTION_SUMMARY": str(os.getenv("SKYLINK_REMOTE_MODEL_ENSEMBLE_SELECTION_SUMMARY", "")).strip(),
            "YOLO_MODEL_V8": str(os.getenv("SKYLINK_REMOTE_MODEL_YOLO_V8") or f"{model_dir}/models/YOLOv8_Small_RDD.pt").strip(),
            "YOLO_MODEL_V12": str(os.getenv("SKYLINK_REMOTE_MODEL_YOLO_V12") or "rezzzq/yolo12s-road-damage-rdd2022").strip(),
            "YOLO12_REPO_DIR": str(os.getenv("SKYLINK_REMOTE_MODEL_YOLO12_REPO_DIR") or f"{remote_path}/external/yolov12").strip(),
            "YOLO12_REPO_URL": str(
                os.getenv("SKYLINK_REMOTE_MODEL_YOLO12_REPO_URL")
                or "https://github.com/sunsmarterjie/yolov12.git"
            ).strip(),
            "YOLO12_REPO_REF": str(os.getenv("SKYLINK_REMOTE_MODEL_YOLO12_REPO_REF", "")).strip(),
            "YOLO_V8_WEIGHTS_URL": os.getenv(
                "SKYLINK_REMOTE_MODEL_YOLO_V8_WEIGHTS_URL",
                "https://huggingface.co/oracl4/YOLOv8_Small_RDD/resolve/main/YOLOv8_Small_RDD.pt",
            ),
            "VLM_API_URL": os.getenv("SKYLINK_REMOTE_MODEL_VLM_API_URL", ""),
            "VLM_API_KEY": os.getenv("SKYLINK_REMOTE_MODEL_VLM_API_KEY", ""),
            "VLM_API_AUTH_SCHEME": os.getenv("SKYLINK_REMOTE_MODEL_VLM_API_AUTH_SCHEME", "x-api-key"),
            "HF_HOME": str(os.getenv("SKYLINK_REMOTE_MODEL_HF_HOME") or f"{remote_path}/.cache/huggingface").strip(),
            "HUGGINGFACE_HUB_TOKEN": os.getenv("SKYLINK_REMOTE_MODEL_HF_TOKEN", ""),
            "PUBLIC_BASE_URL": os.getenv("SKYLINK_REMOTE_MODEL_PUBLIC_BASE_URL", ""),
            "PUBLIC_HOST": os.getenv("SKYLINK_REMOTE_MODEL_PUBLIC_HOST", ssh_host),
            "ENABLE_QUICK_TUNNEL": str(_env_flag("SKYLINK_REMOTE_MODEL_ENABLE_QUICK_TUNNEL", True)).lower(),
            "WAIT_FOR_HEALTH": str(_env_flag("SKYLINK_REMOTE_MODEL_WAIT_FOR_HEALTH", True)).lower(),
            "WAIT_FOR_TUNNEL": str(_env_flag("SKYLINK_REMOTE_MODEL_WAIT_FOR_TUNNEL", True)).lower(),
            "PREFETCH_MODELS": str(_env_flag("SKYLINK_REMOTE_MODEL_PREFETCH", True)).lower(),
            "REMOTE_DEPLOY_MODE": remote_deploy_mode,
        }
        return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"

    def _resolve_existing_path(self, relative_path: str) -> Path | None:
        candidates = [
            self.bundle_root / relative_path,
            self.bundle_root.parent / relative_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _ssh_base_args(self, port: int) -> list[str]:
        args = [
            "-p",
            str(port),
            "-o",
            f"StrictHostKeyChecking={os.getenv('SKYLINK_REMOTE_MODEL_SSH_STRICT_HOST_KEY_CHECKING', 'accept-new')}",
            "-o",
            f"ConnectTimeout={os.getenv('SKYLINK_REMOTE_MODEL_SSH_CONNECT_TIMEOUT', '15')}",
        ]
        key_file = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KEY_FILE", "")).strip()
        known_hosts = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KNOWN_HOSTS_FILE", "")).strip()
        if key_file:
            args.extend(["-i", self._prepared_ssh_private_key(key_file)])
        if known_hosts:
            args.extend(["-o", f"UserKnownHostsFile={known_hosts}"])
        return args

    def _scp_base_args(self, port: int) -> list[str]:
        args = ["-P", str(port)]
        key_file = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KEY_FILE", "")).strip()
        known_hosts = str(os.getenv("SKYLINK_REMOTE_MODEL_SSH_KNOWN_HOSTS_FILE", "")).strip()
        if key_file:
            args.extend(["-i", self._prepared_ssh_private_key(key_file)])
        args.extend(["-o", f"StrictHostKeyChecking={os.getenv('SKYLINK_REMOTE_MODEL_SSH_STRICT_HOST_KEY_CHECKING', 'accept-new')}"])
        if known_hosts:
            args.extend(["-o", f"UserKnownHostsFile={known_hosts}"])
        return args

    def _prepared_ssh_private_key(self, key_file: str) -> str:
        source = Path(key_file)
        if not source.exists():
            return key_file

        runtime_dir = self.bundle_root / "data" / "tmp" / "ssh"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        target = runtime_dir / source.name

        source_bytes = source.read_bytes()
        target_needs_write = True
        if target.exists():
            try:
                target_needs_write = target.read_bytes() != source_bytes
            except Exception:
                target_needs_write = True

        if target_needs_write:
            target.write_bytes(source_bytes)

        try:
            os.chmod(target, 0o600)
        except Exception:
            pass

        public_source = Path(key_file + ".pub")
        if public_source.exists():
            public_target = runtime_dir / public_source.name
            public_bytes = public_source.read_bytes()
            public_needs_write = True
            if public_target.exists():
                try:
                    public_needs_write = public_target.read_bytes() != public_bytes
                except Exception:
                    public_needs_write = True
            if public_needs_write:
                public_target.write_bytes(public_bytes)
            try:
                os.chmod(public_target, 0o644)
            except Exception:
                pass

        return str(target)
