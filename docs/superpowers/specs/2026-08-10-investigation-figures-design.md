# Investigation Figures — accessible, downloadable paper figures

**Status:** design approved (brainstorming)
**Repos:** `vivarium-workbench` (the capability) + `spatio-flux` (content for the `paper-figures` investigation)
**Date:** 2026-08-10

## Problem

An investigation's "final figures" (per-study panels stitched into publication
figures) are currently scattered and hard to get:

- They live only inside each member study's Visualizations tab (as a "Figure N
  (composite)" chart) — you must know the study structure to find them.
- The Visualizations tab only *displays*; there is no download affordance.
- The Runs-tab "Viz" button reads the composite-run engine's `viz.json`, which
  renders only composite-declared visualizations — it never includes a
  study-declared figure, so re-running does not surface them.
- Nothing presents the investigation's figures as one coherent, captioned,
  downloadable set for a reader (live or on the published read-only snapshot).

Goal: make an investigation's figures **discoverable, downloadable, presentable,
and shareable** — with the same behavior live and in the read-only snapshot.

## Approach

A **general** workbench capability (any investigation opts in), not bespoke to
`paper-figures`. Two surfaces:

1. **Headline — `↓ figures` on the investigation card** (top level, next to
   `↓ report` / `↓ notebook`): one click downloads a zip of every figure
   (SVG + PNG). This is the primary accessibility win — no need to open the
   investigation or know its studies.
2. **Investigation "Figures" tab** (presentation): each figure shown with its
   number, title, caption, and per-figure `↓ SVG` / `↓ PNG` links.

Figures are **not** rebuilt here — the existing stitcher
(`spatio-flux/scripts/build_paper_figures.py`) already writes
`studies/<slug>/visualizations/figure_<N>.{svg,png}` and registers a study viz
entry. This capability only *surfaces* those files.

## Data model (hybrid: derive + optional overrides)

New resolver `vivarium_workbench/lib/investigation_figures.py`:

```
build_investigation_figures(ws_root, name) -> list[Figure]
```

- **Auto-discover:** for each member study of the investigation, look for a
  stitched composite `studies/<slug>/visualizations/figure_<N>.svg` (with a
  `.png` sibling). Each becomes a figure.
  - `number` ← parsed from the filename (`figure_7` → 7) or the slug
    (`fig-07` → 7).
  - `title` ← study `title`.
  - `caption` ← study `claim`, falling back to `purpose.mechanism`.
- **Optional override** in `investigation.yaml` (any subset per figure):

  ```yaml
  figures:
    - study: fig-07
      number: 7          # optional (derived)
      title: "…"         # optional (derived from study.title)
      caption: "…"       # optional (derived from study.claim/purpose)
      order: 1           # optional (derived from number)
      include: true      # optional (default true; false hides an auto figure)
  ```

- **Two categories per investigation:**
  - **Post-study composites** (`figure_<N>`) — the "final figures," one per figure
    study. These are the presentation stars (Figures tab) and get numbers/captions.
  - **Study figures** (the panels) — every *other* image visualization declared on
    each member study (loom SVGs, sim PNGs, gifs). These are the raw components.

- **Output:**

  ```
  {
    composites: [ {number, title, caption, study, svg_url, png_url}, … ],  # ordered
    files:      [ {study, arcname, rel_path}, … ],   # EVERY figure file, for the zip
    n_composites: int,                               # card-gating count
  }
  ```

  `composites` drives the Figures tab + per-figure downloads (URLs, **not** inlined
  bytes). `files` is the flat, comprehensive set for the zip — panels *and*
  composites across **all** member studies. Ordering of composites: by `order`
  when given, else `number`.

The resolver never raises; a missing file or malformed `figures:` entry is
skipped so the rest still resolve.

### Download scope — the full investigation figures

The `↓ figures` zip is the **complete** figure archive for the investigation:
every member study's declared image figures (the panels) **and** the post-study
composites, organized `<study>/<filename>` (e.g. `fig-07/7a-community-dfba.svg`,
`fig-07/figure_7.svg`). This is deliberately comprehensive ("the studies figures
and the post-studies figures"), so the zip can be tens of MB — acceptable for an
explicit download.

**Card gating:** `↓ figures` appears only when the investigation has ≥1
post-study composite (or an explicit `figures:` block). This keeps it off
investigations that merely have scattered study charts (e.g. the test-suite),
while paper-figures — which has composites — offers the full archive.

## Payload wiring

- `lib/report_views.build_iset_detail(ws_root, name)` gains a `figures: [...]`
  array (from the resolver) and a `figures_zip_url`. Byte-parity between the
  live builder and the snapshot `api/investigation/<slug>.json` (publish already
  calls `build_iset_detail`).
- The investigation-summaries payload (card data) gains `n_figures` so the card
  can show `↓ figures` only when the investigation actually has figures.

## Live routes (`vivarium_workbench/api/app.py`)

Mirror the existing per-investigation download routes (report/notebook):

- `GET /api/investigation/{slug}/figure/{n}.{ext}` — serve
  `studies/<study>/visualizations/figure_<n>.<ext>` (`ext` ∈ `svg|png`).
  404 `{"error": …}` when absent. `Content-Type` per ext; `Cache-Control:
  no-store` (figures are regenerated).
- `GET /api/investigation/{slug}/figures.zip` — build the zip on the fly
  (`io.BytesIO` + `zipfile.ZIP_DEFLATED`), one entry per figure per format,
  named `figure_<n>.svg` / `figure_<n>.png`. Mirrors the existing
  `lib.composite_run_views.build_composite_run_zip`. 404 when the investigation
  has no figures.

Resolver logic lives in the lib; routes are thin.

## Snapshot staging (`vivarium_workbench/publish.py`)

In the per-investigation loop (where `<slug>.json`, graph, notebook are emitted):

- Stage each figure file to `out/figures/<slug>/figure_<n>.{svg,png}`.
- Build + stage a prebuilt `out/figures/<slug>/figures.zip`.
- Rewrite the payload's `svg_url` / `png_url` / `figures_zip_url` to
  `<base_path>/figures/<slug>/…` (same base-path prefixing the inputs-download
  staging uses).

So the card `↓ figures` and the tab's per-figure links resolve to real static
files in the bundle — identical UX to live.

## Frontend (`vivarium_workbench/static/walkthrough.js`)

- **Card action.** Add `↓ figures` next to `↓ report` / `↓ notebook` on the
  investigation card (~L9343) and the detail-header actions (~L9987), gated on
  `iset.n_figures > 0`. Handler `window._vivFiguresFromCard(ev, name)` mirrors
  `_vivNotebookFromCard`: resolve `/api/investigation/<slug>/figures.zip` (live)
  vs `<base>/figures/<slug>/figures.zip` (snapshot), then `<a download>`-click.
- **Figures tab.** Add a `figures` tab to `_invDetailTab` (button + panel, ~L18389)
  and a `_renderInvestigationFigures(figures)` renderer: an optional top
  `↓ Download all (.zip)` button, then one card per figure — `Figure N — Title`,
  `<img src=svg_url>` (SVG scales crisply), caption, and `↓ SVG` / `↓ PNG`
  links. Empty state when `figures` is empty. Reuses existing card CSS.

## spatio-flux content

Add an optional `figures:` block with authored captions + order to
`investigations/paper-figures/investigation.yaml`, folded into the open **PR #34**
(whose stitched composites the resolver already auto-discovers — figures appear
even before captions are authored). No stitcher changes.

## Scope guards (YAGNI)

- No change to how figures are *built* — only how they are surfaced.
- Keep the per-study composite viz entries (still shown in each study's own
  Visualizations tab).
- No new frontend libraries; the zip is built server/snapshot-side, never
  client-side.
- URLs in the payload, never inlined image bytes (keeps the investigation
  payload light — the paper figures are ~9.5 MB of SVG).

## Testing

- `tests/` unit test for `build_investigation_figures`: auto-discovery from a
  fixture study dir; override merge (number/caption/order/include); missing-file
  and malformed-entry tolerance; ordering.
- Staging test: `publish.py` copies figure files + `figures.zip` and rewrites
  URLs with the base path.
- Route smoke test: `/figure/<n>.svg` 200 + content-type; `/figures.zip` 200 +
  is a valid zip with expected members; 404 when absent.

## Surfaces NOT used (and why)

- `/api/investigation/<slug>/report` (serves `reports/index.html`) — orphan:
  nothing in the UI links it and publish does not stage it.
- Composite-run `viz.json` / Runs-tab "Viz" — composite-scoped; never carries
  study-declared figures.
