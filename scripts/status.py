#!/usr/bin/env python3
"""Gateway + config + allowlist status for ignition_status tool."""

from __future__ import annotations

import time
from typing import Any

from _allowlist import load_allowlist, summary
from _ignition import api, load_config, mask_token, projects_dir
from _json_out import emit


def main() -> None:
    cfg = load_config(require_token=False)
    allow = load_allowlist()
    out: dict[str, Any] = {
        "ok": True,
        "config_path": cfg["_config_path"],
        "gateway_url": cfg["gateway_url"],
        "api_token_set": bool(cfg.get("api_token")),
        "api_token_hint": mask_token(cfg.get("api_token", "")),
        "data_dir": cfg.get("data_dir"),
        "default_project": cfg.get("default_project"),
        "data_dir_exists": bool(cfg.get("data_dir")) and projects_dir(cfg).parent.is_dir(),
        "allowlist": summary(allow),
    }

    # Gateway reachability + identity
    status, info, _ = api(cfg, "/data/api/v1/gateway-info", timeout=10)
    out["gateway_reachable"] = status == 200
    if status == 200 and isinstance(info, dict):
        out["gateway"] = {
            "version": info.get("ignitionVersion"),
            "edition": info.get("edition"),
            "deployment_mode": info.get("deploymentMode"),
            "hostname": info.get("hostname"),
            "jvm": info.get("jvmVersion"),
            "redundancy_role": info.get("redundancyRole"),
        }
        out["gateway"] = {k: v for k, v in out["gateway"].items() if v is not None}
    elif status in (401, 403):
        out["auth_problem"] = (
            f"gateway-info returned HTTP {status}. "
            + (
                "Token missing — create an API key and put it in config."
                if status == 401
                else "Token lacks permission — assign the key a custom security level granted "
                "Gateway Read+Write (Platform > Security > General Settings > Roles and Permissions)."
            )
        )

    # Projects
    status, projects, _ = api(cfg, "/data/api/v1/projects/list", timeout=10)
    if status == 200 and isinstance(projects, list):
        out["projects"] = [
            {
                "name": p.get("name"),
                "title": p.get("title"),
                "enabled": p.get("enabled"),
                "writable_by_agent": p.get("name") in (out["allowlist"]["writable_projects"] or []),
            }
            for p in projects
            if isinstance(p, dict)
        ]

    # Open Designer sessions (conflict warning for file writes / scans)
    designers: list[str] = []
    status, dsessions, _ = api(cfg, "/data/api/v1/designers", timeout=10)
    if status == 200 and isinstance(dsessions, list):
        for s in dsessions:
            if isinstance(s, dict):
                designers.append(str(s.get("projectName") or s.get("project") or s.get("id") or "unknown"))
    out["designer_sessions_open"] = designers
    if designers:
        out["operator_chat"] = (
            f"⚠️ Designer is open on: {', '.join(designers)}. Save or close those projects before "
            "scanning — a scan while the Designer has unsaved edits can conflict. Read-only work is fine."
        )
    else:
        out["operator_chat"] = (
            "Ignition gateway online — file-based 8.3 workflow ready. Typical flow: "
            "ignition_project_resources → ignition_resource_read → edit → ignition_resource_write → "
            "ignition_scan → ignition_screenshot to verify. Writes are gated by the allowlist: "
            f"writable projects = {out['allowlist']['writable_projects'] or 'none'}."
        )
    emit(out)


if __name__ == "__main__":
    main()