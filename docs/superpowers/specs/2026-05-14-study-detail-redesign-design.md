# Study Detail Redesign — Design

**Date:** 2026-05-14
**Status:** approved, ready for implementation plan
**Affects:** vivarium-dashboard — the `/studies/<name>` Study Detail page
**Repo / branch:** `vivarium-dashboard`, `main` (= the merged `studies-phase-1` studies/v3 work)

## Problem

The Study Detail page (`/studies/<name>` → `study-detail.html` + `study-detail.js`)
is a stack of six cards — Objective, Baseline, Variants, Runs, Visualizations,
Conclusion. It is hard to scan, the "Baseline" concept is tied to a single
composite, "Variants" are conflated with "interventions" (each variant nests an
`intervention` field), and the Overview surface is cluttered. The page needs to
become a clean, tabbed view with a clearer conceptual model.

## Conceptual model

A **Study** is organised around three distinct things:

| Concept | Definition |
|---|---|
| **Baseline** | the Study's set of composites — **one or more**. Each is a runnable composite document. |
| **Variant** | a single Baseline composite **plus parameter overrides**. A variant names which composite it derives from (`base_composite`). |
| **Intervention** | a standalone, text-described experimental condition. **Fully separate** from variants — no data link in this phase. |

Plus the existing **Runs** (run history + comparison) and **Visualizations**.

## Approach

**UI redesign + additive `interventions[]`, with a modest `baseline`/`variants`
reshape.** Restructure the page into five tabs, rename concepts, and:

- add a new top-level `interventions[]` field (purely additive),
- reshape `baseline` from a single composite to a **list** of composites,
- add a `base_composite` reference to each variant,
- drop the `groups` concept and the per-variant nested `intervention` from the
  *UI* (the fields may remain in stored data — see Deferred Cleanup).

This delivers the full visible redesign without a large schema-and-migration
rewrite, while accepting one bounded migration step (baseline → list, variants
gain `base_composite`).

## Prerequisites & dependencies

This redesign assumes **v3-shaped studies**. Today the v2ecoli workspace stores
v2-shaped specs (`baseline` as a bare string, `variants` carrying
`source`/`document`/`intervention`), which is why studies currently render with
blank fields. **Before or alongside implementation**, one of the following must
happen — it is **out of scope for this spec** and tracked separately:

- run `vivarium-dashboard migrate-investigations` to migrate workspace data to
  v3, **or**
- make `load_spec` / `study-detail.html` rendering tolerant of both shapes.

## Information architecture

The page becomes a tab bar with one panel per tab, in this order:

**Overview · Baseline · Variants · Interventions · Runs**

Tab switching is client-side (JS toggling an `.active` class on tab buttons and
panels), reusing the existing `registry-tab` / `registry-tab-panel` pattern from
`index.html.j2`'s Registry browser for visual consistency.

Renames from today's UI: "Baseline Composite" → **Baseline**; "Groups" →
**Variants**; the `groups` concept loses its UI entirely.

## Per-tab design

### Overview

**Layout A — "Notebook":** vertical and narrative, reading top to bottom like a
lab-notebook entry:

1. Header: study name + status badge.
2. **Objective** — prominent, the lead element (inline-editable, as today).
3. A thin counts strip: `N variants · N runs · N interventions`.
4. **Conclusion** — closing element (inline-editable, as today).

Reads/writes: reads `objective`, `conclusion`, `status`, and the counts; writes
`objective` and `conclusion` via the existing set-objective / set-conclusion
endpoints.

### Baseline

A Composite-Explorer-style view of the Study's composites (one or more). For
each composite: its id, its parameter list (displayed, not edited here), and the
composite structure/diagram the Composite Explorer already renders.

Affordances:
- **`+ Add composite`** — add a composite to the Study's Baseline.
- **`Remove composite`** — remove one (per composite).
- **`Run`** — per composite, runs that composite directly (the result appears in
  the Runs tab).
- **No `Perturb` button** — perturbing-into-a-variant happens in the Variants
  tab.

Reads `baseline` (the composite list). Writes via `study-baseline-add` /
`study-baseline-remove`.

### Variants

A list of the Study's variants. Each variant displays: **name · the composite it
is based on · its parameter overrides** (a small key→value table).

Affordances:
- **`+ New variant`** — flow: pick a base composite from the Study's Baseline →
  the baseline composite's parameters appear pre-filled with their defaults →
  the user changes values → save. The variant stores `{name, base_composite,
  parameter_overrides}`.
- **Edit params** — re-open the parameter form for an existing variant.
- **Delete** — remove a variant.
- **`Run`** — per variant, runs that variant (result appears in the Runs tab).

Scope for this phase: **parameter overrides only**. Initial-state editing and
process/module swaps are explicitly deferred. The Variants UI ignores any
per-variant nested `intervention` field present in legacy data.

### Interventions

A list of the Study's interventions. Each intervention is `{name, description}`
— `name` is a short list label, `description` is freeform text describing the
experimental condition.

Affordances:
- **`+ New intervention`** — form: name + a description textarea.
- **Edit** — edit name/description.
- **Delete** — remove an intervention.

This is the whole MVP — text only, no link to variants or runs. Writes via
`study-intervention-add` / `-update` / `-delete`.

### Runs

The existing runs table — columns: variant · label · steps · status · viz ·
actions — **plus** the Visualizations section folded in below it. All actions
are existing behaviour: view run, delete run, compare-selected, clear-all-runs,
add-visualization. This tab is largely a relocation of today's Runs +
Visualizations cards into one panel.

## Data model changes

On the study spec (`study.yaml` v3 / `spec.yaml` legacy):

- **`baseline`** — reshaped from a single composite to a **list** of composites.
  Shape: `baseline: [ {composite: <id>, params: {...}}, ... ]`.
- **`variants[]`** — each entry gains a **`base_composite`** field referencing
  one entry in `baseline`. Each variant: `{name, base_composite,
  parameter_overrides: {...}}`. Any pre-existing nested `intervention` field is
  left in stored data but unused by the UI.
- **`interventions[]`** — **new, optional** top-level array. Each entry:
  `{name, description}`. Specs without the key show an empty Interventions tab.
- **`groups[]`** — left in stored data, no UI. Not read or written by the
  redesigned page.
- Unchanged: `runs[]`, `visualizations[]`, `objective`, `conclusion`, `status`.

**Migration:** `migrate_v2_to_v3` (and `load_spec`'s migration path) must:
- wrap a single/legacy `baseline` into a one-element list, and
- give each existing variant a `base_composite` pointing at the (first/only)
  baseline composite.
This is a bounded, deterministic migration — no data loss, no ambiguity.

## Server endpoints

| Area | Endpoint | Status |
|---|---|---|
| Baseline | `POST /api/study-baseline-add` | **new** — add a composite to `baseline[]` |
| Baseline | `POST /api/study-baseline-remove` | **new** — remove a composite from `baseline[]` |
| Variants | `POST /api/study-variant-add` | **extend** — accept and store `base_composite` |
| Variants | `POST /api/study-variant-set-params` | **new** — replace a variant's `parameter_overrides` |
| Variants | `POST /api/study-variant-delete` | exists — reuse |
| Variants | `POST /api/study-run-variant` | exists — reuse |
| Baseline | `POST /api/study-run-baseline` | **extend** — accept a composite ref so a specific Baseline composite can be run |
| Interventions | `POST /api/study-intervention-add` | **new** |
| Interventions | `POST /api/study-intervention-update` | **new** |
| Interventions | `POST /api/study-intervention-delete` | **new** |
| Overview | `study-set-objective` / `study-set-conclusion` | exist — reuse |
| Runs | run / delete / compare / clear / add-viz | exist — reuse |

Existing `investigation-composite-*` handlers should be reviewed first — some
may be adaptable for the Baseline add/remove rather than written fresh.

## Target files

- `vivarium_dashboard/templates/study-detail.html` — cards → 5-tab layout.
- `vivarium_dashboard/static/study-detail.js` — tab switching; wiring for the
  new/changed endpoints; the variant and intervention forms.
- `vivarium_dashboard/server.py` — the new endpoints; `_render_study_detail_html`
  passing the reshaped spec; `_get_study_detail_page` unchanged (already fixed).
- `vivarium_dashboard/lib/investigations.py` (and/or `spec_migration.py`) — the
  `migrate_v2_to_v3` reshape (baseline → list, variants gain `base_composite`)
  and v3 validation of the new shapes.
- `vivarium_dashboard/static/style.css` — tab-bar styling if not already covered
  by the shared `registry-tab` styles.

## Testing

Test-driven, following the repo's existing patterns:

- **Schema / migration:** the `baseline` → list reshape and `variants` gaining
  `base_composite` get migration tests and `load_spec` / v3-validation tests
  (style of `test_study_dir_resolution.py`, `test_investigations.py`).
- **Endpoints:** the new handlers — `study-baseline-add/remove`,
  `study-variant-set-params`, `study-intervention-add/update/delete` — get
  handler tests (the `_post_*_for_test` pattern in `test_study_handlers.py`).
- **Page render:** `tests/test_study_detail_page.py` extends to assert the
  5-tab structure renders and each tab panel is present.
- Each unit gets a failing test first; the implementation plan sequences this.

## Out of scope / deferred

- **Variant scope beyond parameters** — initial-state editing and
  process/module swaps in variants are deferred to a later phase.
- **Formal schema cleanup** — removing the per-variant nested `intervention`
  field and the `groups` field from stored specs / the v3 schema. The redesigned
  UI simply ignores them; a later tidy-up can remove them.
- **The v2→v3 workspace-data migration** — see Prerequisites; tracked
  separately.
- **Interventions ↔ Variants/Runs linkage** — Interventions are text-only this
  phase; any future linking (e.g. a run citing an intervention) is out of scope.
