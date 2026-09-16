# AGENTS.md — sylo-ignition

## What this repo is

An **MCP server package** (v0.2.0+). The pi TypeScript extension was removed —
the tools are **not** library functions you can import or shell out to ad hoc.
They are exposed over the **Model Context Protocol** and require an **MCP
client** (Claude Code, Codex, pi via pi-mcp-adapter, any MCP-compatible
harness) to call them.

## Registering the server

- **Claude Code**: git clone this repo — it reads the root `.mcp.json`
  (server name `ignition`). Approve the project server when prompted on first
  use. One-time deps: `pip install -r scripts/requirements.txt`.
- **Codex**: `codex mcp add ignition -- python server/server.py`
- **pi**: `pi install npm:sylo-ignition` — pi-mcp-adapter auto-registers the
  bundled `.mcp.json` (declared as `pi.mcp` in package.json). Set
  `toolPrefix: "none"` in adapter settings so tool names stay exactly
  `ignition_*` as referenced everywhere in the docs/skills.

Python 3.12+ recommended (Windows: `python`; otherwise `python3`). Set
`SYLO_PYTHON` to override the interpreter used for the wrapped scripts.

## The tools (server name: `ignition`)

| Tool | Purpose | Gated |
|---|---|---|
| `ignition_status` | gateway reachability/version, projects, Designer sessions, allowlist summary — run FIRST | — |
| `ignition_project_resources` | list project resources on disk | — |
| `ignition_resource_read` | read a resource file (text/JSON) | — |
| `ignition_resource_write` | atomic resource write | write-allowlist |
| `ignition_validate` | offline lint (view.json structure, Jython 2.7) | — |
| `ignition_scan` | REST hot-apply of on-disk edits | allow_scan |
| `ignition_project_create` | create empty project + scan to disk | allow_project_create |
| `ignition_backup` | download full gateway backup (.gwbk) | — |
| `ignition_screenshot` | Perspective session screenshot (returns PNG path — read it with your harness's vision) | — |
| `ignition_gateway_logs` | read gateway logs via REST | — |
| `ignition_api_get` | read-only GET passthrough to the gateway REST API | GET-only |

Source of truth for schemas/args: `server/server.py` (thin MCP wrapper) and
`scripts/*.py` (real logic; JSON-out contract). Read `skills/ignition/SKILL.md`
before doing Ignition work — it documents the 8.3 file-based workflow, house
rules, and gateway config.

## Rules for AI working on this repo

- **Never edit `assets/write-allowlist.json`** — operator-managed, enforced in
  Python. The agent must not modify it, and no tool does.
- Tool names are referenced verbatim in skills/docs — keep them identical if
  you change the tool surface, and update wrapper + script together.
- Windows: the wrapper spawns script subprocesses with `stdin=DEVNULL` —
  inheriting the MCP stdio pipe makes the child's `Py_Initialize` lseek block
  forever. Keep that flag if you touch `server/server.py`.
- Verify changes with an MCP stdio client (list tools + a read-only call,
  e.g. `ignition_status`). Gateway config lives outside any repo at
  `~/.ignition-sylo/config.json`.