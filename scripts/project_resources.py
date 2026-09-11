#!/usr/bin/env python3
"""Resource tree listing for a project, for ignition_project_resources tool.

Walks data/projects/<project>/ and returns resource folders (dirs with
resource.json) plus notable files. Module scope is the first path segment
(e.g. com.inductiveautomation.perspective).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _ignition import load_config, project_dir, resolve_project
from _json_out import emit, emit_error

MAX_ENTRIES = 600


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--filter", default="", help="case-insensitive substring filter on path")
    parser.add_argument("--files", action="store_true", help="also list individual files")
    args = parser.parse_args()

    cfg = load_config(require_token=False)
    name = resolve_project(cfg, args.project)
    root = project_dir(cfg, name)
    if not root.is_dir():
        emit_error(
            f"Project folder not found on disk: {root}. If the project exists in the gateway "
            "but not on disk, it may need a scan (POST /data/api/v1/scan/projects) — or the "
            "data_dir in config is wrong."
        )

    flt = args.filter.strip().lower()
    resources: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in sorted_walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        if rel.count("/") == 0 and not rel:
            continue  # project root: project.json handled separately
        has_resource = "resource.json" in filenames
        is_resource_folder = has_resource
        if not is_resource_folder and not args.files:
            continue
        entry: dict[str, Any] = {"path": rel, "module": rel.split("/")[0]}
        if is_resource_folder:
            entry["kind"] = "resource"
            payload = detect_payload(filenames)
            entry["payload"] = payload
            entry["folder"] = dirpath
            resources.append(entry)
        else:
            entry["kind"] = "file"
            entry["files"] = sorted(filenames)
            files.append(entry)
        if len(resources) + len(files) >= MAX_ENTRIES:
            break

    def keep(e: dict[str, Any]) -> bool:
        return not flt or flt in e["path"].lower()

    resources = [e for e in resources if keep(e)]
    files = [e for e in files if keep(e)]
    by_module: dict[str, int] = {}
    for e in resources:
        by_module[e["module"]] = by_module.get(e["module"], 0) + 1

    emit(
        {
            "ok": True,
            "project": name,
            "root": str(root),
            "project_json": (root / "project.json").is_file(),
            "resource_count": len(resources),
            "by_module": by_module,
            "resources": [
                {"path": e["path"], "module": e["module"], "payload": e["payload"]} for e in resources
            ],
            "file_groups": [{"path": e["path"], "files": e["files"]} for e in files],
            "hint": (
                "Read any resource with ignition_resource_read using path=<resource folder path>. "
                "Perspective views live under com.inductiveautomation.perspective/views/."
            )
            if not args.files
            else "",
        }
    )


def sorted_walk(root: Path):
    """Deterministic walk: dirs sorted by name."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        dirnames, filenames = [], []
        for p in entries:
            if p.name in ("thumbnail.png",):
                continue
            if p.is_dir():
                dirnames.append(p.name)
                stack.append(p)
            else:
                filenames.append(p.name)
        yield str(d), dirnames, filenames


def detect_payload(filenames: list[str]) -> str:
    for f in ("view.json", "config.json", "props.json", "style_classes.json"):
        if f in filenames:
            return f
    if any(f.endswith(".py") for f in filenames):
        return ".py"
    if filenames:
        return filenames[0]
    return ""


if __name__ == "__main__":
    main()