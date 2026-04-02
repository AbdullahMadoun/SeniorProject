from __future__ import annotations

import os
from typing import Iterable

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore


def parse_cpu_cores(raw: str | Iterable[int] | int | None, *, default: Iterable[int] | None = None) -> list[int]:
    if raw is None:
        raw = [] if default is None else list(default)
    if isinstance(raw, int):
        values = [raw]
    elif isinstance(raw, str):
        values = [chunk.strip() for chunk in raw.split(",")]
    else:
        values = list(raw)

    normalized: list[int] = []
    for value in values:
        try:
            core_id = int(value)
        except (TypeError, ValueError):
            continue
        if core_id < 0 or core_id in normalized:
            continue
        normalized.append(core_id)
    return normalized


def enforce_cpu_affinity(
    core_ids: int | Iterable[int] | str | None,
    *,
    pid: int | None = None,
    label: str = "process",
) -> dict[str, object]:
    requested = parse_cpu_cores(core_ids)
    if not requested:
        return {
            "applied": False,
            "label": label,
            "pid": pid or os.getpid(),
            "requested": [],
            "reason": "no_valid_cores_requested",
        }

    if psutil is None:
        print(f"[AFFINITY] warning label={label} pid={pid or os.getpid()} reason=psutil_unavailable", flush=True)
        return {
            "applied": False,
            "label": label,
            "pid": pid or os.getpid(),
            "requested": requested,
            "reason": "psutil_unavailable",
        }

    cpu_count = os.cpu_count() or 0
    allowed = [core_id for core_id in requested if cpu_count <= 0 or core_id < cpu_count]
    if not allowed:
        print(
            f"[AFFINITY] warning label={label} pid={pid or os.getpid()} "
            f"reason=no_allowed_cores requested={requested} cpu_count={cpu_count}",
            flush=True,
        )
        return {
            "applied": False,
            "label": label,
            "pid": pid or os.getpid(),
            "requested": requested,
            "reason": "no_allowed_cores",
            "cpu_count": cpu_count,
        }

    try:
        process = psutil.Process(pid or os.getpid())
        if not hasattr(process, "cpu_affinity"):
            raise AttributeError("cpu_affinity is unavailable on this host")
        process.cpu_affinity(allowed)
        print(
            f"[AFFINITY] applied label={label} pid={process.pid} cores={','.join(str(core) for core in allowed)}",
            flush=True,
        )
        return {
            "applied": True,
            "label": label,
            "pid": process.pid,
            "requested": requested,
            "cores": allowed,
        }
    except Exception as exc:
        print(
            f"[AFFINITY] warning label={label} pid={pid or os.getpid()} "
            f"reason={type(exc).__name__} detail={exc}",
            flush=True,
        )
        return {
            "applied": False,
            "label": label,
            "pid": pid or os.getpid(),
            "requested": requested,
            "cores": allowed,
            "reason": type(exc).__name__,
            "detail": str(exc),
        }
