from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any


VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}


def discover_media_bindings(repo_root: Path) -> list[dict[str, Any]]:
    media_dir = repo_root / "artifacts" / "media" / "latest"
    manifest_path = media_dir / "manifest.json"
    bindings: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    raw_entries = manifest.get("media") if isinstance(manifest, dict) else None
    if isinstance(raw_entries, list):
        for index, entry in enumerate(raw_entries):
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            source_path = (media_dir / path_value).resolve()
            if not source_path.exists():
                continue
            bindings.append(
                {
                    "id": entry.get("id") or f"media_{index}",
                    "label": entry.get("label") or source_path.stem,
                    "kind": entry.get("kind") or "video",
                    "mime_type": entry.get("mime_type") or _mime_type_for(source_path),
                    "source_path": str(source_path),
                    "showcase_rel_path": _showcase_rel_path(repo_root, source_path),
                    "web_path": _web_path(repo_root, source_path),
                }
            )
        if bindings:
            return bindings

    readme_bindings = _discover_from_readme(repo_root, media_dir)
    if readme_bindings:
        return readme_bindings

    for index, source_path in enumerate(sorted(media_dir.iterdir()) if media_dir.exists() else []):
        if not source_path.is_file() or source_path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        bindings.append(
            {
                "id": f"media_{index}",
                "label": source_path.stem,
                "kind": "video",
                "mime_type": _mime_type_for(source_path),
                "source_path": str(source_path.resolve()),
                "showcase_rel_path": _showcase_rel_path(repo_root, source_path.resolve()),
                "web_path": _web_path(repo_root, source_path.resolve()),
            }
        )
    return bindings


def _discover_from_readme(repo_root: Path, media_dir: Path) -> list[dict[str, Any]]:
    readme_path = media_dir / "README.md"
    if not readme_path.exists():
        return []

    contents = readme_path.read_text(encoding="utf-8")
    candidates = re.findall(r"([A-Za-z0-9_./ -]+\.(?:mp4|webm|mov))", contents, flags=re.IGNORECASE)
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        normalized_candidate = candidate.strip().strip("`").strip()
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        source_path = (media_dir / normalized_candidate).resolve()
        if not source_path.exists() or not source_path.is_file():
            continue
        bindings.append(
            {
                "id": f"media_{index}",
                "label": source_path.stem,
                "kind": "video",
                "mime_type": _mime_type_for(source_path),
                "source_path": str(source_path),
                "showcase_rel_path": _showcase_rel_path(repo_root, source_path),
                "web_path": _web_path(repo_root, source_path),
                "declared_in": "README.md",
            }
        )
    return bindings


def _showcase_rel_path(repo_root: Path, source_path: Path) -> str:
    showcase_dir = repo_root / "artifacts" / "showcase" / "latest"
    return Path(os.path.relpath(source_path.resolve(), showcase_dir.resolve())).as_posix()


def _web_path(repo_root: Path, source_path: Path) -> str:
    return "/artifacts/" + source_path.resolve().relative_to(repo_root / "artifacts").as_posix()


def _mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mov":
        return "video/quicktime"
    return "video/mp4"
