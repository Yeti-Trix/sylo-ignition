#!/usr/bin/env python3
"""Shared write-allowlist loader / gates for sylo-ignition.

The allowlist lives at packages/sylo-ignition/assets/write-allowlist.json and is
OPERATOR-MANAGED — the agent must never edit it. Every mutating tool
(resource_write, scan, project_create, REST writes) enforces it in Python:
refuse anything not explicitly allowed here.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _json_out import emit_error


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def allowlist_path() -> Path:
    env = os.environ.get("IGNITION_WRITE_ALLOWLIST", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return package_root() / "assets" / "write-allowlist.json"


def default_allowlist() -> dict[str, Any]:
    return {
        "allow_writes": False,
        "allow_scan": False,
        "allow_project_create": False,
        "projects": [],
        "updated_at": None,
        "notes": "Operator-managed. The agent cannot edit this file; mutating tools enforce it.",
    }


def load_allowlist() -> dict[str, Any]:
    path = allowlist_path()
    if not path.is_file():
        return default_allowlist()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_allowlist()
    if not isinstance(data, dict):
        return default_allowlist()
    base = default_allowlist()
    base.update(data)
    if not isinstance(base.get("projects"), list):
        base["projects"] = []
    return base


def _project_entry(allow: dict[str, Any], project: str) -> dict[str, Any] | None:
    for entry in allow.get("projects", []):
        if isinstance(entry, dict) and entry.get("name") == project:
            return entry
    return None


def gate_writes(allow: dict[str, Any], project: str) -> None:
    """Exit with a clear error unless project file-writes are allowed."""
    if not allow.get("allow_writes"):
        emit_error(
            "File writes are disabled in the Ignition write-allowlist "
            f"({allowlist_path()}). The operator must set allow_writes=true."
        )
    entry = _project_entry(allow, project)
    if entry is None:
        emit_error(
            f"Project '{project}' is not in the Ignition write-allowlist. "
            "The operator must add it there (assets/write-allowlist.json) before any write. "
            "The agent must not edit that file."
        )
    if not entry.get("enabled", False):
        emit_error(
            f"Project '{project}' is present but DISABLED in the Ignition write-allowlist. "
            "Ask the operator to enable it (or use a different allowed project)."
        )


def gate_scan(allow: dict[str, Any]) -> None:
    if not allow.get("allow_scan"):
        emit_error(
            "Gateway scan is disabled in the Ignition write-allowlist "
            f"({allowlist_path()}). The operator must set allow_scan=true to hot-apply edits."
        )


def gate_project_create(allow: dict[str, Any], name: str) -> None:
    if not allow.get("allow_project_create"):
        emit_error(
            "Project creation is disabled in the Ignition write-allowlist. "
            "The operator must set allow_project_create=true."
        )
    if not name or any(c in name for c in '/\\:*?"<>|') or name.strip() != name:
        emit_error(f"Invalid project name: {name!r}")


def summary(allow: dict[str, Any]) -> dict[str, Any]:
    return {
        "allow_writes": bool(allow.get("allow_writes")),
        "allow_scan": bool(allow.get("allow_scan")),
        "allow_project_create": bool(allow.get("allow_project_create")),
        "writable_projects": [
            e.get("name") for e in allow.get("projects", []) if isinstance(e, dict) and e.get("enabled")
        ],
        "path": str(allowlist_path()),
    }


def note_update() -> dict[str, Any]:
    return {"updated_at": datetime.now(timezone.utc).isoformat()}