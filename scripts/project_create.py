#!/usr/bin/env python3
"""Create a NEW Ignition project via REST, for ignition_project_create tool.

GATED by the write-allowlist (allow_project_create). Creating a project is
isolated (new empty folder) — the lowest-risk gateway write there is. After
creation the project appears on disk under data/projects/<name>/ after a scan.
"""

from __future__ import annotations

import argparse
from typing import Any

from _allowlist import gate_project_create, load_allowlist
from _ignition import api, load_config, project_dir
from _json_out import emit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--description", default="")
    args = parser.parse_args()

    allow = load_allowlist()
    gate_project_create(allow, args.name)
    cfg = load_config()

    body = {
        "name": args.name,
        "title": args.title or args.name,
        "description": args.description,
        "enabled": True,
        "inheritable": False,
        "parent": "",
    }
    status, resp, _ = api(cfg, "/data/api/v1/projects", method="POST", body=body, timeout=30)
    if status >= 400:
        hint = resp.get("message") if isinstance(resp, dict) else str(resp)[:200]
        emit({"ok": False, "error": f"Create project -> HTTP {status}: {hint}"})

    # Ask the gateway to scan so the folder lands on disk
    scan_status, _, _ = api(cfg, "/data/api/v1/scan/projects", method="POST", body={}, timeout=30)

    pdir = project_dir(cfg, args.name)
    out: dict[str, Any] = {
        "ok": True,
        "project": args.name,
        "created": True,
        "scan_triggered": scan_status == 200,
        "expected_dir": str(pdir),
        "dir_on_disk": pdir.is_dir(),
        "operator_chat": (
            f"Project '{args.name}' created{' and scanned' if scan_status == 200 else ''}. "
            "To let the agent write its resources, make sure it is enabled in the "
            "write-allowlist (assets/write-allowlist.json) — the agent must not edit that file."
        ),
    }
    emit(out)


if __name__ == "__main__":
    main()