#!/usr/bin/env python3
"""Read a resource/file from a project, for ignition_resource_read tool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _ignition import load_config, project_dir, resolve_project
from _json_out import emit, emit_error

BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bin", ".idb", ".zip", ".ttf", ".woff", ".woff2"}
DEFAULT_MAX_CHARS = 40_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--path", required=True, help="path relative to project root")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()

    cfg = load_config(require_token=False)
    name = resolve_project(cfg, args.project)
    root = project_dir(cfg, name)
    target = safe_join(root, args.path)

    if not target.exists():
        emit_error(
            f"Not found: {args.path} (in {root}). List resources with ignition_project_resources. "
            "If you just created the folder, note the gateway may not have scanned it yet."
        )
    if target.is_dir():
        # Directory: show the folder's files (resource.json + payload)
        listing = sorted(p.name for p in target.iterdir())
        emit(
            {
                "ok": True,
                "project": name,
                "path": args.path,
                "type": "directory",
                "files": listing,
                "hint": "Read a specific file by appending it to the path.",
            }
        )
    if target.suffix.lower() in BINARY_EXTS:
        emit_error(
            f"{args.path} is binary ({target.suffix}) — not readable as text. "
            "For images use the gateway web UI; for .bin resources use the Designer."
        )

    raw = target.read_text(encoding="utf-8", errors="replace")
    data: Any = raw
    json_parsed = True
    if target.suffix == ".json":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            json_parsed = False
            data = raw

    truncated = False
    if isinstance(data, str) and len(data) > args.max_chars:
        data = data[: args.max_chars]
        truncated = True

    out: dict[str, Any] = {
        "ok": True,
        "project": name,
        "path": args.path,
        "abs_path": str(target),
        "size_bytes": target.stat().st_size,
        "truncated": truncated,
        "content": data,
    }
    if target.name == "resource.json" and json_parsed:
        out["hint"] = (
            "resource.json attributes are gateway-managed (signatures/timestamps). "
            "Never hand-edit an existing one — the scan regenerates them."
        )
    emit(out)


def safe_join(root: Path, rel: str) -> Path:
    """Join and refuse escapes (.., absolute, drive letters)."""
    rel_clean = rel.replace("\\", "/").strip("/")
    if not rel_clean:
        emit_error("Empty path.")
    if any(part in ("..",) for part in rel_clean.split("/")) or ":" in rel_clean:
        emit_error(f"Illegal path: {rel!r}")
    target = (root / rel_clean).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        emit_error(f"Path escapes project root: {rel!r}")
    return target


if __name__ == "__main__":
    main()