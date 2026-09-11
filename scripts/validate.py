#!/usr/bin/env python3
"""Offline lint/validate of a project resource before scanning.

For ignition_validate tool. Heuristic (no vendor SDK):
  - view.json: structure, unique meta.name, known component types, binding shapes
  - resource.json: required keys
  - .py (project scripts): Jython 2.7 compatibility (f-strings etc. are errors)
  - tag JSON: light structure check
Errors block the write; warnings are advisory. This tool never calls the gateway.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _ignition import load_config, project_dir, resolve_project
from _json_out import emit, emit_error

KNOWN_VIEW_TYPES = {
    "ia.display.label",
    "ia.display.led",
    "ia.display.multistate-indicator",
    "ia.display.table",
    "ia.display.path",
    "ia.shapes.svg",
    "ia.input.btn",
    "ia.input.dropdown",
    "ia.input.numeric-entry",
    "ia.input.text-field",
    "ia.input.slider",
    "ia.input.toggle-switch",
    "ia.input.checkbox",
    "ia.container.flex",
    "ia.container.column",
    "ia.container.row",
    "ia.container.coord",
    "ia.container.tabs",
    "ia.container.accordian",
    "ia.container.dropdown-menu",
    "ia.container.menus",
    "ia.container.modal",
    "ia.container.popup",
    "ia.container.split",
    "ia.container.tab-container",
    "ia.container.template",
    "ia.chart.xy-chart",
    "ia.powerchart.powerchart",
    "ia.gauge.led-numeric-entry",
    "ia.gauge.linear-gauge",
    "ia.gauge.radial-gauge",
    "ia.gauge.arc",
    "ia.alarm.journal-table",
    "ia.alarm.status-table",
    "ia.logos.inductive-automation",
    "ia.display.image",
    "ia.display.markdown",
    "ia.embedded.websocket",
    "ia.embedded.video",
    "ia.barcode.qrcode",
    "ia.tagtags.tag-canvas",
    "em.charts.chartjs",
}
BINDING_TYPES = {"property", "tag", "expr", "query", "tagHistory", "propertyBinding", "exprBinding", "tagBinding"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--path", required=True)
    args = parser.parse_args()

    cfg = load_config(require_token=False)
    name = resolve_project(cfg, args.project)
    root = project_dir(cfg, name)
    target = (root / args.path.replace("\\", "/").strip("/")).resolve()
    if not target.is_file():
        emit_error(f"Not found: {args.path} (in {root})")

    errors: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []

    raw = target.read_text(encoding="utf-8", errors="replace")

    if target.name == "view.json":
        validate_view(raw, errors, warnings, checks)
    elif target.name == "resource.json":
        validate_resource_json(raw, errors, warnings, checks)
    elif target.suffix == ".py":
        validate_jython(raw, errors, warnings, checks)
    elif target.suffix == ".json":
        checks.append("generic JSON parse")
        try:
            json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"invalid JSON: {e}")
    else:
        checks.append("no validation rules for this file type — skipped")

    emit(
        {
            "ok": len(errors) == 0,
            "project": name,
            "path": args.path,
            "errors": errors,
            "warnings": warnings,
            "checks_run": checks,
        }
    )


# ---- view.json ----------------------------------------------------------------

def validate_view(raw: str, errors: list[str], warnings: list[str], checks: list[str]) -> None:
    checks.append("view.json: JSON parse")
    try:
        view = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        errors.append(f"view.json is not valid JSON: {e}")
        return
    if not isinstance(view, dict):
        errors.append("view.json root must be an object")
        return
    checks.append("view.json: root component (verified 8.3.9 shape)")

    # VERIFIED structure (live 8.3.9): top-level "root" is the root COMPONENT
    # (e.g. ia.container.coord) with children — NOT props.root.children.
    # A malformed view is silently dropped by the scan.
    root = view.get("root")
    if not isinstance(root, dict):
        errors.append(
            'view.json must have a top-level "root" component object '
            '(e.g. {"type": "ia.container.coord", "meta": {"name": "root"}, "children": [...]})'
        )
        return
    if root.get("type") not in ("ia.container.coord", "ia.container.flex", "ia.container.column", "ia.container.row"):
        errors.append(f'root.type should be a container type, got {root.get("type")!r}')
    if not isinstance(root.get("children"), list):
        warnings.append("root.children missing or not a list — empty view?")

    names: list[str] = []
    depth_violations: list[str] = []
    count = 0
    percent_mode_nodes: list[str] = []

    def walk(node: Any, path: str, depth: int) -> None:
        nonlocal count
        if not isinstance(node, dict):
            return
        count += 1
        ctype = node.get("type", "")
        if isinstance(ctype, str) and ctype and ctype not in KNOWN_VIEW_TYPES and not ctype.startswith("ia."):
            warnings.append(f"unknown component type {ctype!r} at {path}")
        meta = node.get("meta", {})
        nm = meta.get("name") if isinstance(meta, dict) else None
        if nm:
            if nm in names:
                errors.append(f"duplicate meta.name {nm!r} at {path} — names must be unique")
            names.append(nm)
        pos = node.get("position")
        if isinstance(pos, dict) and pos.get("mode") == "percent":
            percent_mode_nodes.append(path)
        if depth > 12:
            depth_violations.append(path)
        for child in node.get("children", []) or []:
            walk(child, f"{path}/{nm or ctype}", depth + 1)

    for child in root.get("children") or []:
        walk(child, "<root>", 1)
    checks.append(f"view.json: {count} components, {len(names)} named")

    if depth_violations:
        warnings.append(f"deep nesting (>12) at: {', '.join(depth_violations[:5])}")
    if count > 300:
        warnings.append(f"{count} components — very heavy view; consider templates/splitting")
    if percent_mode_nodes:
        warnings.append(
            "position.mode 'percent' observed but UNVERIFIED on 8.3.9 (labels stacked at 0,0 in "
            "live testing — use absolute px inside coord containers until verified)"
        )

    # Binding shape check: any {binding: {...}} must have a known type
    bind_re = re.compile(r'"binding"\s*:\s*\{')
    if bind_re.search(raw):
        checks.append("view.json: binding objects present — verifying types")
        bad = find_bad_bindings(view)
        for b in bad:
            errors.append(f"binding without a known 'type' at {b}")

    # Perspective expression binding syntax quick check
    for m in re.finditer(r"\{([^{}\n]{1,200})\}", raw):
        expr = m.group(1)
        if re.search(r"\bf\"|f'", expr):
            warnings.append(f"possible f-string in expression {expr[:60]!r} — Perspective expressions are not Python")


def find_bad_bindings(node: Any, path: str = "") -> list[str]:
    bad: list[str] = []
    if isinstance(node, dict):
        if set(node.keys()) == {"binding"} or "binding" in node:
            b = node.get("binding")
            if isinstance(b, dict) and b.get("type") not in BINDING_TYPES:
                bad.append(path or "<root>")
        for k, v in node.items():
            bad.extend(find_bad_bindings(v, f"{path}/{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad.extend(find_bad_bindings(v, f"{path}[{i}]"))
    return bad


# ---- resource.json ------------------------------------------------------------

def validate_resource_json(raw: str, errors: list[str], warnings: list[str], checks: list[str]) -> None:
    checks.append("resource.json: keys")
    try:
        meta = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        errors.append(f"resource.json is not valid JSON: {e}")
        return
    for key in ("scope", "version", "files"):
        if key not in meta:
            errors.append(f"resource.json missing key: {key}")
    if meta.get("scope") != "G":
        errors.append("resource.json scope must be 'G'")


# ---- Jython 2.7 ---------------------------------------------------------------

def validate_jython(raw: str, errors: list[str], warnings: list[str], checks: list[str]) -> None:
    checks.append("python: Jython 2.7 compatibility")
    for i, line in enumerate(raw.splitlines(), 1):
        if re.search(r"\bf['\"]", line):
            errors.append(f"line {i}: f-string — Jython 2.7 has no f-strings; use .format() or %")
        if re.search(r"\basync\s+def\b|\bawait\b", line):
            errors.append(f"line {i}: async/await — not available in Jython 2.7")
        if ":=" in line and not line.strip().startswith("#"):
            warnings.append(f"line {i}: walrus ':=' — not available in Jython 2.7")
        if re.match(r"\s*print\s+[^(\s]", line) and "#" not in line.split("print")[0]:
            warnings.append(f"line {i}: print statement without parens (works in 2.7, not Python 3)")
        if re.search(r"\bmatch\s+\w+.*:$", line.strip()) and "case" in raw:
            warnings.append(f"line {i}: 'match' statement — Jython 2.7 has no structural pattern matching")
    if re.search(r"^\s*import\s+(dataclasses|typing\.extensions|pathlib)\b", raw, re.M):
        warnings.append("import of a Python-3-only stdlib module (dataclasses/typing.extensions/pathlib) — unavailable in Jython 2.7")


if __name__ == "__main__":
    main()