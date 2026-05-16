# vivarium-dashboard

Local web UI for [Process-Bigraph](https://github.com/vivarium-collective/process-bigraph)
workspaces. Browse composites, run studies, inspect state-trees, and render
visualizations — without writing dashboard boilerplate.

Point it at a workspace directory (one containing `workspace.yaml`) and it
serves an interactive UI over the workspace's registry, composites, studies,
and reports.

> **Status:** in active beta. APIs and UI may change before 1.0.

## Install

Not yet on PyPI. Install editable from a clone:

```bash
git clone https://github.com/vivarium-collective/vivarium-dashboard ~/code/vivarium-dashboard
./.venv/bin/pip install -e ~/code/vivarium-dashboard   # into your workspace's venv
```

For workspaces scaffolded from [pbg-template](https://github.com/vivarium-collective/pbg-template),
`template-init.sh` wires this up automatically when a sibling
`../vivarium-dashboard/` directory is detected.

## Quick start

From inside a workspace:

```bash
vivarium-dashboard serve                      # default port
vivarium-dashboard serve --port 8765          # pin a port
vivarium-dashboard serve --workspace /path/to/ws --port 8765
```

Then open the printed URL in your browser. Workspaces scaffolded from
`pbg-template` also expose this as `bash scripts/serve.sh`.

## Tabs at a glance

- **Workspace inputs** — workspace.yaml summary, dependencies, scaffolding status.
- **Registry** — every Process / Step / Composite the workspace can import.
- **Composites** — composite browser with an embedded loom-explore view of the
  state-tree (the bigraph).
- **Studies** — canonical 8-section view (Purpose · Pipeline gate · Build ·
  Simulations · Readouts · Tests · Limitations · References) with phase chip
  and rolled-up `effective_status`.
- **Investigations** — DAG canvas grouping studies into research arcs, with
  a "+ New Investigation" creator. *(Final polish shipping in PR #18.)*
- **Visualizations** — render Visualization Steps wired into composites.
- **GitHub Branches** — active branch, push, open PR for the workstream.

## Companion repos

- **[pbg-superpowers](https://github.com/vivarium-collective/pbg-superpowers)** — the Claude Code plugin whose `/pbg-*` skills drive this dashboard's HTTP API. Use it for AI-assisted authoring.
- **[pbg-template](https://github.com/vivarium-collective/pbg-template)** — the workspace scaffold this dashboard serves. Includes the canonical `.pbg/schemas/` validators.

## Migrating an older workspace

If your workspace has `investigations/<name>/spec.yaml` directories from
before schema_version 3, run the one-time migration:

```bash
vivarium-dashboard migrate-investigations --workspace /path/to/workspace
# add --dry-run to preview
```

## License

TBD — license file pending before 1.0.
