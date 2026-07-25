# Capability-matched Analysis Tools + Parsimony Viewer

**Date:** 2026-07-25
**Repos:** `vivarium-workbench` (this spec). Sub-project B (v2ecoli composite) is a *separate* spec — see "Sequencing & follow-ups".
**Branch/worktree:** `feat/analysis-tools-capability-match` at `/Users/eranagmon/code/vwb-analysis-tools` (off `origin/main`).

## Problem

The **Analysis Tools** tab lists tools (Pathway Tools / Omics Viewer, Data Explorer, saved 3D packs) with no relationship to the data in the DB. A user cannot tell which runs a tool can actually consume. Today compatibility is either hardcoded (Data Explorer), computed imperatively as study `targets` (Omics), or scanned per-pack. The tab also carries redundant chrome: an in-page `Analysis Tools` H2 duplicating the nav label, and a long descriptive paragraph.

Goal: **tools advertise what data shape they require; runs/studies advertise the shape they emitted; the tab matches them automatically.** The first concrete tool to land on this framework is the **Parsimony Viewer**, which reads 3D packs and shows saved views at pre-declared times.

## Goals

1. A small, documented **capability vocabulary** derived from what a run actually emits, plus artifact-sourced capabilities (3D packs).
2. Runs **advertise** their capabilities (lazy-computed, cached).
3. Tools **declare** a `requires` list; a matcher pairs each tool with its compatible runs/studies.
4. A **tools-first** tab: one card per tool, each listing its compatible runs/studies with a Launch/Open action; per-tool empty state.
5. Remove the redundant H2 and descriptive paragraph.
6. **Parsimony Viewer** as the first capability-matched tool (`requires: ["3d_pack"]`), presenting each study's saved views (Initial ~10 s, Pre-division) via the existing viewer's model-gallery, and surfacing the *existing* saved packs immediately.

## Non-goals / deferred

- **Sub-project B** — the new v2ecoli `baseline + parsimony` composite that *emits* declared-time snapshot packs. Separate spec; A defines the pack/capability contract it must satisfy.
- **v2ecoli Omics Viewer adopting `requires`** — its contributor keeps producing study `targets` unchanged; it upgrades to run-matching later by declaring `requires`.
- **Saved *camera* views** — "saved view" means a named time-snapshot in the model gallery, not a stored camera. No new camera-persistence feature.
- **Report cards / other saved-viz kinds** — unchanged; still shown on study pages.

---

## Part 1 — The capability-matching framework

### 1.1 Capability vocabulary

A capability is a lowercase string tag. Two sources:

**Store-derived** (from a run's emitted leaves, reusing `explorer_data._categorize_leaves`, which already buckets leaves into Mass / Bulk molecules / Fluxes / Listeners / Growth & division):

| Tag | Meaning (category) |
|-----|--------------------|
| `observables` | store readable with ≥1 leaf (base tag) |
| `mass` | Mass |
| `bulk_counts` | Bulk molecules |
| `fluxes` | Fluxes / FBA |
| `listeners` | Listeners |
| `growth_division` | Growth & division |

**Artifact-sourced** (from workspace files, not the store):

| Tag | Meaning |
|-----|---------|
| `3d_pack` | study has `viz/3d/*.pack.json` **or** a configured `ui.viz_viewer_urls` hosted pack |

Reserved for later (not computed this session): `ptools_tsv`, `report_card`.

The vocabulary lives in one documented constant (`lib/capabilities.py::CAPABILITY_TAGS`) with a one-line description each, so tools and runs share a single source of truth.

### 1.2 Runs advertise their shape — `lib/run_capabilities.py`

New module:

```python
def derive_capabilities(db_path, run_id=None, workspace=None) -> list[str]:
    """Store-derived capability tags for one run. Best-effort:
    unreadable / empty store -> []. Never raises."""
```

- Reuses `explorer_data.list_observables(db_path, run_id, workspace)` → `{categories: {...}}`.
- Maps present category names to tags (`Mass`→`mass`, `Bulk molecules`→`bulk_counts`, `Fluxes`→`fluxes`, `Listeners`→`listeners`, `Growth & division`→`growth_division`); adds `observables` when any leaf exists.
- Unreadable store or zero leaves → `[]` (chosen behavior: such a run matches no tool).

### 1.3 Persistence — lazy compute + cache column

- **Migration:** add `capabilities_json TEXT` to `runs_meta` (`run_registry.py::RUNS_META_DDL`, ~line 32) with an idempotent `ALTER TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check (same pattern used elsewhere for additive columns).
- **Backfill (lazy):** in `simulations_index` (`_row_to_dict`, ~line 149), if a run has no cached `capabilities_json`:
  - **completed** run → `derive_capabilities(...)`, write the result (including `[]`) back to `runs_meta`, and use it.
  - **in-progress / not-yet-completed** run → derive on the fly but **do not** cache (so a still-emitting run isn't frozen as empty); leave the column null to retry next scan.
- **New runs:** on run finalize (completion write in `run_registry`), compute and store `capabilities_json`.
- **Surface:** add `capabilities: list[str]` to `SimRow` (`models.py:53`) and include it in `/api/simulations`.

### 1.4 Tools declare `requires`

Extend the analysis-viewer descriptor contract (`analysis_viewers.py` docstring, lines 15–32) with an optional field:

```
"requires": list[str],   # capability tags a run/study must advertise; match if requires ⊆ capabilities
```

- Absent/empty `requires` → the tool is not run-matched; it renders its own `targets` as today (back-compat for the Omics Viewer).
- Built-in tools (Data Explorer, Parsimony Viewer) declare `requires` in the workbench (see 1.6, Part 2).

### 1.5 The matcher + unified payload — `lib/analysis_tools.py`

New module `build_analysis_tools(ws_root) -> list[dict]` composes, in one place, the tab's full tool list:

1. **External launcher viewers** — `analysis_viewers.viewers_public(ws_root)` (unchanged env-worker seam). Each descriptor may now carry `requires`.
2. **Built-in tools** — Data Explorer (`requires: ["observables"]`); Parsimony Viewer (`requires: ["3d_pack"]`, Part 2).
3. **Matching** — for each tool with non-empty `requires`, compute
   `compatible = [target for target in candidates if set(requires) <= set(target.capabilities)]`
   - run-level tools (Data Explorer) match against the runs index (`simulations_index`);
   - study-level tools (Parsimony Viewer) match against studies carrying `3d_pack` (see 2.1).
   - tools without `requires` keep their contributor-supplied `targets` verbatim.

Returns JSON-safe descriptors: `{id, title, description, kind, requires, matched: [{ref, label, detail, launch_hint}], unmatched_reason}`.

**Endpoint:** `GET /api/analysis-tools` (`api/app.py`), model `AnalysisToolsPayload` (`models.py`). The frontend makes this one call instead of the current split (`/api/analysis-viewers` + hardcoded Explorer + `/api/saved-visualizations`).

### 1.6 Tools-first UI

`static/walkthrough.js`:

- `_loadAnalysesPage()` (~1538) → `GET /api/analysis-tools`; render one card per tool via a single `_renderToolCard(tool)`.
- Each card: title, description, a **"Needs: `<requires>`"** line, then the matched list — each row `label · detail · [Launch/Open]`. Per-tool empty state: *"No compatible runs — needs `observables`."*
- Data Explorer row Launch → mounts the embedded Explorer focused on that run (`window.Explorer.mount`, existing) with `run_id` preselected.
- Parsimony Viewer row Open → the existing iframe viewer (Part 2), retaining `_render3dVizCard`'s iframe/`Open ↗` mechanics but driven from the matched study + its gallery manifest.
- Retire the per-pack card sprawl: `_render3dVizCard` becomes an internal helper invoked by the Parsimony Viewer tool card, not a top-level loop.

`templates/index.html.j2` (page `#page-visualizations`, ~640–652):

- Remove the `<h2 class="page-title">Analysis Tools</h2>` (line 642) — the nav rail already labels the tab.
- Remove the "Interactive scenes saved as workspace artifacts…" paragraph (line 646).
- The `#analyses-gallery` mount (line 647) stays; the "Saved visualizations" heading (line 645) becomes the tools gallery (retitle to "Tools", keep `#viz-count` as the tool count or drop it).

### 1.7 Snapshot / publish path

Keep `publish.py` working: `/api/analysis-tools` must have a static-bundle form (write `api/analysis-tools.json` at publish; degrade Launch/Open to disabled where there's no live backend, matching the existing snapshot pattern).

---

## Part 2 — Parsimony Viewer (Sub-project A)

The 3D render path already exists (`_render3dVizCard` → iframe → bundled `/parsimony-viewer/index.html` or hosted R2 `viewer_url`, three.js `pbg_parsimony/viewer/viewer.js`). A is **integration**, not new rendering.

### 2.1 `3d_pack` capability for studies

- A study advertises `3d_pack` if `saved_visualizations.build_saved_visualizations(ws_root)` finds `viz/3d/*.pack.json` for it, **or** `ui.viz_viewer_urls` has a hosted pack/manifest for it (both already read in `saved_visualizations.py:114–120`).
- Expose a helper `studies_with_3d_pack(ws_root) -> [{study, packs, viewer_url?}]` (in `saved_visualizations.py` or the new `analysis_tools.py`) the matcher consumes.

### 2.2 Parsimony Viewer tool descriptor

Built-in tool in `analysis_tools.py`:

```
{ id: "parsimony-viewer", title: "Parsimony Viewer",
  description: "3D molecular packing of a cell — saved views at declared times.",
  kind: "embed-3d", requires: ["3d_pack"] }
```

Matched targets = studies from 2.1. Each matched row Open → the iframe viewer with that study's **saved-views gallery**.

### 2.3 Saved views via the model gallery

The viewer already supports a named-snapshot dropdown via `?models=<manifest-url>` (`viewer.js:3356–3388`); the ecoli-3d publish flow already emits a two-entry `models.json` (Birth, Pre-division).

- **Hosted output:** if the study has a `viz_viewer_urls` entry pointing at a `models.json`, Open uses it directly (existing R2 gallery — "current saved output" for `ecoli-3d`).
- **Local packs:** the workbench **synthesizes** a per-study manifest from `viz/3d/*.pack.json`:
  - new route `GET /api/study/{study}/3d/models.json` → `[{name, file}]`, one entry per pack, `file` = the pack's `/parsimony-viewer`-relative URL;
  - snapshot **name** from the pack/meta (or filename), so declared-time packs surface as e.g. "Initial (10 s)", "Pre-division";
  - default selected view = the initial (~10 s) snapshot when present, else the first.
  - Open passes `?models=<that route>` to the bundled viewer.

### 2.4 "Current saved output available for viewing"

With 2.1–2.3, existing packs (local `viz/3d/*.pack.json` and the hosted ecoli-3d gallery) appear under the Parsimony Viewer card and open immediately — no composite run required. Snapshot naming for *new* declared-time packs is produced by Sub-project B.

---

## Data flow (after this spec)

```
run → runs_meta (+capabilities_json, lazy/cached) ─┐
studies/*/viz/3d/*.pack.json + ui.viz_viewer_urls ─┤
                                                    ▼
tools (external viewers.requires + built-in Data Explorer/Parsimony Viewer)
   → lib/analysis_tools.build_analysis_tools  (matcher: requires ⊆ capabilities)
   → GET /api/analysis-tools
   → walkthrough.js _renderToolCard  (tools-first; matched runs/studies per tool)
        Data Explorer row  → window.Explorer.mount(run_id)
        Parsimony row Open → iframe /parsimony-viewer?models=<study manifest | R2 url>
```

## File-by-file change list

**New**
- `lib/capabilities.py` — `CAPABILITY_TAGS` vocabulary + docs.
- `lib/run_capabilities.py` — `derive_capabilities(...)`.
- `lib/analysis_tools.py` — `build_analysis_tools(ws_root)` (compose + match); built-in tool descriptors; `studies_with_3d_pack`.

**Changed**
- `lib/run_registry.py` — `RUNS_META_DDL` + additive `capabilities_json` migration; write on finalize.
- `lib/simulations_index.py` — lazy backfill in `_row_to_dict`; include `capabilities`.
- `lib/models.py` — `SimRow.capabilities`; new `AnalysisToolsPayload`.
- `lib/analysis_viewers.py` — document `requires` in the descriptor contract.
- `lib/saved_visualizations.py` — `studies_with_3d_pack` helper (or in `analysis_tools.py`).
- `api/app.py` — `GET /api/analysis-tools`; `GET /api/study/{study}/3d/models.json`; publish static forms.
- `static/walkthrough.js` — `_loadAnalysesPage` → `/api/analysis-tools`; `_renderToolCard`; Explorer/3D rows; retire per-pack loop.
- `templates/index.html.j2` — remove H2 (642) + paragraph (646); retitle gallery.
- `publish.py` — emit `api/analysis-tools.json`; snapshot degrade.
- `lib/generate_ts.py` consumers — regenerate TS types for the new model.

## Testing

- `run_capabilities`: unit tests over fixture stores (zarr/parquet/sqlite) → expected tag sets; unreadable/empty → `[]`.
- `simulations_index`: completed run caches `capabilities_json`; in-progress run does not; `/api/simulations` carries `capabilities`.
- Matcher: `requires ⊆ capabilities` correctness; tool with no `requires` passes `targets` through; empty-state when nothing matches.
- `/api/analysis-tools`: shape + Parsimony Viewer lists a `3d_pack` study; Data Explorer lists an `observables` run.
- `models.json` route: synthesizes named entries from fixture packs; default = initial.
- Frontend: card renders matched rows + empty state (existing dashboard_client subprocess fixture).
- Publish: static bundle contains `api/analysis-tools.json`; Launch/Open degrade.

## Sequencing & follow-ups

1. **This spec (Framework + A)** → plan → implement → verify → PR to `vivarium-workbench` main.
2. **Sub-project B** (separate spec, `v2ecoli`): new `baseline_parsimony` composite — `baseline()` as base doc + a packing Step (ported from `v2e-3d/v2ecoli/structural/`) gated by `update_condition` on `global_time` (declared times, default ~10 s) and `full_chromosomes.division_time` (pre-division), writing named packs to `studies/<study>/viz/3d/*.pack.json`. The Parsimony Viewer from A renders them with no further UI work.
3. Later: Omics Viewer adopts `requires: ["ptools_tsv"]`; artifact tags `ptools_tsv` / `report_card` become computed capabilities.
