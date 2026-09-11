#!/usr/bin/env python3
"""Screenshot a Perspective session with Playwright — ignition_screenshot.

Uses the installed Chrome or Edge via Playwright channels (no browser
download); falls back to bundled Chromium if present. Output PNG is saved to
~/.ignition-sylo/screenshots/ by default — read it back with the analyze_image
tool for vision critique (the design-quality loop).
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from _ignition import load_config
from _json_out import emit, emit_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--path", default="", help="view path segment appended to the client URL (optional)")
    parser.add_argument("--out", default="", help="output PNG path (default ~/.ignition-sylo/screenshots/...)")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--wait-ms", type=int, default=9000, help="render settle time before capture")
    parser.add_argument("--url", default="", help="full override URL (advanced)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        emit_error(
            "playwright is not installed. pip install playwright  "
            "(browsers not required — this tool uses installed Chrome/Edge). "
            "Then retry."
        )

    cfg = load_config(require_token=False)
    base = cfg["gateway_url"]
    project = (args.project or cfg.get("default_project") or "").strip()
    if not args.url and not project:
        emit_error("No --url and no project (pass --project or set default_project).")

    url = args.url or f"{base}/data/perspective/client/{project}"
    if args.path:
        url = url.rstrip("/") + "/" + args.path.strip("/")
    out_path = (
        Path(args.out).expanduser()
        if args.out.strip()
        else Path.home() / ".ignition-sylo" / "screenshots" / f"{project or 'session'}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = ""
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                # --no-proxy-server: headless verifier always targets the local
                # gateway; a system/env proxy would block 127.0.0.1/localhost
                # (observed live: Edge hung on goto until this arg was added).
                browser = p.chromium.launch(channel=channel, headless=True, args=["--no-proxy-server"]) if channel else p.chromium.launch(headless=True, args=["--no-proxy-server"])
                break
            except Exception as e:  # noqa: BLE001 — try next channel
                last_error = str(e)
        if browser is None:
            emit_error(f"Could not launch a browser: {last_error}")
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Perspective is a websocket SPA: give it time to mount views
        try:
            page.wait_for_load_state("networkidle", timeout=args.wait_ms)
        except Exception:  # noqa: BLE001 — settle-time exceeded, capture anyway
            pass
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out_path), full_page=False)
        browser.close()

    emit(
        {
            "ok": True,
            "url": url,
            "screenshot": str(out_path),
            "operator_chat": (
                f"Session screenshot saved: {out_path}. Read it with analyze_image to critique "
                "layout/spacing/hierarchy, then iterate (edit → scan → re-screenshot)."
            ),
        }
    )


if __name__ == "__main__":
    main()