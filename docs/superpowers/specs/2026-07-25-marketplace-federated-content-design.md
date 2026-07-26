# Marketplace + Federated Ecosystem Content — Design

**Date:** 2026-07-25
**Status:** Design (approved for spec review)
**Scope:** vivarium-workbench

## Problem

The Registry page shows only modules that are *in* this workspace (its own
first-party package + installed dependencies), filtered further by the
workspace's `dashboard.registry.include` allow-list. There is no way to:

1. Browse the **whole viva ecosystem** and install any module, and
2. Once installed, **use that module's content** — its composites, studies, and
   investigations — from the current workspace.

Today an installed module contributes only *code* (Processes/Steps/Types via
`build_core`) and, incidentally, its **composites** (which live inside the
Python package `pbg_<slug>/composites/` and are already discovered by
`composite_lookup.discover_installed_pbg_composites`). Its **studies** and
**investigations** — which live at the repo *top level*, outside the Python
package — are invisible.

## Goals

- **Marketplace tab**: browse the full ecosystem registry (unfiltered) and
  install modules. *(SP-A — already implemented this iteration; see below.)*
- **Read-only federation**: an installed module's studies, investigations, and
  composites surface in the current workspace, each tagged with its origin repo.
- **Automatic**: federation happens for any installed module that ships this
  content — no separate opt-in step.
- **Provenance in the UI**: study cards, investigation cards, and composite
  cards show which repo they came from; study cards also show which
  investigations they belong to.
- **Reference foreign content** *(SP-C — separate spec)*: use a foreign
  composite as a study baseline, compare against a foreign study, and group
  foreign studies under one of your own investigations.

## Non-goals

- No copying of foreign content into the workspace — federation is read-only
  reference (foreign items keep living in their source checkout).
- No re-packaging of the ~29 ecosystem repos to ship studies/investigations in
  their wheels.
- SP-C (cross-repo referencing) is designed at a high level here but specced and
  built separately.

## Key constraint (drives the whole design)

| Content type   | Location in repo            | Shipped in wheel? | Federates from PyPI install? |
|----------------|-----------------------------|-------------------|------------------------------|
| Composites     | `pbg_<slug>/composites/` (inside package) | **yes** | **yes** (already works) |
| Studies        | `studies/` (repo top level) | no                | **no** |
| Investigations | `investigations/` (top level) | no              | **no** |

To federate studies + investigations, the module must be installed as a
**full-repo checkout**, not a PyPI wheel. The existing git-submodule install
path already does exactly this: it lands the full repo at
`<workspace>/external/<name>/` (with top-level `studies/`, `investigations/`,
`composites/`, and `workspace.yaml`) and records `install_path: external/<name>`.

## Decomposition

- **SP-A — Marketplace browse + install tab** *(implemented; one change here)*
- **SP-B — Federated discovery + provenance display** *(this spec)*
- **SP-C — Cross-repo referencing** *(future spec)*

---

## SP-A — Marketplace tab (status + remaining change)

**Implemented this iteration:**
- `lib/catalog.build_catalog(ws_root, full=True)` — returns the full canonical
  ecosystem registry, bypassing `registry.include` and the `registry.modules`
  override, each entry annotated with this workspace's install state.
- `GET /api/marketplace` (FastAPI) → `CatalogPayload` from `build_catalog(full=True)`.
- Registry page: third sub-tab **Marketplace** (`.js-authoring`, after
  "Discovered registry"), with its own search + installed/available filter +
  grid/list toggle. JS `_loadMarketplace` / `_renderMarketplace` /
  `_setMarketplaceView`, lazy-loaded on first open, reusing the shared
  `_renderModuleGrid` / `_moduleActionFor` / `_filterModules` helpers (extracted
  from the old `_renderCatalog`) and the existing `_installFromCatalog` flow.

**Remaining change (folded into SP-B implementation):**
- Marketplace installs must **force the full-repo git-checkout** path even when
  the catalog entry carries a `pypi_name`, so `studies/`+`investigations/` land
  on disk under `external/<name>/`. Options: pass a flag from the marketplace
  Install button (`{name, full_repo: true}`) that `catalog_install` honors by
  skipping the PyPI branch. Composites-only modules and modules with no git
  `source` fall back to the normal path (they simply contribute composites).

---

## SP-B — Federated discovery + provenance display

### Federation source

New module `lib/federation.py`:

- `linked_workspaces(ws_root) -> list[LinkedWorkspace]`
  - Scan `<ws_root>/external/*/` for directories containing `workspace.yaml`.
  - Additionally include any *editable-installed* module that resolves to a repo
    root with a `workspace.yaml` (e.g. `v2ecoli` installed `-e`), resolved via
    `importlib.util.find_spec(pkg)` → package dir → parent, matching the
    `catalog.py` install-state resolution. (Best-effort; skip on any error.)
  - Each `LinkedWorkspace` = `{repo: str, root: Path, layout: WorkspacePaths}`.
  - `repo` is the module's display name (from its `workspace.yaml` `name`, else
    the directory name).
  - Exclude the current workspace itself (dedupe by resolved root).

- `federated_studies(ws_root)`, `federated_investigations(ws_root)`,
  `federated_composites(ws_root)` — enumerate each linked workspace's content via
  its own `WorkspacePaths`, returning items tagged with:
  - `origin_repo`: the linked repo name
  - `read_only: true`
  - a **namespaced id** so foreign items never collide with local ones:
    `"<repo>::<local_id>"` (studies, investigations). Composites already use
    `"<pkg>.composites.<stem>"`, which is inherently namespaced.

All helpers are best-effort: a malformed linked workspace is skipped, never
raising, so the current workspace's own listings always render.

### Merge into existing listings

- **Composites** (`composite_lookup` / `composites_query` → `GET /api/composites`):
  already merges installed-package composites. Add `origin_repo` to every entry
  — derived from the spec-id package (`_derive_module_from_spec_id`), mapped to
  the owning module's display name; the workspace's own composites get
  `origin_repo: null`.
- **Investigations** (`investigations` / `investigation_views` →
  `GET /api/investigations`): append `federated_investigations(ws_root)`, tagged.
- **Studies** (rendered from the investigations payload / study index): append
  federated studies, tagged, and compute each study's `investigations` list
  (membership) across **both** local and federated investigations that reference
  it. Local investigations may reference a federated study (SP-C), which is why
  membership is computed over the merged set.

### Provenance data contract (per item)

```
origin_repo: string | null          # null / absent => this workspace
read_only:   boolean                # true for federated items
investigations: string[]            # studies only: investigation names it belongs to
```

Pydantic models (`lib/models.py`) for study / investigation / composite payload
entries gain these optional fields (default null/false/[] so existing consumers
and the published static bundle are unaffected).

### UI (the display requirements)

Frontend (`walkthrough.js`), reusing existing card renderers:

- **Study cards** (`_renderInvestigationSets` / study browse + side rail):
  origin-repo badge (e.g. `📦 v2ecoli`) when `origin_repo` is set; a
  `part of: <inv>, <inv>` line from `investigations[]`. Own studies show no
  badge (or a subtle "this workspace").
- **Investigation cards** (`_renderInvestigationSets`): origin-repo badge.
- **Composite cards** (`_renderComposites`, `#composite-cards`): origin-repo
  badge from `origin_repo`.
- **Read-only treatment**: foreign cards (`read_only: true`) hide mutate/run/
  delete affordances regardless of authoring mode (a `.federated-readonly`
  card class + CSS, distinct from `.js-authoring` which only tracks
  snapshot/remote mode). A single shared badge helper renders `📦 <repo>` so all
  three card types look consistent.

### Data flow

```
install (marketplace, full-repo)  ->  external/<name>/ on disk
        |
        v
lib/federation.linked_workspaces(ws_root)      # scans external/* + editable workspaces
        |
        +-> federated_composites -----> merged into GET /api/composites   (+origin_repo)
        +-> federated_investigations -> merged into GET /api/investigations (+origin_repo)
        +-> federated_studies --------> merged into study listings          (+origin_repo, +investigations[])
        |
        v
walkthrough.js card renderers  ->  origin-repo badge + membership line + read-only treatment
```

### Error handling

- Every federation helper swallows per-workspace errors and continues; a broken
  linked workspace never breaks the current workspace's page.
- Namespaced ids (`<repo>::<id>`) prevent foreign/local collisions.
- Published static bundle: `linked_workspaces` finds nothing (no `external/` in a
  bundle), so federated sections are simply empty — the new optional fields
  default to null/false/[] and the bundle renders unchanged.

### Testing

- `lib/federation.py` unit tests against a fixture workspace with an
  `external/<linked-ws>/` containing `workspace.yaml` + `studies/` +
  `investigations/` + a package `composites/`: assert each helper returns the
  linked content tagged with the right `origin_repo` and namespaced ids, and that
  a malformed linked workspace is skipped without raising.
- Endpoint tests (`dashboard_client` fixture): `GET /api/composites`,
  `/api/investigations`, and the study listing include the federated items with
  provenance fields; own items carry `origin_repo: null`.
- Regression: a workspace with no `external/` returns exactly today's payloads
  plus the new default fields.

---

## SP-C — Cross-repo referencing (future spec, sketch only)

Builds on SP-B's federated ids. Three capabilities:

1. **Foreign composite as baseline** — the study-create / baseline picker lists
   federated composites by their `<pkg>.composites.<stem>` id (already
   registry-resolvable), so a study's `baseline: [{name, composite}]` can point
   at a foreign composite.
2. **Compare against a foreign study** — an investigation's comparison/baseline
   config accepts a namespaced `<repo>::<study>` ref; report rendering resolves
   the federated study's `runs.db` from its linked-workspace root.
3. **Group foreign studies under my investigation** — an investigation spec's
   member list accepts federated study refs; SP-B's `investigations[]` membership
   computation then shows that foreign study as belonging to the local
   investigation.

## Rollout order

1. SP-A install-mode change (full-repo checkout).
2. SP-B federation layer + provenance display.
3. SP-C referencing (separate spec + plan).
