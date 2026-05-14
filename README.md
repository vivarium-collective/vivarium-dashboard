# vivarium-dashboard

Web-based dashboard for [Vivarium](https://vivarium-collective.github.io/) /
[process-bigraph](https://github.com/vivarium-collective/process-bigraph) workspaces.

Extracted from `pbg-template` so the dashboard runtime can be pip-installed
into any workspace venv rather than being vendored at scaffold-time. Template
scaffolding still lives in `pbg-template`; the dashboard runtime now lives here.

## Install

> **Not yet published on PyPI.** Listing `vivarium-dashboard` in a fresh
> workspace's `pyproject.toml` and running `uv pip install -e .` will fail
> with *"vivarium-dashboard was not found in the package registry"* until
> this package ships to PyPI. In the meantime use an editable install from
> a local checkout and add a `[tool.uv.sources]` pin to the consumer's
> pyproject (see below).

### Editable install from a local checkout

```bash
# clone this repo as a sibling of your workspace
git clone https://github.com/vivarium-collective/vivarium-dashboard ~/code/vivarium-dashboard

# install into the workspace venv
cd /path/to/workspace
./.venv/bin/pip install -e ~/code/vivarium-dashboard
```

### Pin from a workspace's pyproject.toml

So `uv pip install -e ".[dev]"` resolves the dep without a manual second step:

```toml
[project]
dependencies = ["vivarium-dashboard", ...]

[tool.uv.sources]
vivarium-dashboard = { path = "../vivarium-dashboard", editable = true }
```

The `pbg-template` workspace template's `template-init.sh` adds this block
automatically when a sibling `../vivarium-dashboard/` directory (or
`$VIVARIUM_DASHBOARD_PATH`) is detected at scaffold time.

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
backing the interactive dashboard.

> **Heads up — there are two HTTP servers in play.** This `vivarium-dashboard
> serve` is the *interactive* one (side-rail tabs, Registry, Composites,
> Investigations, …). The separate `pbg-superpowers/server/start-server.sh`
> launched by the `/pbg-server` skill backs a minimal report-only server
> for stage-skill prompt mirroring; it does **not** serve this UI. If your
> browser shows only the static report ("biomodels · No models yet"), you
> launched the wrong one — stop it and use `bash scripts/serve.sh` (or
> `vivarium-dashboard serve --workspace .`) instead.

### Migration: Investigations → Studies (one-time)

If your workspace has `investigations/<name>/spec.yaml` directories created
before schema_version 3 / Studies, run the migration once:

```bash
vivarium-dashboard migrate-investigations --workspace /path/to/workspace
```

The script renames `investigations/` → `studies/`, bumps each spec from
v2 to v3, and lifts the first composite into `baseline:`. Multi-composite
investigations are migrated with a warning — recreate the extra composites
as variants from the new Study Detail view.

Add `--dry-run` to preview without writing.

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
