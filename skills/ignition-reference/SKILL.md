---
name: ignition-reference
description: Ignition 8.3 offline documentation map + format quickrefs — Perspective view JSON, bindings, component catalog, tag JSON, theme files, gateway REST routes, Jython 2.7. Grep the local manual before guessing.
metadata:
  sylo:
    category: automation
    icon: cpu
---

# Ignition reference — offline docs + format quickrefs

## Offline documentation (grep here first)

Full 8.3 User Manual as grep-friendly Markdown (1,566 pages) + SDK guide live in the
Sylo repo:

- `packages/sylo-ignition/references/user-manual-8.3/` — the whole manual, Docusaurus
  pages converted to `.md` (pipe/grid tables, fenced code, internal links rewritten
  to relative `.md`). `references/README.md` lists key pages.
- `packages/sylo-ignition/references/sdk-docs/` — SDK Programmer's Guide (resource
  collections, module model).
- `packages/sylo-ignition/references/user-manual-8.1-pdfs/` — official 8.1 PDFs
  (git-ignored, 262 MB; 8.1 has NO REST API / file config — only zip + gwbk workflows).
- `packages/sylo-ignition/references/gateway-rest-api-8.3.md` — verified route map of
  the 588-route REST API + the working API-key auth recipe.
- Regenerate everything: `python packages/sylo-ignition/scripts/fetch_docs.py`.

Key manual pages (relative to `user-manual-8.3/`):

- Perspective components: `appendix/components/perspective-components/` (every
  component: props, events, style tips)
- Perspective props/bindings: `perspective/props/` and `perspective/bindings/`
- Expressions: `appendix/expression-functions/` ( Perspective expression language)
- Scripting (Jython 2.7): `appendix/scripting-functions/` + `perspective/scripting/`
- Tags: `platform/tags/` (tag properties, UDTs, tag file JSON)
- Gateway folder structure: `appendix/reference-pages/gateway-folder-structure.md`
- Version control / file-based config: `tutorials/version-control-guide.md`
- Security: `platform/security/` (API keys, security levels, zones)

## On-disk layout (8.3, verified on a live gateway)

```
data/
├── projects/<Name>/
│   ├── project.json               # {title, description, enabled, inheritable, parent}
│   └── com.inductiveautomation.perspective/
│       ├── views/<viewPath>/     # view.json + thumbnail.png + resource.json
│       ├── page-config/config.json/
│       ├── page-startup/onPageStartup.py/
│       └── session-props/props.json/
└── config/                        # gateway config (JSON, scan via /scan/config)
```

`resource.json` (per folder, gateway-owned — never hand-edit existing):
`{scope: "G", version: 1, restricted, overridable, files: [...], attributes:
{lastModificationSignature, lastModification: {actor, timestamp}}}`

## Perspective view.json quickref (VERIFIED live on 8.3.9)

```json
{
  "custom": {},
  "params": {},
  "props": {},
  "root": {
    "type": "ia.container.coord",
    "meta": { "name": "root" },
    "children": [
      {
        "type": "ia.display.label",
        "meta": { "name": "titleLabel" },
        "position": { "x": 24, "y": 24, "width": 400, "height": 40 },
        "props": {
          "text": "Machine Overview",
          "style": { "fontSize": "24px", "fontWeight": "bold" }
        }
      }
    ]
  }
}
```

- **`root` is a top-level key holding the root COMPONENT** (usually
  `ia.container.coord`) — NOT `props.root.children`. Malformed views are
  silently dropped by the scan.
- Component `type` comes from the catalog (`ia.<family>.<component>`); full prop
  details in `appendix/components/perspective-components/`.
- `meta.name` must be **unique** across the view.
- Position: absolute px (`x`,`y`,`width`,`height`) inside coord containers — VERIFIED.
  `mode: "flow"` for children of flex containers — VERIFIED. `mode: "percent"` —
  did NOT apply in live testing (unverified; avoid for now).
- Style lives under `props.style` (CSS-ish: fontSize, backgroundColor, padding,
  width, height); shared looks go in **style classes** (manual: `perspective/style-classes/`),
  referenced via `props.style.classes`.

## Page-config quickref (VERIFIED live on 8.3.9)

`com.inductiveautomation.perspective/page-config/config.json` — without it,
sessions show "No view configured for this page":

```json
{
  "pages": {
    "/": { "viewPath": "Home" },
    "/alarms": { "viewPath": "Alarms/Console" }
  },
  "sharedDocks": { "cornerPriority": "top-bottom" }
}
```

URL `…/data/perspective/client/<project>/<page>` maps `page` to the pages key above
(root page = `/`).

## Bindings quickref

Property bindings wrap the value:

```json
"props": { "text": { "binding": { "type": "property", "config": { "path": "view.params.title" } } } }
```

- `type: "property"` → `config.path` (`view.x`, `self.x`, `session.props.x`)
- `type: "tag"` → `config.path: "[default]Line1/Speed"`, optional `config.op` e.g.
  `readBlocking`? (see manual `perspective/bindings/tag-binding.md` for transforms/format)
- `type: "expr"` → `config.expression` — Perspective expression language
  (`{view.params.speed} * 60`, `coalesce()`, `if()`, `toFix()`)
- Transforms: `config.transforms: [{"type": "map", "config": {...}}]` etc.

## Tag file JSON quickref

Tags (definitions) live in the provider's config or can be round-tripped as JSON via
`GET /data/api/v1/tags/export` / `POST /data/api/v1/tags/import`. UDT definitions,
value types (`Int4`, `Float8`, `Boolean`, `String8`), alarm definitions — see
`platform/tags/tag-properties.md` and `platform/tags/udts/`. REST manages
definitions; live **values** need scripting/OPC-UA.

## Jython 2.7 quickref (gateway scripts)

Python 2 syntax: `print x` ok, prefer `print(x)`; string formatting `%` or
`.format()`; no f-strings, no async, no pathlib/dataclasses/match. `system.*`
scripting functions in `appendix/scripting-functions/` (e.g.
`system.tag.readBlocking`, `system.perspective.sendMessage`).

## Gateway REST quickref

- Auth: header `X-Ignition-API-Token`; 401 = dead token, 403 = insufficient
  security level (see gateway-rest-api-8.3.md for the working SyloAPI recipe)
- Projects: `/data/api/v1/projects/{list,names,find/{n},copy,rename/{n},export/{n},import/{n}}`
- Scan: `POST /data/api/v1/scan/{projects,config}`; lock:
  `POST /data/api/v1/scan-lock/projects`
- Resources (gateway config types incl. tag-provider, opcua device, perspective
  themes): `/data/api/v1/resources/{list,names,find,singleton}/{moduleId}/{typeId}`
- Tags: `/data/api/v1/tags/{export,import}` (JSON definitions)
- Perspective: `/data/perspective/api/v1/sessions/`, `.../themes/copy-base-themes`
- Status/diagnostics: `/data/api/v1/{gateway-info,overview,overview/problems,logs}`,
  `GET /data/api/v1/backup` (.gwbk), `/data/api/v1/designers` (open sessions)
- Full spec: `GET /openapi.json` (12 MB — save to disk, don't inline)