#!/usr/bin/env python3
"""Trigger a gateway scan (hot-apply of on-disk edits), for ignition_scan tool.

GATED by the write-allowlist (allow_scan). Protocol:
  1. Check open Designer sessions — warn loudly if any (unsaved-edit risk)
  2. Try to acquire the project scan lock (mutual exclusion with other scanners)
  3. POST /data/api/v1/scan/{scope}  →  poll GET until the scan completes
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from _allowlist import gate_scan, load_allowlist
from _ignition import api, api_expect, load_config
from _json_out import emit, emit_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("projects", "config"), default="projects")
    parser.add_argument("--wait", type=float, default=60.0, help="max seconds to poll for scan completion")
    parser.add_argument("--no-lock", action="store_true", help="skip the scan-lock acquire attempt")
    args = parser.parse_args()

    allow = load_allowlist()
    gate_scan(allow)
    cfg = load_config()

    out: dict[str, Any] = {"ok": True, "scope": args.scope}

    # Designer conflict warning
    status, designers, _ = api(cfg, "/data/api/v1/designers", timeout=10)
    open_projects: list[str] = []
    if status == 200 and isinstance(designers, list):
        for s in designers:
            if isinstance(s, dict):
                open_projects.append(str(s.get("projectName") or s.get("project") or s.get("id") or "unknown"))
    out["designer_sessions_open"] = open_projects
    if open_projects and args.scope == "projects":
        out["designer_warning"] = (
            f"Designer is OPEN on: {', '.join(open_projects)}. If there are unsaved edits, "
            "this scan may cause conflicts. Ask the operator to save/close first, or proceed only "
            "if the operator confirms."
        )

    # Scan lock (best-effort; gateway rejects if already held)
    if not args.no_lock and args.scope == "projects":
        status, lock, _ = api(cfg, "/data/api/v1/scan-lock/projects", method="POST", body={}, timeout=10)
        if status == 200:
            out["scan_lock_acquired"] = True
        elif status == 409:
            out["scan_lock_acquired"] = False
            out["scan_lock_note"] = "Lock held elsewhere — another scan in progress or Designer-locked."
        else:
            out["scan_lock_acquired"] = False
            out["scan_lock_note"] = f"Lock acquire returned HTTP {status} (continuing without lock)."

    # Trigger
    api_expect(cfg, f"/data/api/v1/scan/{args.scope}", method="POST", timeout=30, what="scan trigger")
    out["scan_triggered"] = True

    # Poll
    deadline = time.time() + args.wait
    final: dict[str, Any] = {}
    while time.time() < deadline:
        status, st, _ = api(cfg, f"/data/api/v1/scan/{args.scope}", timeout=10)
        if status == 200 and isinstance(st, dict):
            final = st
            if not st.get("scanActive", False):
                break
        time.sleep(1.0)
    out["scan_status"] = final or "poll timed out — check ignition_gateway_logs"
    out["completed"] = bool(final and not final.get("scanActive", False))
    out["next"] = (
        "Verify in the Designer / browser session, or ignition_screenshot for visual check. "
        "If the resource did not appear, check ignition_gateway_logs for scan errors."
    )
    emit(out)


if __name__ == "__main__":
    main()