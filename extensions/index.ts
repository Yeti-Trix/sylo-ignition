/**
 * sylo-ignition — Ignition 8.3 gateway + project assistant.
 *
 * File-based workflow on a live 8.3 gateway: author/edit project resources on
 * disk (data/projects/**), trigger REST scans to hot-apply, screenshot Perspective
 * sessions for vision verification. Writes are gated by the operator-managed
 * write-allowlist (assets/write-allowlist.json) — enforced in Python, never
 * agent-editable.
 *
 * @see features_tracker/active/2026-08-30_16-59-56_sylo_ignition_package.md
 */
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

const execFileAsync = promisify(execFile)

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPTS_DIR = path.join(PACKAGE_ROOT, 'scripts')

type ToolContentBlock = { type: 'text'; text: string }

const TIMEOUTS: Record<string, number> = {
  'screenshot.py': 120_000,
  'backup.py': 360_000,
  'scan.py': 120_000,
}

function resolvePython(): { command: string; prefixArgs: string[] } {
  const envPython = process.env.SYLO_PYTHON?.trim()
  if (envPython) return { command: envPython, prefixArgs: [] }
  return { command: process.platform === 'win32' ? 'python' : 'python3', prefixArgs: [] }
}

function toolError(text: string): { content: ToolContentBlock[] } {
  return { content: [{ type: 'text', text }] }
}

function parseTrailingJson(stdout: string): Record<string, unknown> | null {
  const trimmed = stdout.trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed) as Record<string, unknown>
  } catch {
    /* fall through */
  }
  let idx = trimmed.lastIndexOf('\n{')
  while (idx >= 0) {
    const candidate = trimmed.slice(idx + 1)
    try {
      return JSON.parse(candidate) as Record<string, unknown>
    } catch {
      idx = trimmed.lastIndexOf('\n{', idx - 1)
    }
  }
  return null
}

function tail(text: string, lines = 12): string {
  return text.trim().split('\n').slice(-lines).join('\n').trim()
}

async function runPythonScript(
  scriptName: string,
  args: string[],
  timeoutMs?: number,
): Promise<{ content: ToolContentBlock[] }> {
  const timeout = timeoutMs ?? TIMEOUTS[scriptName] ?? 90_000
  const scriptPath = path.join(SCRIPTS_DIR, scriptName)
  const { command, prefixArgs } = resolvePython()
  try {
    const { stdout, stderr } = await execFileAsync(command, [...prefixArgs, scriptPath, ...args], {
      cwd: PACKAGE_ROOT,
      maxBuffer: 64 * 1024 * 1024,
      windowsHide: true,
      timeout,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    })
    const parsed = parseTrailingJson(stdout) as
      | { ok?: boolean; error?: string; operator_chat?: string }
      | null
    if (!parsed) {
      return toolError(tail(stdout) || stderr.trim() || `${scriptName} produced no output`)
    }
    if (parsed.ok === false) {
      return toolError(String(parsed.error ?? `${scriptName} failed`))
    }
    if (typeof parsed.operator_chat === 'string' && parsed.operator_chat.trim()) {
      return { content: [{ type: 'text', text: parsed.operator_chat.trim() }] }
    }
    return { content: [{ type: 'text', text: JSON.stringify(parsed, null, 2) }] }
  } catch (err) {
    const e = err as NodeJS.ErrnoException & { stdout?: string; stderr?: string }
    const parsed = typeof e.stdout === 'string' ? parseTrailingJson(e.stdout) : null
    if (parsed && typeof parsed.error === 'string' && parsed.error.trim()) {
      return toolError(parsed.error.trim())
    }
    const detail = [
      typeof e.stdout === 'string' ? tail(e.stdout) : '',
      typeof e.stderr === 'string' ? tail(e.stderr) : '',
    ]
      .filter(Boolean)
      .join('\n')
    const message = err instanceof Error ? err.message : String(err)
    return toolError(detail ? `${message}\n${detail}` : message)
  }
}

/** Large content (view JSON) can exceed Windows argv limits — stage to a temp file. */
async function stageContent(content: string): Promise<string[]> {
  if (content.length < 6000) return ['--content', content]
  const tmp = path.join(os.tmpdir(), `sylo-ignition-content-${Date.now()}.txt`)
  await fs.promises.writeFile(tmp, content, 'utf-8')
  return ['--content-file', tmp]
}

export default function piSyloIgnitionExtension(pi: ExtensionAPI): void {
  pi.registerTool({
    name: 'ignition_status',
    label: 'Ignition gateway status',
    description:
      'Gateway reachability + version, project list, open Designer sessions (write-conflict warning), config presence, allowlist summary. Run this FIRST in any Ignition task.',
    parameters: Type.Object({}),
    async execute() {
      return runPythonScript('status.py', [])
    },
  })

  pi.registerTool({
    name: 'ignition_project_resources',
    label: 'Ignition project resource tree',
    description:
      'List a project\'s resources on disk (views, scripts, themes, etc.) grouped by module scope, with payload types. Read any of them with ignition_resource_read.',
    parameters: Type.Object({
      project: Type.Optional(Type.String({ description: 'Project name (default from config)' })),
      filter: Type.Optional(Type.String({ description: 'Case-insensitive path substring filter' })),
      files: Type.Optional(Type.Boolean({ description: 'Also list non-resource file groups' })),
    }),
    async execute(_id, params) {
      const args: string[] = []
      const project = String(params.project ?? '').trim()
      if (project) args.push('--project', project)
      const filter = String(params.filter ?? '').trim()
      if (filter) args.push('--filter', filter)
      if (params.files === true) args.push('--files')
      return runPythonScript('project_resources.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_resource_read',
    label: 'Ignition read resource',
    description:
      'Read a project resource file (view.json, .py, theme.css, resource.json, any text file) as pretty JSON or text. Binary files are refused.',
    parameters: Type.Object({
      path: Type.String({ description: 'Path relative to project root, e.g. com.inductiveautomation.perspective/views/mainView/view.json' }),
      project: Type.Optional(Type.String({ description: 'Project name (default from config)' })),
      max_chars: Type.Optional(Type.Number({ description: 'Truncate content at N chars (default 40000)' })),
    }),
    async execute(_id, params) {
      const p = String(params.path ?? '').trim()
      if (!p) return toolError('ignition_resource_read requires path.')
      const args = ['--path', p]
      const project = String(params.project ?? '').trim()
      if (project) args.unshift('--project', project)
      if (typeof params.max_chars === 'number' && params.max_chars > 0)
        args.push('--max-chars', String(Math.floor(params.max_chars)))
      return runPythonScript('resource_read.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_resource_write',
    label: 'Ignition write resource',
    description:
      'GATED (write-allowlist): atomically write a project resource file. JSON must parse; forbidden targets (digest, .bin, thumbnails, .resources, gateway config) are refused. New resource folders get a scan-compatible resource.json scaffold. Follow with ignition_scan to hot-apply.',
    parameters: Type.Object({
      path: Type.String({ description: 'File path relative to project root' }),
      content: Type.String({ description: 'Full file content (text/JSON)' }),
      project: Type.Optional(Type.String({ description: 'Project name — must be enabled in the write-allowlist' })),
    }),
    async execute(_id, params) {
      const p = String(params.path ?? '').trim()
      const content = String(params.content ?? '')
      if (!p) return toolError('ignition_resource_write requires path.')
      if (!content) return toolError('ignition_resource_write requires non-empty content.')
      const project = String(params.project ?? '').trim()
      const staged = await stageContent(content)
      const args = project ? ['--project', project] : []
      args.push('--path', p, ...staged)
      return runPythonScript('resource_write.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_validate',
    label: 'Ignition validate resource',
    description:
      'Offline lint before writing/scanning: view.json structure + unique component names + binding shapes; Jython 2.7 compatibility for project scripts (f-strings are errors); resource.json key checks. Never touches the gateway.',
    parameters: Type.Object({
      path: Type.String({ description: 'Resource file path relative to project root' }),
      project: Type.Optional(Type.String({ description: 'Project name (default from config)' })),
    }),
    async execute(_id, params) {
      const p = String(params.path ?? '').trim()
      if (!p) return toolError('ignition_validate requires path.')
      const args = ['--path', p]
      const project = String(params.project ?? '').trim()
      if (project) args.unshift('--project', project)
      return runPythonScript('validate.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_scan',
    label: 'Ignition scan (hot-apply)',
    description:
      'GATED (allow_scan): trigger POST /data/api/v1/scan/{scope} to hot-apply on-disk edits into the gateway + open Designers. Warns when a Designer session is open. Polls until the scan completes. Scope=projects for view/tag/script edits; config for gateway config.',
    parameters: Type.Object({
      scope: Type.Optional(Type.String({ description: 'projects | config (default projects)' })),
      wait_seconds: Type.Optional(Type.Number({ description: 'Max poll seconds (default 60)' })),
    }),
    async execute(_id, params) {
      const args: string[] = []
      const scope = String(params.scope ?? 'projects').trim()
      if (scope) args.push('--scope', scope)
      if (typeof params.wait_seconds === 'number' && params.wait_seconds > 0)
        args.push('--wait', String(params.wait_seconds))
      return runPythonScript('scan.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_project_create',
    label: 'Ignition create project',
    description:
      'GATED (allow_project_create): create a NEW empty project via REST (isolated, low-risk) and scan it onto disk. Use for scratch/demo projects — then enable it in the write-allowlist to write its resources.',
    parameters: Type.Object({
      name: Type.String({ description: 'New project name (no spaces/slashes)' }),
      title: Type.Optional(Type.String({ description: 'Display title (defaults to name)' })),
      description: Type.Optional(Type.String({ description: 'Project description' })),
    }),
    async execute(_id, params) {
      const name = String(params.name ?? '').trim()
      if (!name) return toolError('ignition_project_create requires name.')
      const args = ['--name', name]
      const title = String(params.title ?? '').trim()
      const desc = String(params.description ?? '').trim()
      if (title) args.push('--title', title)
      if (desc) args.push('--description', desc)
      return runPythonScript('project_create.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_backup',
    label: 'Ignition gateway backup',
    description:
      'Download a full gateway backup (.gwbk) via REST to ~/.ignition-sylo/backups/. Run before risky/bulk changes as the rollback safety net (restore via gateway web UI).',
    parameters: Type.Object({
      out: Type.Optional(Type.String({ description: 'Output .gwbk path (default ~/.ignition-sylo/backups/<timestamp>.gwbk)' })),
    }),
    async execute(_id, params) {
      const out = String(params.out ?? '').trim()
      const args = out ? ['--out', out] : []
      return runPythonScript('backup.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_screenshot',
    label: 'Ignition Perspective screenshot',
    description:
      'Screenshot a Perspective session page (uses installed Chrome/Edge — no browser download). Save path is returned; read it with analyze_image for the vision design-quality loop. Requires pip playwright (package requirements).',
    parameters: Type.Object({
      project: Type.Optional(Type.String({ description: 'Project name (default from config)' })),
      path: Type.Optional(Type.String({ description: 'View path segment appended to the client URL' })),
      url: Type.Optional(Type.String({ description: 'Full override URL (advanced)' })),
      out: Type.Optional(Type.String({ description: 'Output PNG path' })),
      width: Type.Optional(Type.Number({ description: 'Viewport width (default 1600)' })),
      height: Type.Optional(Type.Number({ description: 'Viewport height (default 900)' })),
      wait_ms: Type.Optional(Type.Number({ description: 'Render settle ms (default 9000)' })),
    }),
    async execute(_id, params) {
      const args: string[] = []
      const project = String(params.project ?? '').trim()
      if (project) args.push('--project', project)
      const p = String(params.path ?? '').trim()
      if (p) args.push('--path', p)
      const url = String(params.url ?? '').trim()
      if (url) args.push('--url', url)
      const out = String(params.out ?? '').trim()
      if (out) args.push('--out', out)
      if (typeof params.width === 'number') args.push('--width', String(params.width))
      if (typeof params.height === 'number') args.push('--height', String(params.height))
      if (typeof params.wait_ms === 'number') args.push('--wait-ms', String(params.wait_ms))
      return runPythonScript('screenshot.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_gateway_logs',
    label: 'Ignition gateway logs',
    description:
      'Read gateway logs via REST (filters: level, search, logger). Use when a scan fails or a resource does not appear — scan/resource errors land here.',
    parameters: Type.Object({
      limit: Type.Optional(Type.Number({ description: 'Max entries (default 100)' })),
      min_level: Type.Optional(Type.String({ description: 'e.g. WARN or ERROR' })),
      search: Type.Optional(Type.String({ description: 'Substring search in messages' })),
      logger: Type.Optional(Type.String({ description: 'Logger name filter' })),
    }),
    async execute(_id, params) {
      const args: string[] = []
      if (typeof params.limit === 'number' && params.limit > 0) args.push('--limit', String(Math.floor(params.limit)))
      const minLevel = String(params.min_level ?? '').trim()
      if (minLevel) args.push('--min-level', minLevel)
      const search = String(params.search ?? '').trim()
      if (search) args.push('--search', search)
      const logger = String(params.logger ?? '').trim()
      if (logger) args.push('--logger', logger)
      return runPythonScript('gateway_logs.py', args)
    },
  })

  pi.registerTool({
    name: 'ignition_api_get',
    label: 'Ignition REST GET (read-only)',
    description:
      'Read-only GET passthrough to the 588-route gateway REST API (resource lists, gateway info, tag export, Perspective sessions...). GET only — mutating verbs are refused. Use --save for big payloads like /openapi.json.',
    parameters: Type.Object({
      route: Type.String({ description: 'GET route starting with /data/ (query string allowed), or /openapi.json' }),
      save: Type.Optional(Type.String({ description: 'Save the full payload to this file path (recommended for large responses)' })),
    }),
    async execute(_id, params) {
      const route = String(params.route ?? '').trim()
      if (!route) return toolError('ignition_api_get requires route.')
      const args = ['--route', route]
      const save = String(params.save ?? '').trim()
      if (save) args.push('--save', save)
      return runPythonScript('api_get.py', args)
    },
  })
}