#!/usr/bin/env python3
"""Download a gateway backup (.gwbk) — the pre-change safety net.

For ignition_backup tool. Read-only (GET /data/api/v1/backup). Backups land in
~/.ignition-sylo/backups/ by default (outside any repo).
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from _ignition import api, load_config
from _json_out import emit, emit_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="output .gwbk file (default ~/.ignition-sylo/backups/<ts>.gwbk)")
    args = parser.parse_args()

    cfg = load_config()
    out_path = Path(args.out).expanduser() if args.out.strip() else (
        Path.home() / ".ignition-sylo" / "backups" / f"gateway-{datetime.now().strftime('%Y%m%d-%H%M%S')}.gwbk"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    status, payload, headers = api(cfg, "/data/api/v1/backup", method="GET", timeout=300, raw=True)
    if status >= 400:
        emit_error(f"Backup -> HTTP {status} ({payload[:200]!r})")
    if not payload or len(payload) < 10_000:
        emit_error(f"Backup response suspiciously small ({len(payload)} bytes) — not saved.")

    out_path.write_bytes(payload)
    emit(
        {
            "ok": True,
            "backup_path": str(out_path),
            "bytes": len(payload),
            "content_type": headers.get("content-type", ""),
            "note": "Restore via gateway web UI (Gateway > Restore) or POST /data/api/v1/backup. Keep this file until changes are verified.",
        }
    )


if __name__ == "__main__":
    main()