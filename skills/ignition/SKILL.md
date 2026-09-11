---
name: ignition
description: Create and edit Ignition 8.3 projects — file-based resource authoring on the gateway's data dir, REST scan to hot-apply, screenshot-verified Perspective UI. Write-allowlist gated; 8.1 is NOT supported.
metadata:
  sylo:
    category: automation
    icon: cpu
---

# Ignition — file-based 8.3 workflow

Sylo edits Ignition **8.3** project resources directly on disk (`data/projects/<name>/...`),
then triggers a gateway **scan** to hot-apply them — no Designer import step, no zip. All
mutating tools enforce the operator-managed **write-allowlist**. This targets **8.3 only**:
8.1 keeps projects + config in an internal SQLite DB with no REST API — see the reference
skill's version notes.

## First-run setup (operator, one time)

1. **API key**: gateway web UI → Platform → Security → API Keys → Create API Key +
   (Basic Token). Uncheck "Require secure connections" for a plain-HTTP local gateway.
   Copy the token.
2. **Security level**: Platform → Security → **Levels** → select `Authenticated` →
   Add Level + → name it `SyloAPI` → Save. Then edit the API key and check `SyloAPI`.
   (Role-derived levels like Administrator are greyed out for API keys — custom levels are not.)
3. **Grant access**: Platform → Security → General Settings → **Roles and Permissions** →
   check `SyloAPI` for Gateway Read AND Gateway Write. Save.
4. **Config file** at `C:\Users\<user>\.ignition-sylo\config.json` (OUTSIDE any repo —
   tokens never go in git):
   ```json
   {
     "gateway_url": "http://localhost:8088",
     "api_token": "Sylo:...",
     "data_dir": "C:\\Program Files\\Inductive Automation\\Ignition\\data",
     "default_project": "SyloSandbox"
   }
   ```
5. **File-write permission** (native Windows install under Program Files — one time,
   elevated PowerShell; the Users group only has read on the data dir by default):
   ```powershell
   icacls "C:\Program Files\Inductive Automation\Ignition\data\projects" /grant "<user>:(OI)(CI)M"
   icacls "C:\Program Files\Inductive Automation\Ignition\data\config" /grant "<user>:(OI)(CI)M"
   ```
6. `ignition_status` should now show `gateway_reachable: true` and the project list.

## Core loop

1. **`ignition_status`** — always first. Note open Designer sessions (conflict risk),
   which projects exist, and what the allowlist permits.
2. **`ignition_project_resources`** — see the resource tree of the project you'll touch.
3. **`ignition_resource_read`** — study existing views before authoring (match the
   house style; the Example project's `mainView` is a good reference).
4. Author/edit → **`ignition_validate`** (catch structure + Jython-2.7 errors offline).
5. **`ignition_resource_write`** — allowlist-gated atomic write. New folders get a
   scan-compatible `resource.json` scaffold automatically.
6. **`ignition_scan`** (scope projects) — hot-apply into the gateway + Designer.
7. **`ignition_screenshot`** → `analyze_image` — visual verification / design critique loop.
8. If something didn't apply: **`ignition_gateway_logs`** (search "scan" / "resource").

Use **`ignition_project_create`** for a scratch project, and **`ignition_backup`**
before risky or bulk changes (restorable .gwbk in `~/.ignition-sylo/backups/`).
**`ignition_api_get`** is the read-only passthrough for everything else on the
588-route API (resource lists, sessions, tag export JSON, gateway info...).

## Gates (hard rules)

| Tool | Gate |
|------|------|
| `ignition_resource_write` | project must be present + **enabled** in `assets/write-allowlist.json` |
| `ignition_scan` | `allow_scan` must be true |
| `ignition_project_create` | `allow_project_create` must be true (creates only NEW isolated projects) |
| write-allowlist itself | **never edit it as the agent** — operator-owned; ask the operator |

If a gate blocks you, explain to the operator exactly what to change and stop.
Default scratch project: **SyloSandbox** (pre-enabled). Never write `Example`
(read-only by default) or any production project the operator hasn't listed.

## Forbidden paths (the write tool also refuses these)

- `**/.resources/`, `*.digest.json` — gateway internals
- `data/var/**`, `config/local/**`, `*.idb` — runtime state / local overrides
- `*.bin`, thumbnails, images — binary payloads produced by Designer/gateway
- Existing `resource.json` — the gateway owns it (signatures/timestamps);
  new-resource scaffolds are created automatically by the write tool
- Gateway `data/config/**` — out of scope for project writes (Phase 3)

## Designer conflict rule

A scan while the Designer has **unsaved edits** can clobber them. Before
`ignition_scan`, check `ignition_status`. If Designer sessions are open, ask the
operator to save/close (or confirm proceed). Never scan silently over an open
Designer.

## Gotchas

- **Views are reachable only via pages**: a new project has no page-config, so sessions
  show "No view configured for this page". Write
  `com.inductiveautomation.perspective/page-config/config.json` mapping `"/"` to your
  view path (schema in the reference skill), then scan. The URL after the project name
  is the PAGE path, not the view path.
- **The scan silently drops malformed resources** — a bad view.json produces no error,
  just an absent view. ALWAYS screenshot-verify after scanning; if the view is missing,
  check the structure against the verified schema (top-level `root` component — see
  reference skill) and `ignition_gateway_logs`.
- **Position modes**: `flow` inside flex containers is verified working; **`percent`
  inside coord containers did NOT apply in live testing** (labels stacked at 0,0) — use
  absolute pixel x/y/width/height inside coord containers.
- **Jython 2.7**: project gateway scripts are Python 2 — no f-strings, no
  async/await, no pathlib. `ignition_validate` catches these; write `.format()` code.
- **Windows paths**: resource paths use forward slashes in tool calls; the
  scripts handle OS joins. Keep view folder names short (255-char path limit).
- **Program Files ACL**: native installs need the one-time icacls grant (setup step 5)
  — otherwise writes fail with Access denied.
- **Encoding**: scripts run with UTF-8 forced; write tool always writes UTF-8
  with `\n` endings.
- **Scans are global**: `scan/projects` scans ALL projects, not just yours —
  another reason the Designer rule matters.
- **No tag VALUES via REST**: 8.3 REST manages tag *definitions* (tags export/import
  JSON); live values go through scripting/OPC-UA — currently out of scope.
- The full offline 8.3 User Manual (1,566 pages) + SDK docs live in the Sylo repo at
  `packages/sylo-ignition/references/` — grep them via the **ignition-reference** skill
  before guessing formats.

## Design quality (operator standard: beautiful, intuitive, clean)

When building views, aim for real design quality, not just function: consistent
spacing rhythm, meaningful hierarchy (page title → section → content), color used
sparingly for state (not decoration), labels that read like the machine ("Conveyor
Speed" not "tag1"), large readable values for at-a-glance operation. Always
screenshot and critique against these rules before reporting done; iterate at
least once when something feels off.