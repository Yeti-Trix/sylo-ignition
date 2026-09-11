# sylo-ignition

Ignition 8.3 gateway + project assistant for Sylo. Lets the agent create and
edit Ignition projects the way Ignition 8.3 is designed to be edited: **files on
disk + REST scan** — no Designer automation, no zip import/export.

- **Workflow**: `ignition_status` → `ignition_project_resources` →
  `ignition_resource_read` → edit → `ignition_validate` →
  `ignition_resource_write` → `ignition_scan` → `ignition_screenshot` →
  `analyze_image` (vision design loop).
- **8.3 only**: 8.1 keeps everything in an internal SQLite DB and has no REST
  API — 8.1 support would be a separate, zip-based kit (deferred).
- **Safety**: all mutating tools enforce the operator-managed
  `assets/write-allowlist.json` (the agent must never edit it). Gateway
  backups via `ignition_backup`. Forbidden targets (digest, `.bin`,
  `.resources/`, runtime state) are refused in code.
- **Connection config** lives outside git at `~/.ignition-sylo/config.json`
  (`gateway_url`, `api_token`, `data_dir`, `default_project`). Setup recipe in
  the `ignition` skill.
- **Docs**: `references/` holds the offline 8.3 User Manual (1,566 pages,
  Markdown), SDK guide, verified REST route map, and the fetch tool
  (`scripts/fetch_docs.py`). 8.1 PDF bundle is git-ignored, re-fetchable.

See `features_tracker/active/2026-08-30_16-59-56_sylo_ignition_package.md`
for the design record.