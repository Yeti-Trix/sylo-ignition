#!/usr/bin/env python3
"""Read gateway logs via REST — for debugging scan failures / runtime errors.

For ignition_gateway_logs tool. GET /data/api/v1/logs with query filters.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from _ignition import api, load_config
from _json_out import emit, emit_error

MAX_CHARS = 30_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-level", default="", help="e.g. WARN, ERROR")
    parser.add_argument("--search", default="", help="substring search across log messages")
    parser.add_argument("--logger", default="", help="logger name filter")
    args = parser.parse_args()

    cfg = load_config()
    params = [f"limit={args.limit}"]
    if args.min_level:
        params.append(f"minLevel={args.min_level}")
    if args.search:
        params.append(f"search={args.search}")
    if args.logger:
        params.append(f"logger={args.logger}")
    route = "/data/api/v1/logs?" + "&".join(params)

    status, data, _ = api(cfg, route, timeout=20)
    if status >= 400:
        emit_error(f"GET {route} -> HTTP {status}: {str(data)[:200]}")

    text = json.dumps(data, indent=2) if not isinstance(data, str) else data
    truncated = False
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = True

    out: dict[str, Any] = {
        "ok": True,
        "route": route,
        "truncated": truncated,
        "logs": data if not truncated else text + "\n...[truncated]",
    }
    emit(out)


if __name__ == "__main__":
    main()