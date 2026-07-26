# Module Cards — Content Counts + Workspace Usage — Design

**Date:** 2026-07-26
**Status:** Design (approved via clarification: usage = "referenced by my work"; all sort/metadata options)
**Scope:** vivarium-workbench (Registry → Modules + Marketplace card grids)

## Goal

Each module card (Registry → Modules and the Marketplace tab) surfaces, for every
module in the catalog:

- **# composites** the module provides
- **# investigations** the module ships
- **# studies** the module ships
- **# used in this workspace** — how many of the module's composites/studies are
  actually **referenced by this workspace's own investigations/studies** (the
  "we depend on this" signal), not merely present.
- **source / ref** (git URL @ ref) and **last-updated**

Cards are **sortable** by: install state + name (current default), **usage
(most-used first)**, each content count, and **recency (last-updated)**.

## Data model (per catalog module entry)

`build_catalog` / `build_marketplace` entries gain (all additive, default 0/null):

```
n_composites:   int
n_investigations: int
n_studies:      int
n_used:         int      # composites+studies of this module referenced by THIS workspace
last_updated:   str|null # ISO date from the module's git HEAD (or file mtime fallback)
```

`source`/`ref` already present on installed entries; ensure they're populated for
available (catalog) entries from the catalog metadata.

## Where the counts come from

Reuse the federation/linked-workspace scan (`lib/federation.py`) — it already
resolves each installed module's on-disk root + composites/studies/investigations:

- **Composites:** `federated_composites` (packaged, always countable) grouped by
  origin module → `n_composites`. For the module's own count independent of
  install mode, count `<pkg>/composites/*.composite.*`.
- **Studies / investigations:** for a full-repo-installed module (landed at
  `external/<name>/`), count its `studies/` dirs and `investigations/` dirs via
  its `WorkspacePaths`. For wheel-only installs (no top-level studies), these are
  0 (not on disk) — the card shows 0 with a subtle "code-only install" hint.

- **`n_used` (referenced by my work):** scan THIS workspace's own study specs and
  investigations for references to the module's items:
  - a study whose `baseline[].composite` (or comparison composite) resolves to a
    composite id owned by the module (`<pkg>.composites.<stem>`), OR
  - a study/investigation that references one of the module's studies by its
    federated id.
  Count distinct module items referenced. Cheap: build the set of the module's
  item ids once, then intersect with the references gathered from the workspace's
  own specs.

New helper in `lib/federation.py` (or a small `lib/module_stats.py`):
`module_content_stats(ws_root) -> dict[module_name, {n_composites, n_investigations, n_studies, n_used, last_updated}]`.
Best-effort per module (never raises).

## API

Extend the existing `/api/marketplace` and `/api/catalog` payloads: merge
`module_content_stats` into each module entry by name. (No new endpoint; the
stats are additive fields on the existing `CatalogPayload` entries, which are
`extra="allow"`.)

## Frontend (`walkthrough.js`)

- `_moduleActionFor` / card body (`_renderModuleGrid`): add a compact stat row —
  `▦ N composites · ⌥ N studies · ⌸ N investigations · ★ N used` (omit a metric
  when its count is 0, except keep "used" visible when >0). Add source/ref +
  last-updated line.
- Toolbar: add a **Sort** control to the module grids with options: `Installed & name`
  (default), `Most used`, `# composites`, `# studies`, `# investigations`,
  `Recently updated`. Wire to `_renderCatalog`/`_renderMarketplace` via a
  `window._catalogSort` / `window._marketplaceSort` state, applied in
  `_renderModuleGrid` before the existing installed-first sort (sort key first,
  then stable tiebreak by name).

## Non-goals

- No new "usage detail" drill-down (which specific studies use it) — just the count.
- No live git fetch for last-updated; use local HEAD/commit date or file mtime.

## Testing

- `module_content_stats` unit tests against a fixture workspace with a linked
  module (composites+studies+investigations) AND an own study that references one
  of the module's composites → assert `n_composites/n_studies/n_investigations`
  and `n_used == 1`.
- Endpoint test: `/api/marketplace` entries carry the new count fields.
- Frontend: `node --check` + grep that the stat row + sort control are wired into
  both grids.

## Rollout

Own branch/commit, separable from the federation feature (it depends on
`lib/federation.py` but is a distinct card-UI concern).
