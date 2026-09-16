#!/usr/bin/env python3
"""sylo-ignition MCP server — Ignition 8.3 gateway + project assistant.

Harness-neutral replacement for the old pi TS extension: every tool is a thin
1:1 wrapper around the standalone Python scripts in ``scripts/`` (same CLI
args, same JSON-out contract, same allowlist enforcement). Any MCP client
(Claude Code, Codex, pi via pi-mcp-adapter, ...) gets identical behavior.

File-based workflow on a live 8.3 gateway: author/edit project resources on
disk (data/projects/**), trigger REST scans to hot-apply, screenshot
Perspective sessions for vision verification. Writes are gated by the
operator-managed write-allowlist (assets/write-allowlist.json) — enforced in
Python, never agent-editable.

Python resolution for the wrapped scripts (same precedence the TS extension
used): ``SYLO_PYTHON`` env var wins, else the interpreter running this server.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PACKAGE_ROOT / "scripts"

# Per-script timeouts in seconds (mirrors the old TS extension).
TIMEOUTS: dict[str, float] = {
    "screenshot.py": 120.0,
    "backup.py": 360.0,
    "scan.py": 120.0,
}
DEFAULT_TIMEOUT = 90.0

mcp = FastMCP("ignition")

DEBUG = os.environ.get("SYLO_IGNITION_MCP_DEBUG") == "1"
DEBUG_LOG = PACKAGE_ROOT / "server" / "_debug.log"


def _dbg(msg: str) -> None:
    if not DEBUG:
        return
    import datetime

    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().isoformat() + " " + msg + "\n")
    except Exception:
        pass


# Windows env floor: some MCP harnesses launch servers with a sanitized
# environment (missing SYSTEMROOT etc.), which makes child Python processes
# hang on imports (ssl/socket). Rebuild any missing critical vars.
_WIN_ENV_FLOOR = {
    "SYSTEMROOT": r"C:\Windows",
    "SYSTEMDRIVE": "C:",
    "COMSPEC": r"C:\Windows\system32\cmd.exe",
    "PATHEXT": ".COM;.EXE;.BAT;.CMD",
    "TEMP": os.path.expandvars(r"%LOCALAPPDATA%\Temp") if os.environ.get("LOCALAPPDATA") else r"C:\Windows\Temp",
    "TMP": r"C:\Windows\Temp",
}


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if os.name == "nt":
        for key, default in _WIN_ENV_FLOOR.items():
            env.setdefault(key, default)
    return env


class ToolError(Exception):
    """Raised when a wrapped script fails; surfaces as an MCP error result."""


def _script_python() -> str:
    env = os.environ.get("SYLO_PYTHON", "").strip()
    return env or sys.executable


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().split("\n")[-lines:]).strip()


def _parse_trailing_json(stdout: str) -> dict | None:
    trimmed = stdout.strip()
    if not trimmed:
        return None
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass
    idx = trimmed.rfind("\n{")
    while idx >= 0:
        candidate = trimmed[idx + 1:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            idx = trimmed.rfind("\n{", 0, idx)
    return None


def _run_script(script: str, args: list[str]) -> str:
    """Run scripts/<script> with the same env/cwd/timeout contract the TS
    extension used; return operator-facing text (JSON pretty or error)."""
    timeout = TIMEOUTS.get(script, DEFAULT_TIMEOUT)
    cmd = [_script_python(), str(SCRIPTS_DIR / script), *args]
    _dbg(f"run {script} args={args!r} python={_script_python()}")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        _dbg("launching subprocess")
        proc = subprocess.run(
            cmd,
            cwd=str(PACKAGE_ROOT),
            # stdin=DEVNULL is load-bearing on Windows: inheriting the MCP
            # stdio pipe makes the child's Py_Initialize lseek on that pipe
            # block forever (server.py hangs, child never starts).
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=_child_env(),
            creationflags=flags,
        )
        _dbg(f"returned rc={proc.returncode} outlen={len(proc.stdout or '')}")
    except subprocess.TimeoutExpired:
        _dbg(f"TIMEOUT {script} after {timeout}s")
        raise ToolError(f"{script} timed out after {int(timeout)}s")
    except OSError as exc:
        _dbg(f"OSERROR {exc}")
        raise ToolError(f"failed to launch {script}: {exc}")

    parsed = _parse_trailing_json(proc.stdout)
    if parsed is None:
        detail = _tail(proc.stdout) or proc.stderr.strip() or f"{script} produced no output"
        _dbg(f"no-json output, detail={detail[:120]!r}")
        raise ToolError(detail)
    if parsed.get("ok") is False:
        raise ToolError(str(parsed.get("error") or f"{script} failed"))
    operator_chat = parsed.get("operator_chat")
    if isinstance(operator_chat, str) and operator_chat.strip():
        return operator_chat.strip()
    return json.dumps(parsed, indent=2)


def _stage_content(content: str) -> list[str]:
    """Large content can exceed Windows argv limits — stage to a temp file."""
    if len(content) < 6000:
        return ["--content", content]
    fd, tmp = tempfile.mkstemp(prefix="sylo-ignition-content-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
    except BaseException:
        os.unlink(tmp)
        raise
    return ["--content-file", tmp]


@mcp.tool()
def ignition_status() -> str:
    """Gateway reachability + version, project list, open Designer sessions (write-conflict warning), config presence, allowlist summary. Run this FIRST in any Ignition task."""
    return _run_script("status.py", [])


@mcp.tool()
def ignition_project_resources(
    project: str | None = None,
    filter: str | None = None,
    files: bool | None = None,
) -> str:
    """List a project's resources on disk (views, scripts, themes, etc.) grouped by module scope, with payload types. Read any of them with ignition_resource_read."""
    args: list[str] = []
    if project and project.strip():
        args += ["--project", project.strip()]
    if filter and filter.strip():
        args += ["--filter", filter.strip()]
    if files is True:
        args.append("--files")
    return _run_script("project_resources.py", args)


@mcp.tool()
def ignition_resource_read(
    path: str,
    project: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Read a project resource file (view.json, .py, theme.css, resource.json, any text file) as pretty JSON or text. Binary files are refused."""
    p = (path or "").strip()
    if not p:
        raise ToolError("ignition_resource_read requires path.")
    args: list[str] = []
    if project and project.strip():
        args += ["--project", project.strip()]
    args += ["--path", p]
    if max_chars and max_chars > 0:
        args += ["--max-chars", str(int(max_chars))]
    return _run_script("resource_read.py", args)


@mcp.tool()
def ignition_resource_write(
    path: str,
    content: str,
    project: str | None = None,
) -> str:
    """GATED (write-allowlist): atomically write a project resource file. JSON must parse; forbidden targets (digest, .bin, thumbnails, .resources, gateway config) are refused. New resource folders get a scan-compatible resource.json scaffold. Follow with ignition_scan to hot-apply."""
    p = (path or "").strip()
    if not p:
        raise ToolError("ignition_resource_write requires path.")
    if not content:
        raise ToolError("ignition_resource_write requires non-empty content.")
    staged = _stage_content(content)
    args: list[str] = []
    if project and project.strip():
        args += ["--project", project.strip()]
    args += ["--path", p, *staged]
    try:
        return _run_script("resource_write.py", args)
    finally:
        if "--content-file" in staged:
            tmp = staged[staged.index("--content-file") + 1]
            try:
                os.unlink(tmp)
            except OSError:
                pass


@mcp.tool()
def ignition_validate(path: str, project: str | None = None) -> str:
    """Offline lint before writing/scanning: view.json structure + unique component names + binding shapes; Jython 2.7 compatibility for project scripts (f-strings are errors); resource.json key checks. Never touches the gateway."""
    p = (path or "").strip()
    if not p:
        raise ToolError("ignition_validate requires path.")
    args: list[str] = []
    if project and project.strip():
        args += ["--project", project.strip()]
    args += ["--path", p]
    return _run_script("validate.py", args)


@mcp.tool()
def ignition_scan(scope: str | None = None, wait_seconds: float | None = None) -> str:
    """GATED (allow_scan): trigger POST /data/api/v1/scan/{scope} to hot-apply on-disk edits into the gateway + open Designers. Warns when a Designer session is open. Polls until the scan completes. Scope=projects for view/tag/script edits; config for gateway config."""
    args: list[str] = []
    s = (scope or "projects").strip()
    if s:
        args += ["--scope", s]
    if wait_seconds and wait_seconds > 0:
        args += ["--wait", str(int(wait_seconds))]
    return _run_script("scan.py", args)


@mcp.tool()
def ignition_project_create(
    name: str,
    title: str | None = None,
    description: str | None = None,
) -> str:
    """GATED (allow_project_create): create a NEW empty project via REST (isolated, low-risk) and scan it onto disk. Use for scratch/demo projects — then enable it in the write-allowlist to write its resources."""
    n = (name or "").strip()
    if not n:
        raise ToolError("ignition_project_create requires name.")
    args = ["--name", n]
    if title and title.strip():
        args += ["--title", title.strip()]
    if description and description.strip():
        args += ["--description", description.strip()]
    return _run_script("project_create.py", args)


@mcp.tool()
def ignition_backup(out: str | None = None) -> str:
    """Download a full gateway backup (.gwbk) via REST to ~/.ignition-sylo/backups/. Run before risky/bulk changes as the rollback safety net (restore via gateway web UI)."""
    args = ["--out", out.strip()] if out and out.strip() else []
    return _run_script("backup.py", args)


@mcp.tool()
def ignition_screenshot(
    project: str | None = None,
    path: str | None = None,
    url: str | None = None,
    out: str | None = None,
    width: int | None = None,
    height: int | None = None,
    wait_ms: int | None = None,
) -> str:
    """Screenshot a Perspective session page (uses installed Chrome/Edge — no browser download). Save path is returned; view the PNG with your harness's own vision (Claude Code/Codex read images natively; on pi use analyze_image). Requires playwright (see scripts/requirements.txt)."""
    args: list[str] = []
    if project and project.strip():
        args += ["--project", project.strip()]
    if path and path.strip():
        args += ["--path", path.strip()]
    if url and url.strip():
        args += ["--url", url.strip()]
    if out and out.strip():
        args += ["--out", out.strip()]
    if width:
        args += ["--width", str(int(width))]
    if height:
        args += ["--height", str(int(height))]
    if wait_ms:
        args += ["--wait-ms", str(int(wait_ms))]
    return _run_script("screenshot.py", args)


@mcp.tool()
def ignition_gateway_logs(
    limit: int | None = None,
    min_level: str | None = None,
    search: str | None = None,
    logger: str | None = None,
) -> str:
    """Read gateway logs via REST (filters: level, search, logger). Use when a scan fails or a resource does not appear — scan/resource errors land here."""
    args: list[str] = []
    if limit and limit > 0:
        args += ["--limit", str(int(limit))]
    if min_level and min_level.strip():
        args += ["--min-level", min_level.strip()]
    if search and search.strip():
        args += ["--search", search.strip()]
    if logger and logger.strip():
        args += ["--logger", logger.strip()]
    return _run_script("gateway_logs.py", args)


@mcp.tool()
def ignition_api_get(route: str, save: str | None = None) -> str:
    """Read-only GET passthrough to the 588-route gateway REST API (resource lists, gateway info, tag export, Perspective sessions...). GET only — mutating verbs are refused. Use save for big payloads like /openapi.json."""
    r = (route or "").strip()
    if not r:
        raise ToolError("ignition_api_get requires route.")
    args = ["--route", r]
    if save and save.strip():
        args += ["--save", save.strip()]
    return _run_script("api_get.py", args)


if __name__ == "__main__":
    mcp.run()