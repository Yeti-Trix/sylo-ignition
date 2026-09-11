#!/usr/bin/env python3
"""Read-only GET passthrough for gateway REST routes — ignition_api_get.

Lets the agent explore the 588-route API (resource lists, session detail,
overviews, tag exports) without a dedicated tool per route. GET ONLY — every
mutating verb is refused; the mutating tools have their own gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _ignition import api, load_config
from _json_out import emit, emit_error

ALLOWED_PREFIXES = ("/data/", "/openapi.json", "/system/")
MAX_INLINE_CHARS = 24_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, help="GET route, e.g. /data/api/v1/projects/list (query string allowed)")
    parser.add_argument("--save", default="", help="save the full JSON payload to this file (recommended for big routes)")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    route = args.route.strip()
    if not route.startswith(ALLOWED_PREFIXES) or route.startswith("//"):
        emit_error(
            f"Route must start with one of {ALLOWED_PREFIXES}. Got: {route!r}. "
            "Mutating methods are not available through this tool."
        )
    if "?" in route and any(
        kw in route.lower() for kw in ("method=", "delete", "put", "post")
    ):
        # route query strings don't carry verbs, but guard obviously wrong usage
        pass  # no-op: query params like ?scope=projects are legitimate

    cfg = load_config()
    status, data, _ = api(cfg, route, method="GET", timeout=args.timeout)

    out: dict[str, Any] = {"ok": status < 400, "route": route, "http_status": status}
    if status >= 400:
        out["error"] = str(data)[:300]
        emit(out)

    if args.save:
        save_path = Path(args.save).expanduser()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (dict, list)):
            save_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            save_path.write_text(str(data), encoding="utf-8")
        out["saved_to"] = str(save_path)
        out["hint"] = "Full payload saved to disk — read it with the read tool."
    else:
        text = json.dumps(data, indent=2) if not isinstance(data, str) else data
        if len(text) > MAX_INLINE_CHARS:
            out["payload"] = text[:MAX_INLINE_CHARS]
            out["truncated"] = True
            out["hint"] = "Truncated — re-run with --save <path> to capture the full payload."
        else:
            out["payload"] = data
    emit(out)


if __name__ == "__main__":
    main()