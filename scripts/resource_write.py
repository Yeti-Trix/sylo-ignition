#!/usr/bin/env python3
"""Allowlist-gated atomic write of a project resource file.

For ignition_resource_write tool. Enforces:
  - operator-managed write-allowlist (project must be present + enabled)
  - forbidden paths (.resources, digest files, .bin, var/, local config, thumbnails)
  - JSON files must parse before writing (no corruption on disk)
  - atomic replace via temp file
  - new resource folders get a scaffold resource.json (scan-compatible)

resource.json of EXISTING resources is never written — the gateway owns it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _allowlist import gate_writes, load_allowlist
from _ignition import load_config, project_dir, resolve_project
from _json_out import emit, emit_error

FORBIDDEN_SUFFIXES = (".bin", ".idb", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gwbk")
FORBIDDEN_NAMES = {"thumbnail.png"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--path", required=True, help="file path relative to project root")
    parser.add_argument("--content", default=None, help="file content (string)")
    parser.add_argument("--content-file", default=None, help="read content from this file instead")
    args = parser.parse_args()

    if args.content is None and args.content_file is None:
        emit_error("Provide --content or --content-file.")
    content = args.content if args.content is not None else Path(args.content_file).read_text(encoding="utf-8")

    allow = load_allowlist()
    cfg = load_config(require_token=False)
    name = resolve_project(cfg, args.project)
    gate_writes(allow, name)

    root = project_dir(cfg, name)
    if not root.is_dir():
        emit_error(f"Project folder not found: {root} — create the project first (ignition_project_create).")

    target = safe_join(root, args.path)
    rel = target.relative_to(root).as_posix()

    # Forbidden targets
    parts = rel.split("/")
    if any(p == ".resources" for p in parts):
        emit_error(f"{rel}: .resources/ folders are gateway-internal — never write them.")
    if target.name.endswith(".digest.json"):
        emit_error(f"{rel}: digest files are gateway-managed — never write them.")
    if parts[0] in ("config", "var"):
        emit_error(f"{rel}: gateway config/var is out of scope for project writes.")
    if target.name in FORBIDDEN_NAMES or target.suffix.lower() in FORBIDDEN_SUFFIXES:
        emit_error(
            f"{rel}: binary/managed files (images, .bin, thumbnails) are produced by the "
            "gateway/Designer — write the text payload instead."
        )

    # JSON must parse (protects the gateway scan from bad files)
    if target.suffix == ".json":
        try:
            json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            emit_error(f"Refusing to write invalid JSON to {rel}: {e}")

    # resource.json policy: only scaffold NEW resource folders; never edit existing
    writing_resource_json = target.name == "resource.json"
    if writing_resource_json and target.exists():
        emit_error(
            f"{rel} already exists — the gateway owns resource.json (signatures/timestamps). "
            "Write the payload files instead; the scan updates attributes itself."
        )

    created_resource_json = False
    if writing_resource_json:
        created_resource_json = True

    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write
    existed = target.exists()
    tmp = target.with_suffix(target.suffix + ".sylo-tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(target)

    # Resource-folder bookkeeping
    scaffolded = False
    files_list_updated = False
    if not created_resource_json and target.parent != root:
        res_meta = target.parent / "resource.json"
        if not res_meta.exists():
            files = sorted({p.name for p in target.parent.iterdir() if p.name != "resource.json"})
            sig = hashlib.sha256(content.encode("utf-8")).hexdigest()
            meta = {
                "scope": "G",
                "version": 1,
                "restricted": False,
                "overridable": True,
                "files": files,
                "attributes": {
                    "lastModificationSignature": sig,
                    "lastModification": {
                        "actor": "Sylo",
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
            }
            tmp2 = res_meta.with_suffix(".json.sylo-tmp")
            tmp2.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
            tmp2.replace(res_meta)
            scaffolded = True
        else:
            # Existing resource folder: keep the files[] list in sync (attributes
            # stay gateway-owned — only the files array is touched).
            try:
                meta = json.loads(res_meta.read_text(encoding="utf-8"))
                files = meta.get("files")
                if isinstance(files, list) and target.name not in files:
                    files.append(target.name)
                    meta["files"] = sorted(files)
                    tmp2 = res_meta.with_suffix(".json.sylo-tmp")
                    tmp2.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
                    tmp2.replace(res_meta)
                    files_list_updated = True
            except (json.JSONDecodeError, OSError):
                pass  # malformed meta — the scan will flag it

    emit(
        {
            "ok": True,
            "project": name,
            "path": rel,
            "abs_path": str(target),
            "bytes": len(content.encode("utf-8")),
            "created": not existed,
            "resource_json_scaffolded": scaffolded,
            "resource_files_list_updated": files_list_updated,
            "next": (
                "Run ignition_validate (optional) then ignition_scan to hot-apply, "
                "then ignition_screenshot to verify."
            ),
        }
    )


def safe_join(root: Path, rel: str) -> Path:
    rel_clean = rel.replace("\\", "/").strip("/")
    if not rel_clean:
        emit_error("Empty path.")
    if any(part == ".." for part in rel_clean.split("/")) or ":" in rel_clean:
        emit_error(f"Illegal path: {rel!r}")
    target = (root / rel_clean).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        emit_error(f"Path escapes project root: {rel!r}")
    return target


if __name__ == "__main__":
    main()