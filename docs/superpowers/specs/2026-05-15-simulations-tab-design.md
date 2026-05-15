# Simulations Tab — Design

**Date:** 2026-05-15
**Repo:** `vivarium-dashboard`
**Branch:** `simulations-tab` (off `main`)
**Status:** Approved design — ready for implementation planning

## Goal

Add a left-rail **Simulations** tab to the dashboard that lists every
persisted run across the workspace and lets the user delete entries
completely — DB rows, run artifacts, and Study references — from a single
view.

## Motivation

Today, runs live in two kinds of SQLite databases:

- `<workspace>/.pbg/composite-runs.db` — Composite Explorer scratch runs.
- `<workspace>/studies/<name>/runs.db` — one per Study (baseline + variants).

The Composite Explorer's recent-runs list shows only the workspace-level
scratch DB; the Study Detail page shows only one study's DB. There is no
single place to see *all* of the runs in a workspace, and no place to
prune them. As workspaces accumulate dozens or hundreds of runs across
many studies, that gap becomes the principal source of "what's actually
in this workspace?" confusion and disk bloat. The Simulations tab is
that single place.

## Architecture

A **server-side aggregator** (`simulations_index.py`) walks every SQLite
DB in the workspace, collects `runs_meta` rows, cross-references each
`run_id` against every `study.yaml`'s `runs[]` array, and returns one
sorted list. A **delete endpoint** does the full delete: DB rows + per-step
`history` rows + the `.pbg/runs/<run_id>/` directory + unlink from any
`study.yaml`'s `runs[]`. The frontend renders a single table on a new
`#simulations` page.

Multi-DB knowledge lives in one pure module; the HTTP layer is two thin
wrappers; the JS layer is one fetch + render + delete handler. Each unit
has one responsibility.

## Tech Stack

Python 3.12, `sqlite3` (WAL, busy-timeout already set by `composite_runs.connect`),
`pyyaml` for `study.yaml` round-trip. Frontend: vanilla JS in the existing
`walkthrough.js`/`index.html.j2` style — no new dependency. Testing:
pytest (`tests/_fixtures/ws_increase_demo` already in place).

## Components & File Structure

### New files

- **`vivarium_dashboard/lib/simulations_index.py`** — the pure aggregator.
  Public functions:
  - `list_simulations(workspace: Path) -> list[dict]` — walks every SQLite
    DB, gathers `runs_meta` rows, cross-references every `study.yaml`,
    returns one sorted list.
  - `delete_simulation(workspace: Path, run_id: str) -> dict` — full
    delete: `runs_meta` row + `history` rows + `.pbg/runs/<run_id>/`
    dir + unlink from every referencing `study.yaml`. Returns a summary
    dict.
  No HTTP, no module globals — trivially unit-testable.

- **`tests/test_simulations_index.py`** — unit tests for the aggregator and
  the delete logic.

- **`tests/test_simulations_api.py`** — integration tests against the
  in-process dashboard server (mirrors `test_composite_explorer_api.py`).

### Modified files

- **`vivarium_dashboard/server.py`** — two thin handlers and the routing.
  - `_get_simulations()` → `GET /api/simulations`.
  - `_delete_simulation()` → `DELETE /api/simulations/<run_id>`.
  - Routing additions in `do_GET` and `do_DELETE`.

- **`vivarium_dashboard/templates/index.html.j2`** — add `<a href="#simulations">`
  rail link between Investigations and Visualizations; add a
  `<div data-page="simulations">` page section with the table scaffolding
  (heading + lead + filter input + `<table>` thead + empty `<tbody>` +
  empty-state placeholder).

- **`vivarium_dashboard/static/walkthrough.js`** — add `"simulations"` to
  the valid-pages list in `fromHash()`; add `_initSimulations()` that
  fetches `/api/simulations` and renders rows; add `_deleteSimulation(run_id)`
  that opens the confirm dialog and calls the DELETE endpoint.

## Data Flow

### `list_simulations(workspace)` — aggregation

1. **Discover DBs.** Two paths:
   - `<workspace>/.pbg/composite-runs.db` (if file exists).
   - `<workspace>/studies/<name>/runs.db` for every entry in `studies/`
     that is a directory and contains a `runs.db`.
2. **Pull metadata.** From each DB:
   `SELECT run_id, spec_id, sim_name, label, started_at, completed_at,
   n_steps, status, progress_step FROM runs_meta`.
   Use `composite_runs.connect()` so WAL + busy-timeout apply uniformly.
   Tag each row with `db_path` (workspace-relative string).
3. **Cross-reference Studies.** Walk every
   `<workspace>/studies/<name>/study.yaml`. Parse the `runs:` entry —
   accept either a list of strings (`runs: [r-1, r-2]`) or a list of
   dicts (`runs: [{run_id: r-1, ...}, ...]`). Build a
   `run_id → [study_name…]` map.
4. **Annotate.** For each row, set `studies` to the list of names that
   reference its `run_id` (often empty for scratch runs).
5. **Sort.** Newest first by `started_at` desc.
6. **Return.** Each dict: `{run_id, spec_id, sim_name, label, status,
   n_steps, progress_step, started_at, completed_at, db_path, studies}`.

### `GET /api/simulations`

Thin: call `list_simulations(WORKSPACE)`, return `{simulations: [...]}`.
`200` on success, `500 {error}` on internal failure (the aggregator
itself should not crash on a single malformed DB or yaml — see Error
Handling — but wrap the call for safety).

### `delete_simulation(workspace, run_id)` — full delete

1. **Resolve.** Find which DB the `run_id` lives in (call the aggregator
   or do a direct scan; aggregator reuse is simpler). If none, raise a
   `RunNotFound` sentinel exception (handler translates to `404`).
2. **Delete DB rows.** In that DB, single transaction:
   `DELETE FROM history WHERE simulation_id = ?` then
   `DELETE FROM runs_meta WHERE run_id = ?`. Capture the row counts.
3. **Delete run dir.** If `<workspace>/.pbg/runs/<run_id>/` exists,
   `shutil.rmtree(..., ignore_errors=True)`. Capture whether it actually
   existed.
4. **Unlink from studies.** For every `study.yaml` whose `runs[]`
   contains this `run_id`: load → remove the entry (supporting both
   string and dict shapes) → `yaml.safe_dump(sort_keys=False)` →
   atomic write (write-then-rename). Capture each study name unlinked.
5. **Return summary.** `{deleted_rows: 1, deleted_history: N,
   removed_dir: bool, unlinked_studies: [name…], errors: [...]}`. The
   `errors` list is empty on the happy path; contains per-file error
   strings on partial failure (see Error Handling).

### `DELETE /api/simulations/<run_id>`

Thin: call `delete_simulation(WORKSPACE, run_id)`. Return the summary
with HTTP `200`. On `RunNotFound`, return `404 {error: "run not found"}`.

**This endpoint does NOT go through `_active_branch_action`.** Run DBs
and `.pbg/runs/` are gitignored. `study.yaml` edits *are* git-tracked,
but pruning a simulation is a cleanup operation, not authored content —
wrapping it in a stage commit would surprise the user and trip the
dirty-tree check unnecessarily. The user's normal Studies-tab edits
remain commit-wrapped as before; this endpoint just modifies files
directly, leaving the `study.yaml` change in `git status` like any other
working-tree edit.

## UI Layout

### Page heading + lead

> ### Simulations
> All persisted runs across this workspace, gathered from
> `.pbg/composite-runs.db` and every `studies/<name>/runs.db`. Delete a
> row to remove its DB rows, run artifacts, and any Study references.

### Empty state

> No simulations yet. Run a composite from the Composite Explorer or
> from a Study to see entries here.

### Table

One row per simulation. Columns in order:

| Column | Source | Notes |
|---|---|---|
| **Composite** | `spec_id` | `<code>` block; last segment bold for scannability. |
| **Studies** | `studies` annotation | Clickable chips → `#studies/<name>` deep-link. Empty for scratch runs. |
| **Status** | `status` | Colored chip: `completed` green, `running` blue, `failed` red, `orphaned` gray. |
| **Steps** | `n_steps` / `progress_step` | For `running`, render `progress/total`. |
| **Label** | `sim_name` or `label` | `sim_name` for Study runs (e.g. `baseline`, `variant-foo`); fall back to `label` for scratch runs (auto-label from overrides). |
| **Started** | `started_at` | Relative ("2h ago"); full timestamp on hover. |
| **Run** | `run_id`, `db_path` | Short run-id chip (last 6 hex chars). Tooltip shows the full `run_id` *and* `db_path` (`.pbg/composite-runs.db` or `studies/<name>/runs.db`). Avoids a separate noisy column for the source DB. |
| **Delete** | — | Trash icon → confirm dialog. |

### Filter

One client-side text filter at the top filters across **Composite**,
**Studies**, and **Label** simultaneously. No server-side filter API —
the list is metadata-only and small.

### Delete confirmation dialog

> **Delete simulation `<run_id>` (composite `<spec_id>`)?**
>
> This will permanently remove:
> - 1 `runs_meta` row in `<db_path>`
> - **N** `history` rows (N steps of trajectory data)
> - The run directory `.pbg/runs/<run_id>/` *(if it exists)*
> - References from **K** `study.yaml`(s): *<study names>*
>
> [Cancel] [Delete]

Counts come from a small pre-flight pass before opening the modal
(cheap — single-row count on `history`, existence check on the run
dir, the `studies` annotation is already in hand from the listing).

On confirm: `DELETE /api/simulations/<run_id>` → re-fetch
`/api/simulations` → re-render. Toast on success or partial failure.

## Error Handling

| Failure | Behavior |
|---|---|
| DB file missing/empty | Skip it; don't error. A workspace with no `.pbg/composite-runs.db` yet, or a brand-new study with no `runs.db`, simply contributes zero rows. |
| DB locked (concurrent writer) | `connect()` already sets `PRAGMA busy_timeout=5000`. If a read still times out, treat *that* DB as empty for this request; log a warning; rest of the list renders. UI shows a small "1 DB unavailable, refresh in a moment" banner if any DB was skipped. |
| Malformed `study.yaml` | `yaml.safe_load` raises → catch, log, treat as `runs: []` for that study. Other studies unaffected. |
| Unknown `run_id` on DELETE | `404 {error: "run not found"}`. |
| DELETE partial failure | E.g. DB rows deleted but a `study.yaml` rewrite fails (read-only, permission, etc.). Each file write is in its own try/except. Return `200` with `errors: [...]` populated. The run is functionally gone (DB rows removed) — the dangling study ref is a follow-up. UI shows a warning toast naming the partial issue. |
| `shutil.rmtree` permission failure | Use `ignore_errors=True`. `removed_dir: false` surfaces in the summary, doesn't abort. |
| GET aggregator hard crash | `500 {error}`. UI shows the message in a banner with Retry. Page doesn't go blank. |
| Delete while run is still `running` | The confirm dialog flags it: *"This simulation is still running. Deleting now will orphan the detached process."* Delete proceeds if confirmed; the orphan write attempt later fails harmlessly inside SQLite. |
| `WORKSPACE` unset (test edge) | `500 {error: "no workspace"}` — same shape as other endpoints. |

**Invariant:** the aggregator is read-only; the DELETE never blurs the
gitignored vs git-tracked boundary. Run DBs and `.pbg/runs/` are
gitignored. `study.yaml` edits are intentionally left in the working
tree (not auto-committed) — same UX as editing a study from the
Studies tab.

## Testing

### Unit tests (`tests/test_simulations_index.py`)

- **`test_list_simulations_walks_workspace_and_studies_dbs`** — tmp
  workspace with `.pbg/composite-runs.db` (1 scratch run) and
  `studies/foo/runs.db` (1 baseline run); assert both rows present with
  correct `db_path`s and reverse-chronological order.
- **`test_list_simulations_cross_references_study_yaml`** — seed a
  run_id in `studies/foo/runs.db`; write `studies/foo/study.yaml` with
  `runs: [<run_id>]`; assert the row gets `studies: ["foo"]`.
- **`test_list_simulations_accepts_dict_runs_shape`** — same as above
  but `runs: [{run_id: <run_id>, ...}]`; assert annotation still works.
- **`test_list_simulations_run_in_multiple_studies`** — same run_id
  referenced from two `study.yaml`s; assert `studies` contains both.
- **`test_list_simulations_tolerates_missing_db`** — workspace with no
  `.pbg/composite-runs.db` and one empty study dir; assert `[]`.
- **`test_list_simulations_tolerates_malformed_study_yaml`** — invalid
  YAML in one study; assert listing still returns rows, that study
  contributes no annotations.
- **`test_delete_simulation_full_pass`** — seed a run + history +
  `.pbg/runs/<id>/request.json` + a study.yaml reference; call
  `delete_simulation`; assert each artifact gone and summary matches.
- **`test_delete_simulation_unknown_raises_run_not_found`** — call with
  nonexistent run_id; assert raises the sentinel.
- **`test_delete_simulation_partial_failure_records_errors`** —
  make a `study.yaml` read-only so its rewrite fails; assert DB
  deletion succeeded; assert summary `errors` lists the file.

### Integration tests (`tests/test_simulations_api.py`)

Pattern from `test_composite_explorer_api.py`: spin up the dashboard
server subprocess against a copy of `tests/_fixtures/ws_increase_demo`,
exercise endpoints via `urllib`.

- **`test_get_api_simulations_lists_runs`** — POST a composite-test-run
  (detached pipeline); poll to completion; `GET /api/simulations`
  returns 200 with the run present, `status='completed'`, `studies: []`.
- **`test_delete_api_simulation_removes_everything`** — same setup;
  `DELETE /api/simulations/<run_id>` → 200 + summary; subsequent GET no
  longer has the row; `GET /api/composite-run/<id>/status` now 404.
- **`test_delete_api_simulation_404_unknown`** — assert 404 + error
  shape.

### Git-hygiene test

- **`test_delete_does_not_dirty_run_artifacts`** — call
  `delete_simulation`; assert `git status` only shows the
  `study.yaml` change (the expected modification), not any
  `.pbg/runs/` or run-db change (those are gitignored).

### Manual smoke

Listed in the PR test plan, not automated:
- Open `#simulations` — table renders, status chips colored, Studies
  chips clickable to their detail page.
- Run a composite from the Composite Explorer; refresh — row appears.
- Run a Study baseline; refresh — row appears with the Study chip.
- Trash icon → confirm dialog shows correct row/history/study counts.
- Confirm → table refreshes, row gone. `git status` shows the
  `study.yaml` edit.

## Out of Scope

- **Other emitter types** (`RAMEmitter`, `JSONEmitter`, `ConsoleEmitter`).
  The aggregator is named `simulations_index` rather than
  `sqlite_simulations` deliberately — future per-emitter adapters can
  be added without changing the API shape. No adapter abstraction is
  built now (YAGNI).
- **Bulk delete / multi-select.** Single-row delete with confirm is the
  approved UX.
- **Server-side filtering / pagination.** Client-side filter only; the
  list is metadata-rows and stays small.
- **Auto-committing `study.yaml` edits.** Out of scope per Section "Data
  Flow"; the user's Studies-tab flow remains the source for committed
  study edits.
- **Restoring deleted simulations.** Delete is final; the recover path
  is "re-run".

## Non-Goals

- Replacing the Composite Explorer's recent-runs list. The Explorer's
  list stays as a focused per-composite view; the Simulations tab is
  the workspace-wide view.
- Replacing the Study Detail page's runs section. Per-study still has
  its own affordances (compare variants, etc.). The Simulations tab
  duplicates the runs *list* in service of cross-cutting cleanup, not
  the study-specific affordances.
