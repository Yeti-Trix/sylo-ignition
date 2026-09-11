#!/usr/bin/env python3
"""Shared Ignition gateway plumbing: config file, REST client, data-dir paths.

Connection config lives OUTSIDE any repo at ~/.ignition-sylo/config.json so the
API token never lands in git:

    {
      "gateway_url": "http://localhost:8088",
      "api_token": "Sylo:...",
      "data_dir": "C:\\Program Files\\Inductive Automation\\Ignition\\data",
      "default_project": "SyloSandbox"
    }

Env overrides (testing): IGNITION_SYLO_CONFIG (path), IGNITION_SYLO_URL,
IGNITION_SYLO_TOKEN, IGNITION_SYLO_DATA_DIR, IGNITION_SYLO_PROJECT.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from _json_out import emit_error

CONFIG_FILENAME = "config.json"
COMMON_DATA_DIRS = (
    r"C:\Program Files\Inductive Automation\Ignition\data",
    r"C:\Program Files (x86)\Inductive Automation\Ignition\data",
)


def config_path() -> Path:
    env = os.environ.get("IGNITION_SYLO_CONFIG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".ignition-sylo" / CONFIG_FILENAME


def _first_existing_data_dir() -> str | None:
    for candidate in COMMON_DATA_DIRS:
        if Path(candidate).is_dir():
            return candidate
    return None


def load_config(require_token: bool = True) -> dict[str, Any]:
    """Load connection config; emit_error exits on missing pieces."""
    path = config_path()
    cfg: dict[str, Any] = {}
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            emit_error(f"Could not parse {path}: {e}")
    else:
        emit_error(
            f"No Ignition connection config at {path}. "
            "Create it (see skill: setup section) with gateway_url + api_token "
            "(Platform > Security > API Keys in the gateway web UI)."
        )
    # Env overrides
    cfg["gateway_url"] = os.environ.get("IGNITION_SYLO_URL", "").strip() or cfg.get("gateway_url", "")
    token = os.environ.get("IGNITION_SYLO_TOKEN", "").strip() or cfg.get("api_token", "").strip()
    cfg["api_token"] = token
    cfg["data_dir"] = (
        os.environ.get("IGNITION_SYLO_DATA_DIR", "").strip() or cfg.get("data_dir") or _first_existing_data_dir()
    )
    cfg["default_project"] = (
        os.environ.get("IGNITION_SYLO_PROJECT", "").strip() or cfg.get("default_project") or ""
    )
    cfg["_config_path"] = str(path)

    if not cfg.get("gateway_url"):
        emit_error(f"gateway_url missing in {path}")
    if require_token and not cfg.get("api_token"):
        emit_error(
            f"api_token missing in {path}. Create an API key (Platform > Security > API Keys), "
            "give it a custom security level granted Gateway Read+Write (see skill setup), "
            f"then put the token in {path}."
        )
    cfg["gateway_url"] = str(cfg["gateway_url"]).rstrip("/")
    return cfg


def projects_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg["data_dir"]) / "projects"


def project_dir(cfg: dict[str, Any], project: str) -> Path:
    return projects_dir(cfg) / project


def api(
    cfg: dict[str, Any],
    route: str,
    method: str = "GET",
    body: Any = None,
    timeout: float = 30.0,
    raw: bool = False,
) -> tuple[int, Any, dict[str, str]]:
    """Call the gateway REST API with the X-Ignition-API-Token header.

    Returns (status, parsed_json_or_text_or_bytes, headers). Auth/permission
    failures are returned as status codes — callers decide how to surface.
    """
    url = route if route.startswith("http") else cfg["gateway_url"] + route
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if cfg.get("api_token"):
        headers["X-Ignition-API-Token"] = cfg["api_token"]
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
            headers["Content-Type"] = "application/octet-stream"
        else:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    ctx = ssl.create_default_context()
    # Local gateways commonly run plain HTTP or self-signed HTTPS.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = resp.read()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        emit_error(f"Gateway unreachable at {url}: {e}")
    if raw:
        return status, payload, resp_headers
    text = payload.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text), resp_headers
    except (json.JSONDecodeError, ValueError):
        return status, text, resp_headers


def api_expect(
    cfg: dict[str, Any],
    route: str,
    method: str = "GET",
    body: Any = None,
    timeout: float = 30.0,
    what: str = "",
) -> Any:
    """api() that emit_errors on any non-2xx status."""
    status, parsed, _ = api(cfg, route, method=method, body=body, timeout=timeout)
    if status >= 400:
        if isinstance(parsed, dict):
            hint = parsed.get("message") or parsed.get("error") or json.dumps(parsed)[:200]
        else:
            hint = str(parsed)[:200]
        emit_error(f"{method} {route} -> HTTP {status}: {hint}" + (f" ({what})" if what else ""))
    return parsed


def mask_token(token: str) -> str:
    if not token:
        return ""
    return token[:6] + "..." if len(token) > 9 else "***"


def resolve_project(cfg: dict[str, Any], project: str | None) -> str:
    name = (project or "").strip() or cfg.get("default_project", "").strip()
    if not name:
        emit_error(
            "No project specified and no default_project in config. "
            "Pass --project or set default_project in ~/.ignition-sylo/config.json."
        )
    return name