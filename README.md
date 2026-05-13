# vivarium-dashboard

Web-based dashboard for [Vivarium](https://vivarium-collective.github.io/) /
[process-bigraph](https://github.com/vivarium-collective/process-bigraph) workspaces.

Extracted from `pbg-template` so the dashboard runtime can be pip-installed
into any workspace venv rather than being vendored at scaffold-time. Template
scaffolding still lives in `pbg-template`; the dashboard runtime now lives here.

## Install

```bash
pip install -e /path/to/vivarium-dashboard
# or, into a workspace venv
./.venv/bin/pip install -e /path/to/vivarium-dashboard
```

## Usage

From inside a workspace (directory containing `workspace.yaml`):

```bash
vivarium-dashboard serve
# or pin a port
vivarium-dashboard serve --port 8765
# or point at a specific workspace
vivarium-dashboard serve --workspace /path/to/ws --port 8765
```

This renders `<workspace>/reports/index.html` and starts a local HTTP server
backing the 5-tab dashboard.

## What's included

- `vivarium_dashboard.server` — REST + SSE server (`/api/state`, `/api/composites`,
  `/api/composite-test-run`, `/api/workspace-manifest`, …)
- `vivarium_dashboard.lib.*` — workspace helpers (composite lookup/runs,
  investigations, pyproject editing, report rendering, …)
- `vivarium_dashboard/templates/index.html.j2` — dashboard template (Jinja2)
- `vivarium_dashboard/static/` — CSS, JS, vivarium logo, bundled
  `loom-explore` viewer

## Provenance

This package was extracted from
[pbg-template](https://github.com/vivarium-collective/pbg-template)'s
`template/scripts/_{server,templates,assets,lib}/` directories. Workspaces
scaffolded from `pbg-template` now depend on `vivarium-dashboard` as a
regular pip dep.
