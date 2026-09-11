#!/usr/bin/env python3
"""Fetch Ignition documentation locally for the sylo-ignition package.

Downloads the Ignition 8.3 User Manual (docs.inductiveautomation.com) and the
Ignition SDK Programmer's Guide (sdk-docs.inductiveautomation.com) — both
Docusaurus static sites — and converts every page to offline Markdown.

Also downloads the official 8.1 PDF manual bundle (legacy-docs exports) so the
8.1 fallback path has offline coverage.

Usage:
    python fetch_docs.py                # full run (download + convert + pdfs)
    python fetch_docs.py --no-download  # convert from existing html cache
    python fetch_docs.py --no-pdfs
    python fetch_docs.py --refresh      # re-download even if cache exists

Requires: pandoc 3.x on PATH. Python 3.10+ (stdlib only).

Output layout (relative to packages/sylo-ignition/):
    references/user-manual-8.3/<page-path>.md
    references/sdk-docs/<page-path>.md
    references/user-manual-8.1-pdfs/*.pdf
    references/README.md is maintained by hand (provenance/index).

Scratch cache: ~/igscrape/html/{user,sdk}/...
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import posixpath
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

USER_SITE = "https://www.docs.inductiveautomation.com"
SDK_SITE = "https://www.sdk-docs.inductiveautomation.com"
USER_SITEMAP = USER_SITE + "/sitemap.xml"
SDK_SITEMAP = SDK_SITE + "/sitemap.xml"

# Official 8.1 PDF exports (legacy-docs page, taken 2024-02-21).
PDF_81 = [
    "DOC-81-1-welcome-intro-other-editions",
    "DOC-81-2-0-vision",
    "DOC-81-2-1-perspective",
    "DOC-81-2-2-opc-ua-and-drivers",
    "DOC-81-2-3-tag-historian-and-sql-bridge",
    "DOC-81-2-4-reporting",
    "DOC-81-2-5-alarm-notification",
    "DOC-81-2-6-enterprise-administration",
    "DOC-81-2-7-sequential-function-charts",
    "DOC-81-2-8-secsgem",
    "DOC-81-2-9-symbol-factory-webdev-mongodb-connector",
    "DOC-81-3-platform",
    "DOC-81-4-scripting-functions",
    "DOC-81-5-expression-functions",
    "DOC-81-6-1-vision-components",
    "DOC-81-6-2-perspective-components",
    "DOC-81-6-3-reporting-components",
]
PDF_81_BASE = "https://d1v6u62vatllb2.cloudfront.net/81/"

PKG_ROOT = Path(__file__).resolve().parent.parent
REFS = PKG_ROOT / "references"
SCRATCH = Path.home() / "igscrape"
HTML_CACHE = SCRATCH / "html"

UA = {"User-Agent": "Mozilla/5.0 (sylo-ignition doc fetcher)"}


def http_get(url: str, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"failed {url}: {last}")


def sitemap_urls(sitemap_url: str, keep_prefixes: tuple[str, ...]) -> list[str]:
    xml = http_get(sitemap_url).decode("utf-8", errors="replace")
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    return [u for u in urls if any(u.startswith(p) for p in keep_prefixes)]


def local_rel(site_url: str, url: str, version_prefix: str) -> str:
    """Map a docs URL to a local path under the manual root (no version dir)."""
    rel = url[len(site_url):]
    rel = rel[len(version_prefix):] if rel.startswith(version_prefix) else rel
    rel = rel.strip("/")
    return (rel + "/index.md") if rel == "" or url.endswith("/") else rel + ".md"


def download_all(jobs: list[tuple[str, Path]], workers: int = 8) -> tuple[int, int]:
    ok, fail = 0, 0

    def one(job):
        url, dest = job
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            return True
        try:
            data = http_get(url)
        except Exception:
            return False
        dest.write_bytes(data)
        return len(data) > 200

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, jobs):
            ok += 1 if r else 0
            fail += 0 if r else 1
    return ok, fail


# ---------------------------------------------------------------- conversion

PANDOC = ["pandoc", "-f", "html", "-t", "gfm", "--wrap=none"]


def pandoc(fragment: str, fmt: str = "gfm") -> str:
    args = ["pandoc", "-f", "html", "-t", fmt, "--wrap=none"]
    p = subprocess.run(args, input=fragment.encode(), capture_output=True)
    return p.stdout.decode("utf-8", errors="replace")


def html_to_md(html: str, source_url: str) -> str | None:
    """Extract the Docusaurus markdown container and convert to Markdown."""
    k = html.find("theme-doc-markdown")
    if k < 0:
        return None
    i = html.find(">", k) + 1          # start AFTER the container's opening tag
    j = html.rfind("</article>")
    if i <= 0 or j < 0:
        return None
    frag = html[i:j]  # container closes naturally inside the article

    # Destructive simplifications so pandoc emits clean Markdown:
    frag = re.sub(r"<colgroup>.*?</colgroup>", "", frag, flags=re.S)  # widths -> pipe tables
    frag = re.sub(r'<nav class="pagination-nav.*?</nav>', "", frag, flags=re.S)
    frag = re.sub(r"<footer.*?</footer>", "", frag, flags=re.S)
    # <details>/<summary> -> bold heading (avoids raw-HTML blocks)
    frag = re.sub(r"</?(details|summary)( [^>]*)?>", "", frag)
    # Trim the trailing "Edit this page" metadata row.
    frag = re.sub(r'<div class="row margin-top--sm theme-doc-footer-edit-meta-row">.*', "", frag, flags=re.S)

    # Flatten div/span/header/section wrappers — gfm cannot represent them
    # anyway; stripping the tags keeps their content as clean flow.
    frag = re.sub(r"</?div[^>]*>", "", frag)
    frag = re.sub(r"</?span[^>]*>", "", frag)
    frag = re.sub(r"</?header[^>]*>", "", frag)
    frag = re.sub(r"</?section[^>]*>", "", frag)

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    title = m.group(1).split("|")[0].strip() if m else ""

    md = pandoc(frag)

    # De-duplicate the in-content H1 (we already emit `# {title}`).
    first = md.split("\n", 1)[0].strip()
    if first == f"# {title}":
        md = md.split("\n", 1)[1].lstrip("\n") if "\n" in md else ""
    # Hybrid table pass: tables that GFM could not express stay as raw <table>
    # HTML blocks; re-run those through pandoc's markdown (grid tables).
    def gridify(match: re.Match) -> str:
        return pandoc(match.group(0), "markdown").strip() or match.group(0)

    md = re.sub(r"<table>.*?</table>", gridify, md, flags=re.S)

    # Post-conversion cleanup: drop heading hash-links and empty card anchors.
    md = re.sub(r'<a href="#[^"]*" class="hash-link"[^>]*>.*?</a>', "", md)
    md = re.sub(r'<a href="/docs/8\.3/[^"]*" class="card[^"]*"[^>]*>\s*</a>', "", md)

    # Absolute-ize image URLs (images are not mirrored; keep them resolvable).
    site = USER_SITE if "docs.inductiveautomation.com" in source_url else SDK_SITE
    md = re.sub(r'\((/img/[^)]+)\)', lambda m2: f"({site}{m2.group(1)})", md)

    header = f"# {title}\n\n> Source: {source_url}\n\n"
    return header + md.strip() + "\n"


def rewrite_links(md: str, cur_rel: str, rels: set[str], version_prefix: str, site: str) -> str:
    """Rewrite internal docs links to relative .md paths when the target is mirrored."""
    link_re = re.compile(r"\]\((/docs/8\.3/[^)#\s]+?)(/?(#[^)\s]*)?)\)")

    def repl(m: re.Match) -> str:
        path, _slash, anchor = m.group(1), m.group(2), m.group(3) or ""
        rel = local_rel(site, site + path, version_prefix)
        if rel not in rels:
            return m.group(0)  # not mirrored — leave the absolute link
        here = posixpath.dirname(cur_rel)
        target = posixpath.relpath(rel, here) if here else rel
        return f"]({target}{anchor})"

    return link_re.sub(repl, md)


def convert_site(site: str, sitemap_url: str, version_prefix: str, cache: Path, out_root: Path, download: bool = True) -> dict:
    urls = sitemap_urls(sitemap_url, (site + version_prefix,))
    # Drop auto-generated category index pages and version pickers.
    urls = [u for u in urls if "/category/" not in u and u.rstrip("/") != site + "/versions"]
    jobs = [(u, cache / (local_rel(site, u, version_prefix).removesuffix(".md") + ".html")) for u in urls]
    if download:
        print(f"[{site}] {len(jobs)} pages to download")
        ok, fail = download_all(jobs)
        print(f"[{site}] downloaded ok={ok} fail={fail}")
    else:
        jobs = [(u, p) for u, p in jobs if p.exists()]
        print(f"[{site}] converting {len(jobs)} cached pages")

    stats = {"pages": 0, "skipped": 0, "bytes": 0}
    rels = {local_rel(site, u, version_prefix) for u in urls}
    for url, html_path in jobs:
        if not html_path.exists():
            stats["skipped"] += 1
            continue
        html = html_path.read_text(encoding="utf-8", errors="replace")
        md = html_to_md(html, url)
        if md is None:
            stats["skipped"] += 1
            continue
        rel = local_rel(site, url, version_prefix)
        md = rewrite_links(md, rel, rels, version_prefix, site)
        dest = out_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        stats["pages"] += 1
        stats["bytes"] += len(md)
    print(f"[{site}] converted {stats['pages']} pages, {stats['bytes']/1e6:.1f} MB md, skipped {stats['skipped']}")
    return stats


def fetch_pdfs() -> None:
    out = REFS / "user-manual-8.1-pdfs"
    out.mkdir(parents=True, exist_ok=True)
    for name in PDF_81:
        dest = out / f"{name}.pdf"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = PDF_81_BASE + name + ".pdf"
        try:
            dest.write_bytes(http_get(url))
            print(f"[pdf] {name}.pdf ({dest.stat().st_size/1e6:.1f} MB)")
        except Exception as exc:  # noqa: BLE001
            print(f"[pdf] FAILED {name}: {exc}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-pdfs", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    if args.refresh and HTML_CACHE.exists():
        for p in HTML_CACHE.rglob("*.html"):
            p.unlink()

    if args.no_download:
        convert_site(USER_SITE, USER_SITEMAP, "/docs/8.3/", HTML_CACHE / "user", REFS / "user-manual-8.3", download=False)
        convert_site(SDK_SITE, SDK_SITEMAP, "/docs/8.3/", HTML_CACHE / "sdk", REFS / "sdk-docs", download=False)
    else:
        convert_site(USER_SITE, USER_SITEMAP, "/docs/8.3/", HTML_CACHE / "user", REFS / "user-manual-8.3")
        convert_site(SDK_SITE, SDK_SITEMAP, "/docs/8.3/", HTML_CACHE / "sdk", REFS / "sdk-docs")
    if not args.no_pdfs:
        fetch_pdfs()


if __name__ == "__main__":
    main()