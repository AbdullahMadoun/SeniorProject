from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


API_BASE_URL = "https://console.vast.ai/api/v0"
DEFAULT_TIMEOUT_S = 30.0


class VastApiError(RuntimeError):
    """Raised when Vast.ai rejects or fails a request."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    current_key: str | None = None
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in line and not line[:1].isspace():
            key, value = line.split("=", 1)
            current_key = key.strip()
            values[current_key] = value.strip()
            continue
        if current_key is not None and line[:1].isspace():
            values[current_key] = f"{values[current_key]}{stripped}"
    return values


def load_api_key(explicit: str | None = None) -> str:
    if explicit:
        return "".join(explicit.split())

    for env_name in ("SKYLINK_VAST_API_KEY", "VAST_API_KEY", "VAST_API"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return "".join(value.split())

    repo_env = _load_env_file(_repo_root() / ".env")
    for env_name in ("SKYLINK_VAST_API_KEY", "VAST_API_KEY", "VAST_API"):
        value = repo_env.get(env_name, "").strip()
        if value:
            return "".join(value.split())

    raise SystemExit(
        "Missing Vast.ai API key. Set SKYLINK_VAST_API_KEY, VAST_API_KEY, or VAST_API, "
        "or store one of them in the repo .env file."
    )


def _json_request(
    method: str,
    path: str,
    *,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    errors: list[str] = []
    for auth_mode in ("bearer", "query"):
        try:
            return _json_request_once(
                method,
                path,
                api_key=api_key,
                body=body,
                timeout_s=timeout_s,
                auth_mode=auth_mode,
            )
        except VastApiError as exc:
            errors.append(str(exc))
    raise VastApiError(" | ".join(errors))


def _json_request_once(
    method: str,
    path: str,
    *,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    auth_mode: str,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    url = f"{API_BASE_URL}{path}"
    if auth_mode == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_mode == "query":
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode({'api_key': api_key})}"
    else:
        raise ValueError(f"Unsupported auth mode: {auth_mode}")
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        detail = error_body or exc.reason
        raise VastApiError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise VastApiError(f"{method} {path} failed: {exc.reason}") from exc

    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise VastApiError(f"{method} {path} returned invalid JSON: {payload[:200]}") from exc


def _coerce_instances(payload: dict[str, Any]) -> list[dict[str, Any]]:
    instances = payload.get("instances", [])
    if isinstance(instances, list):
        return [item for item in instances if isinstance(item, dict)]
    if isinstance(instances, dict):
        return [instances]
    return []


def _coerce_offers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    offers = payload.get("offers", [])
    if isinstance(offers, list):
        return [item for item in offers if isinstance(item, dict)]
    if isinstance(offers, dict):
        return [offers]
    return []


def _instance_summary(instance: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": instance.get("id"),
        "label": instance.get("label"),
        "actual_status": instance.get("actual_status"),
        "cur_state": instance.get("cur_state"),
        "intended_status": instance.get("intended_status"),
        "ssh_host": instance.get("ssh_host"),
        "ssh_port": instance.get("ssh_port"),
        "image_uuid": instance.get("image_uuid"),
        "template_name": instance.get("template_name"),
        "template_hash_id": instance.get("template_hash_id"),
        "vms_enabled": instance.get("vms_enabled"),
        "gpu_name": instance.get("gpu_name"),
        "num_gpus": instance.get("num_gpus"),
        "public_ipaddr": instance.get("public_ipaddr"),
        "dph_total": instance.get("dph_total"),
    }


def _offer_summary(offer: dict[str, Any]) -> dict[str, Any]:
    gpu_ram_mb = offer.get("gpu_ram")
    cpu_ram_mb = offer.get("cpu_ram")
    return {
        "id": offer.get("id"),
        "machine_id": offer.get("machine_id"),
        "gpu_name": offer.get("gpu_name"),
        "num_gpus": offer.get("num_gpus"),
        "gpu_ram_gb": round(float(gpu_ram_mb) / 1024.0, 1) if gpu_ram_mb is not None else None,
        "cpu_cores_effective": offer.get("cpu_cores_effective"),
        "cpu_ram_gb": round(float(cpu_ram_mb) / 1024.0, 1) if cpu_ram_mb is not None else None,
        "reliability": offer.get("reliability"),
        "verification": offer.get("verification"),
        "direct_port_count": offer.get("direct_port_count"),
        "vms_enabled": offer.get("vms_enabled"),
        "discounted_dph_total": offer.get("discounted_dph_total"),
        "dph_total": offer.get("dph_total"),
        "geolocation": offer.get("geolocation"),
        "public_ipaddr": offer.get("public_ipaddr"),
    }


def _instance_has_ssh(instance: dict[str, Any]) -> bool:
    return bool(instance.get("ssh_host")) and instance.get("ssh_port") is not None


def _instance_is_running(instance: dict[str, Any]) -> bool:
    return str(instance.get("actual_status", "")).lower() == "running" or str(
        instance.get("cur_state", "")
    ).lower() == "running"


def _parse_extra_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("Expected a JSON object.")
    return value


def _tail_text(raw: str, tail_lines: int) -> str:
    if tail_lines <= 0:
        return raw
    lines = raw.splitlines()
    if len(lines) <= tail_lines:
        return raw
    return "\n".join(lines[-tail_lines:])


def _normalize_runtype(raw: str | None) -> str | None:
    if raw != "ssh_direct":
        return raw
    print(
        "Deprecated runtype 'ssh_direct' requested; using 'ssh' with direct SSH enabled instead.",
        file=sys.stderr,
    )
    return "ssh"


def _build_offer_filters(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "limit": args.limit,
        "type": args.offer_type,
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "order": [["discounted_dph_total", "asc"]],
    }
    if args.verified:
        payload["verified"] = {"eq": True}
    if args.vm_capable:
        payload["vms_enabled"] = {"eq": True}
    if args.min_reliability is not None:
        payload["reliability"] = {"gte": args.min_reliability}
    if args.min_gpu_ram_gb is not None:
        payload["gpu_ram"] = {"gte": int(args.min_gpu_ram_gb * 1024)}
    if args.min_direct_ports is not None:
        payload["direct_port_count"] = {"gte": args.min_direct_ports}
    if args.allocated_storage_gb is not None:
        payload["allocated_storage"] = args.allocated_storage_gb
    if args.max_hourly_usd is not None:
        payload["dph_total"] = {"lte": args.max_hourly_usd}
    if args.gpu_name:
        payload["gpu_name"] = {"in": list(args.gpu_name)}
    if args.external:
        payload["external"] = {"eq": True}
    if args.datacenter:
        payload["datacenter"] = {"eq": True}
    return payload


def command_instances(args: argparse.Namespace) -> int:
    payload = _json_request("GET", "/instances/", api_key=args.api_key)
    instances = _coerce_instances(payload)
    if args.raw:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps([_instance_summary(item) for item in instances], indent=2))
    return 0


def command_show_instance(args: argparse.Namespace) -> int:
    payload = _json_request("GET", f"/instances/{args.instance_id}/", api_key=args.api_key)
    instance = _coerce_instances(payload)
    if not instance:
        raise SystemExit(f"Instance {args.instance_id} was not returned by Vast.ai.")
    print(json.dumps(instance[0] if args.raw else _instance_summary(instance[0]), indent=2))
    return 0


def command_wait_instance(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout_seconds
    last_summary: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = _json_request("GET", f"/instances/{args.instance_id}/", api_key=args.api_key)
        instance_list = _coerce_instances(payload)
        if not instance_list:
            raise SystemExit(f"Instance {args.instance_id} was not returned by Vast.ai.")
        instance = instance_list[0]
        last_summary = _instance_summary(instance)
        if _instance_is_running(instance) and (not args.require_ssh or _instance_has_ssh(instance)):
            print(json.dumps(last_summary, indent=2))
            return 0
        time.sleep(args.poll_interval_seconds)

    if last_summary is not None:
        print(json.dumps(last_summary, indent=2))
    raise SystemExit(
        f"Timed out after {args.timeout_seconds} seconds waiting for instance {args.instance_id}."
    )


def command_attach_ssh_key(args: argparse.Namespace) -> int:
    ssh_key = Path(args.public_key_file).read_text(encoding="utf-8").strip()
    payload = _json_request(
        "POST",
        f"/instances/{args.instance_id}/ssh/",
        api_key=args.api_key,
        body={"ssh_key": ssh_key},
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_request_logs(args: argparse.Namespace) -> int:
    payload = _json_request(
        "PUT",
        f"/instances/request_logs/{args.instance_id}/",
        api_key=args.api_key,
        timeout_s=args.timeout_seconds,
    )
    if args.raw:
        print(json.dumps(payload, indent=2))
        return 0

    log_url = payload.get("temp_download_url") or payload.get("result_url")
    if not isinstance(log_url, str) or not log_url:
        raise SystemExit(f"Instance {args.instance_id} did not return a downloadable log URL.")
    request = urllib.request.Request(log_url, headers={"Accept": "text/plain"})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
            raw_log = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        detail = error_body or exc.reason
        raise VastApiError(f"GET log download failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise VastApiError(f"GET log download failed: {exc.reason}") from exc

    print(_tail_text(raw_log, args.tail_lines))
    return 0


def command_offers(args: argparse.Namespace) -> int:
    payload = _json_request(
        "POST",
        "/bundles/",
        api_key=args.api_key,
        body=_build_offer_filters(args),
    )
    offers = _coerce_offers(payload)
    if args.raw:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps([_offer_summary(item) for item in offers], indent=2))
    return 0


def command_create_template(args: argparse.Namespace) -> int:
    onstart = args.onstart
    if args.onstart_file:
        onstart = Path(args.onstart_file).read_text(encoding="utf-8")
    runtype = _normalize_runtype(args.runtype)
    payload: dict[str, Any] = {
        "name": args.name,
        "image": args.image,
        "tag": args.tag,
        "runtype": runtype,
        "recommended_disk_space": args.recommended_disk_space,
    }
    if runtype == "ssh":
        payload["ssh_direct"] = True
        payload["use_ssh"] = True
    if args.env:
        payload["env"] = args.env
    if onstart:
        payload["onstart"] = onstart
    if args.desc:
        payload["desc"] = args.desc
    extra_filters = _parse_extra_json(args.extra_filter_json)
    if extra_filters:
        payload["extra_filters"] = extra_filters

    response = _json_request("POST", "/template/", api_key=args.api_key, body=payload)
    print(json.dumps(response, indent=2))
    return 0


def command_create_instance(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "template_hash_id": args.template_hash_id,
        "disk": args.disk_gb,
        "target_state": "running",
        "cancel_unavail": True,
    }
    if args.label:
        payload["label"] = args.label
    runtype = _normalize_runtype(args.runtype)
    if runtype:
        payload["runtype"] = runtype
    if args.vm:
        payload["vm"] = True
    if args.env:
        payload["env"] = args.env
    response = _json_request(
        "PUT",
        f"/asks/{args.offer_id}/",
        api_key=args.api_key,
        body=payload,
    )
    print(json.dumps(response, indent=2))
    return 0


def command_destroy_instance(args: argparse.Namespace) -> int:
    response = _json_request(
        "DELETE",
        f"/instances/{args.instance_id}/",
        api_key=args.api_key,
    )
    print(json.dumps(response, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Vast.ai helper for Skylink2 simulation workflows.")
    parser.add_argument("--api-key", help="Override the Vast.ai API key.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    instances_parser = subparsers.add_parser("instances", help="List live Vast.ai instances.")
    instances_parser.add_argument("--raw", action="store_true", help="Print the raw API response.")
    instances_parser.set_defaults(func=command_instances)

    show_parser = subparsers.add_parser("show-instance", help="Show one Vast.ai instance.")
    show_parser.add_argument("--instance-id", type=int, required=True)
    show_parser.add_argument("--raw", action="store_true", help="Print the raw API response.")
    show_parser.set_defaults(func=command_show_instance)

    wait_parser = subparsers.add_parser("wait-instance", help="Poll until an instance is running.")
    wait_parser.add_argument("--instance-id", type=int, required=True)
    wait_parser.add_argument("--timeout-seconds", type=int, default=900)
    wait_parser.add_argument("--poll-interval-seconds", type=int, default=5)
    wait_parser.add_argument("--require-ssh", action="store_true")
    wait_parser.set_defaults(func=command_wait_instance)

    attach_parser = subparsers.add_parser("attach-ssh-key", help="Attach an SSH public key to an instance.")
    attach_parser.add_argument("--instance-id", type=int, required=True)
    attach_parser.add_argument("--public-key-file", required=True)
    attach_parser.set_defaults(func=command_attach_ssh_key)

    request_logs_parser = subparsers.add_parser(
        "request-logs",
        help="Fetch the instance boot/runtime log and print a bounded tail.",
    )
    request_logs_parser.add_argument("--instance-id", type=int, required=True)
    request_logs_parser.add_argument("--tail-lines", type=int, default=120)
    request_logs_parser.add_argument("--timeout-seconds", type=float, default=120.0)
    request_logs_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print only the raw log-request API response metadata.",
    )
    request_logs_parser.set_defaults(func=command_request_logs)

    offers_parser = subparsers.add_parser("offers", help="Search Vast.ai offers.")
    offers_parser.add_argument("--offer-type", choices=("ondemand", "bid", "reserved"), default="ondemand")
    offers_parser.add_argument("--verified", action="store_true")
    offers_parser.add_argument("--vm-capable", action="store_true")
    offers_parser.add_argument("--min-reliability", type=float)
    offers_parser.add_argument("--min-gpu-ram-gb", type=float)
    offers_parser.add_argument("--min-direct-ports", type=int)
    offers_parser.add_argument("--allocated-storage-gb", type=int)
    offers_parser.add_argument("--max-hourly-usd", type=float)
    offers_parser.add_argument("--gpu-name", action="append")
    offers_parser.add_argument("--external", action="store_true")
    offers_parser.add_argument("--datacenter", action="store_true")
    offers_parser.add_argument("--limit", type=int, default=20)
    offers_parser.add_argument("--raw", action="store_true", help="Print the raw API response.")
    offers_parser.set_defaults(func=command_offers)

    template_parser = subparsers.add_parser("create-template", help="Create a Vast.ai template.")
    template_parser.add_argument("--name", required=True)
    template_parser.add_argument("--image", required=True)
    template_parser.add_argument("--tag", default="latest")
    template_parser.add_argument("--runtype", choices=("ssh", "jupyter", "args"), default="ssh")
    template_parser.add_argument("--recommended-disk-space", type=int, default=64)
    template_parser.add_argument("--env", help="Docker-style env/port flags, e.g. '-p 8000:8000'.")
    template_parser.add_argument("--onstart", help="On-start command.")
    template_parser.add_argument("--onstart-file", help="Read the on-start command from a local file.")
    template_parser.add_argument("--desc", help="Template description.")
    template_parser.add_argument("--extra-filter-json", help="Extra template filter JSON.")
    template_parser.set_defaults(func=command_create_template)

    create_instance_parser = subparsers.add_parser("create-instance", help="Create a Vast.ai instance.")
    create_instance_parser.add_argument("--offer-id", type=int, required=True)
    create_instance_parser.add_argument("--template-hash-id", required=True)
    create_instance_parser.add_argument("--disk-gb", type=int, default=64)
    create_instance_parser.add_argument("--label")
    create_instance_parser.add_argument("--runtype")
    create_instance_parser.add_argument("--vm", action="store_true")
    create_instance_parser.add_argument("--env", help="Docker-style env/port flags.")
    create_instance_parser.set_defaults(func=command_create_instance)

    destroy_instance_parser = subparsers.add_parser("destroy-instance", help="Destroy a Vast.ai instance.")
    destroy_instance_parser.add_argument("--instance-id", type=int, required=True)
    destroy_instance_parser.set_defaults(func=command_destroy_instance)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.api_key = load_api_key(args.api_key)
    try:
        return int(args.func(args))
    except VastApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
