from __future__ import annotations

from typing import Any, Iterable


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _offer_total_hour(offer: dict[str, Any]) -> float:
    nested = offer.get("search") or offer.get("instance") or {}
    return _to_float(
        offer.get("dph_total_adj")
        or offer.get("dph_total")
        or nested.get("discountedTotalPerHour")
        or nested.get("totalHour"),
        10**9,
    )


def _offer_reliability(offer: dict[str, Any]) -> float:
    return _to_float(offer.get("reliability2") or offer.get("reliability"), 0.0)


def _offer_gpu_ram_gb(offer: dict[str, Any]) -> float:
    raw = offer.get("gpu_total_ram")
    if raw is None:
        raw = offer.get("gpu_totalram")
    if raw is None:
        raw = offer.get("gpu_ram")
    ram_mb = _to_float(raw, 0.0)
    return ram_mb / 1024.0 if ram_mb > 0 else 0.0


def _preference_index(gpu_name: str, preferred_gpu_names: Iterable[str]) -> int:
    lowered = gpu_name.strip().lower()
    for index, candidate in enumerate(preferred_gpu_names):
        if lowered == candidate.strip().lower():
            return index
    return len(list(preferred_gpu_names))


def select_best_vast_offer(
    offers: list[dict[str, Any]],
    *,
    preferred_gpu_names: Iterable[str] = (),
    max_total_hour: float | None = None,
    min_gpu_ram_gb: float = 0.0,
    min_reliability: float = 0.97,
    require_verified: bool = True,
    require_direct_ports: bool = True,
) -> dict[str, Any] | None:
    preferred = list(preferred_gpu_names)
    viable: list[dict[str, Any]] = []

    for offer in offers:
        if require_verified:
            verification = str(offer.get("verification") or "").strip().lower()
            verified_flag = bool(offer.get("verified"))
            if verification != "verified" and not verified_flag:
                continue
        if not bool(offer.get("rentable", True)):
            continue
        if bool(offer.get("rented", False)):
            continue
        if require_direct_ports and _to_int(offer.get("direct_port_count"), 0) <= 0:
            continue
        if _offer_reliability(offer) < min_reliability:
            continue
        if _offer_gpu_ram_gb(offer) < min_gpu_ram_gb:
            continue
        total_hour = _offer_total_hour(offer)
        if max_total_hour is not None and total_hour > max_total_hour:
            continue
        viable.append(offer)

    if not viable:
        return None

    def score(offer: dict[str, Any]) -> tuple[Any, ...]:
        return (
            _preference_index(str(offer.get("gpu_name") or ""), preferred),
            -_offer_reliability(offer),
            _offer_total_hour(offer),
            -_to_float(offer.get("dlperf"), 0.0),
            -_offer_gpu_ram_gb(offer),
        )

    return sorted(viable, key=score)[0]


def normalize_vast_instance(instance: dict[str, Any]) -> dict[str, Any]:
    actual_status = str(instance.get("actual_status") or instance.get("cur_state") or "").strip().lower()
    ssh_host = str(instance.get("ssh_host") or "").strip()
    ssh_port = _to_int(instance.get("ssh_port"), 22)
    public_ip = str(instance.get("public_ipaddr") or "").strip()

    return {
        "instance_id": instance.get("id"),
        "status": actual_status or "unknown",
        "ready": actual_status == "running" and bool(ssh_host),
        "ssh_host": ssh_host,
        "ssh_port": ssh_port,
        "public_ip": public_ip,
        "gpu_name": instance.get("gpu_name"),
        "gpu_ram_gb": _offer_gpu_ram_gb(instance),
    }


def resolve_frontend_connection(
    *,
    bridge_base_url: str,
    model_api_url: str,
    model_api_key: str,
    frontend_direct_model: bool,
    expose_model_key: bool,
    bridge_proxy_enabled: bool,
) -> dict[str, Any]:
    direct_enabled = bool(frontend_direct_model and model_api_url)
    analyze_via_bridge = bool(bridge_proxy_enabled and not direct_enabled and bridge_base_url)
    key_visible_to_frontend = bool(direct_enabled or expose_model_key)

    return {
        "BRIDGE_BASE_URL": bridge_base_url,
        "ANALYZE_VIA_BRIDGE": analyze_via_bridge,
        "DIRECT_MODEL_ENABLED": direct_enabled,
        "DEFAULT_MODEL_API_URL": model_api_url if direct_enabled else "",
        "DEFAULT_MODEL_API_KEY": model_api_key if key_visible_to_frontend else "",
        "MODEL_API_CONFIGURED": bool(model_api_url),
        "SERVER_SIDE_MODEL_KEY_CONFIGURED": bool(model_api_key),
    }
